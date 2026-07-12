"""验证已部署的本地推理链路，不调用任何云端视觉模型。"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import requests


def request_headers(token: str) -> dict[str, str]:
    return {"X-Device-Token": token} if token else {}


def run(base_url: str, image_path: Path | None, token: str) -> None:
    base_url = base_url.rstrip("/")
    health = requests.get(f"{base_url}/vision-health", timeout=20)
    health.raise_for_status()
    health_payload = health.json()
    if health_payload.get("ok") is not True or health_payload.get("backend") != "elf2-local-yolo-pose-yunet-sface-ferplus":
        raise RuntimeError(f"板端视觉未就绪：{health_payload}")
    print(json.dumps({"vision_health": health_payload}, ensure_ascii=False, indent=2))

    if image_path is None:
        return
    if not image_path.is_file():
        raise FileNotFoundError(f"测试图片不存在：{image_path}")
    response = requests.post(
        f"{base_url}/vision",
        headers=request_headers(token),
        json={"image": base64.b64encode(image_path.read_bytes()).decode("ascii")},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("ok") is not True or payload.get("backend") != "elf2-local-yolo-pose-yunet-sface-ferplus":
        raise RuntimeError(f"视觉推理没有经过 ELF2 本地模型：{payload}")
    print(json.dumps({"vision_result": payload}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 ELF2 本地视觉部署")
    parser.add_argument("--base-url", default="https://anima.veyralux.org")
    parser.add_argument("--image", type=Path, help="用于真实推理的 JPEG/PNG")
    parser.add_argument("--token", default="", help="直连板端时使用；公网 Worker 会自动注入")
    args = parser.parse_args()
    run(args.base_url, args.image, args.token)


if __name__ == "__main__":
    main()
