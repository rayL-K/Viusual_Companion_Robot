"""调用 Hugging Face VoxCPM-Demo 生成一段测试音频。

本脚本复用项目里的 TTS 后端配置，不依赖 gradio_client。
原因是当前本地统一 Python 环境仍是 3.8，而最新版 gradio_client 要求 Python 3.10+。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from live2d_control_server import PROJECT_ROOT, synthesize_with_tts_backend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试 Hugging Face VoxCPM-Demo TTS 后端。")
    parser.add_argument("--text", default="你好，我是草莓兔兔，现在正在测试 VoxCPM 语音。")
    parser.add_argument("--rate", type=float, default=1.08)
    parser.add_argument("--voice", default="voxcpm_hf_space_test")
    parser.add_argument("--reference", default="", help="参考音频 ID，留空时使用 tts_models.json 的 active_reference。")
    parser.add_argument("--prompt-text", default=None, help="参考音频对应文本，留空时使用配置中的默认文本。")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "main" / "reports" / "tts" / "voxcpm_hf_space_test.mp3"),
        help="输出音频路径，默认写入 main/reports/tts/，该目录不进入 Git。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    audio, content_type = synthesize_with_tts_backend(args.text, args.rate, args.voice, args.reference, args.prompt_text)
    output_path.write_bytes(audio)
    print(f"content_type={content_type}")
    print(f"bytes={len(audio)}")
    print(f"output={output_path}")


if __name__ == "__main__":
    main()
