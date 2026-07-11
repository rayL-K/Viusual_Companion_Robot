from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from veyrasoul.memory import HybridRetriever, MemoryDraft, MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entries", type=int, default=2_000)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="veyrasoul-memory-") as directory:
        store = MemoryStore(Path(directory) / "memory.db")
        drafts = [
            MemoryDraft(
                "episode",
                f"记忆 {index}",
                f"第 {index} 次多模态机器人讨论，用户坐在书桌前。",
                "benchmark",
                (index % 10) / 10,
            )
            for index in range(args.entries)
        ]
        started = time.perf_counter()
        store.add_entries(drafts)
        ingest_ms = (time.perf_counter() - started) * 1000
        retriever = HybridRetriever(store)
        samples: list[float] = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            result = retriever.retrieve("书桌前的多模态机器人", 8)
            samples.append((time.perf_counter() - started) * 1000)
        samples.sort()
    report = {
        "entries": args.entries,
        "iterations": args.iterations,
        "batch_ingest_ms": round(ingest_ms, 3),
        "retrieval_mean_ms": round(statistics.mean(samples), 3),
        "retrieval_p50_ms": round(samples[int(len(samples) * 0.50) - 1], 3),
        "retrieval_p95_ms": round(samples[int(len(samples) * 0.95) - 1], 3),
        "hits": len(result),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
