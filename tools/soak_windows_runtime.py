"""Long-running Windows smoke test for the local browser and control services."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import statistics
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def request(url: str, data: bytes | None = None, content_type: str = "") -> tuple[str, float, int]:
    headers = {"Content-Type": content_type} if content_type else {}
    started = time.perf_counter()
    response = urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=120)
    body = response.read()
    elapsed_ms = (time.perf_counter() - started) * 1000
    if not 200 <= response.status < 300:
        raise RuntimeError(f"{url} returned HTTP {response.status}")
    return url, elapsed_ms, len(body)


def windows_rss(pid: int) -> int | None:
    if os.name != "nt":
        return None

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    handle = ctypes.windll.kernel32.OpenProcess(0x1010, False, pid)
    if not handle:
        return None
    try:
        counters = ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(counters)
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize) if ok else None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def discover_windows_pids(ports: set[int]) -> list[int]:
    if os.name != "nt":
        return []
    port_list = ",".join(str(port) for port in sorted(ports))
    command = (
        "$ports=@(" + port_list + "); "
        "(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object {$ports -contains $_.LocalPort} | "
        "Select-Object -ExpandProperty OwningProcess -Unique) -join ','"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=0x08000000,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [int(value) for value in completed.stdout.strip().split(",") if value.strip().isdigit()]


def process_samples(ports: set[int], configured_pids: list[int]) -> list[dict[str, Any]]:
    if configured_pids:
        return [
            {"pid": pid, "rss_bytes": rss}
            for pid in configured_pids
            if (rss := windows_rss(pid)) is not None
        ]

    try:
        import psutil
    except ImportError:
        return []

    samples = []
    seen = set()
    for connection in psutil.net_connections(kind="tcp"):
        if not connection.laddr or connection.laddr.port not in ports or connection.pid in seen:
            continue
        seen.add(connection.pid)
        try:
            process = psutil.Process(connection.pid)
            samples.append(
                {
                    "pid": connection.pid,
                    "port": connection.laddr.port,
                    "name": process.name(),
                    "rss_bytes": process.memory_info().rss,
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-sec", type=int, default=1800)
    parser.add_argument("--interval-sec", type=float, default=5.0)
    parser.add_argument("--tts-every-sec", type=int, default=60)
    parser.add_argument("--stage-url", default="http://127.0.0.1:5174/")
    parser.add_argument("--control-url", default="http://127.0.0.1:8765")
    parser.add_argument("--process-pid", type=int, action="append", default=[])
    parser.add_argument("--report", type=Path, default=Path("main/reports/windows_runtime_soak.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.duration_sec <= 0 or args.interval_sec <= 0:
        raise SystemExit("duration-sec and interval-sec must be positive")

    started_at = datetime.now(timezone.utc)
    started_monotonic = time.monotonic()
    deadline = started_monotonic + args.duration_sec
    next_tts = time.monotonic()
    latencies: dict[str, list[float]] = {}
    failures: list[dict[str, Any]] = []
    memory: list[dict[str, Any]] = []
    request_count = 0
    tts_count = 0
    silence_pcm = b"\x00\x00" * 8_000
    monitored_pids = args.process_pid or discover_windows_pids({5174, 8765})
    health_urls = [
        args.stage_url,
        f"{args.control_url}/health",
        f"{args.control_url}/voices",
        f"{args.control_url}/asr-health",
    ]

    while time.monotonic() < deadline:
        cycle_started = time.monotonic()
        requests = [(url, None, "") for url in health_urls]
        requests.append((f"{args.control_url}/asr", silence_pcm, "audio/pcm; rate=16000"))
        if time.monotonic() >= next_tts:
            payload = json.dumps(
                {"text": "Windows 稳定性测试。", "rate": 1.0, "voice": "sherpa_vits", "reference": "soft_girl"},
                ensure_ascii=False,
            ).encode("utf-8")
            requests.append((f"{args.control_url}/tts", payload, "application/json"))
            next_tts = time.monotonic() + args.tts_every_sec
            tts_count += 1

        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            futures = [executor.submit(request, *request_args) for request_args in requests]
            for future in as_completed(futures):
                request_count += 1
                try:
                    url, elapsed_ms, _ = future.result()
                    route = urlparse(url).path or "/"
                    latencies.setdefault(route, []).append(elapsed_ms)
                except Exception as exc:  # noqa: BLE001 - soak report must retain all failures
                    failures.append({"at": datetime.now(timezone.utc).isoformat(), "error": str(exc)})

        memory.append(
            {
                "at_sec": round(time.monotonic() - started_monotonic, 1),
                "processes": process_samples({5174, 8765}, monitored_pids),
            }
        )
        remaining = args.interval_sec - (time.monotonic() - cycle_started)
        if remaining > 0:
            time.sleep(min(remaining, max(0, deadline - time.monotonic())))

    latency_summary = {
        route: {
            "count": len(values),
            "mean_ms": round(statistics.fmean(values), 2),
            "max_ms": round(max(values), 2),
            "p95_ms": round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 2),
        }
        for route, values in latencies.items()
    }
    report = {
        "ok": not failures,
        "started_at": started_at.isoformat(),
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "duration_sec": args.duration_sec,
        "request_count": request_count,
        "tts_count": tts_count,
        "monitored_pids": monitored_pids,
        "failure_count": len(failures),
        "failures": failures[:100],
        "latency": latency_summary,
        "memory_samples": memory,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("ok", "duration_sec", "request_count", "tts_count", "failure_count")}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
