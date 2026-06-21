"""生成 Live2D 展示页使用的 LLM 控制文件。

脚本会调用 DeepSeek API，并把结构化控制结果写入
``main/live2d_stage/public/control/latest_control.json``。API key 只从
``DEEPSEEK_API_KEY`` 环境变量读取，绝不写入输出文件。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
DEFAULT_OUTPUT = PROJECT_ROOT / "main" / "live2d_stage" / "public" / "control" / "latest_control.json"
DEFAULT_MANIFEST = PROJECT_ROOT / "main" / "assets" / "live2d" / "Strawberry_Rabbit" / "manifest.json"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.integrations.llm_client import DeepSeekLlmClient, LlmClientError, LlmContext


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="调用 DeepSeek 生成 Live2D 控制计划。")
    parser.add_argument(
        "--prompt",
        default="请用温柔、活泼的中文女声向用户打招呼，并展示一个开心的 Live2D 表情。",
        help="发送给 LLM 的用户意图",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="Live2D manifest 路径")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="控制 JSON 输出路径")
    parser.add_argument("--model", default=None, help="DeepSeek 模型名，默认读取 DEEPSEEK_MODEL 或 deepseek-v4-flash")
    return parser.parse_args()


def load_manifest(path: Path) -> tuple[list[str], list[str]]:
    """读取允许的表情和动作名称。"""

    with path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    expressions = list((manifest.get("expressions") or {}).keys())
    motions = list((manifest.get("motions") or {}).keys())
    if not expressions:
        raise ValueError("manifest 中没有 expressions。")
    if not motions:
        raise ValueError("manifest 中没有 motions。")
    return expressions, motions


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    try:
        expressions, motions = load_manifest(args.manifest)
        client = DeepSeekLlmClient(model=args.model)
        plan = client.generate_live2d_control(
            LlmContext(
                user_prompt=args.prompt,
                expressions=expressions,
                motions=motions,
            )
        )
    except (OSError, ValueError, LlmClientError) as exc:
        print("LLM 控制计划生成失败：{0}".format(exc))
        return 1

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as handle:
            json.dump(plan.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except OSError as exc:
        print(f"控制文件写入失败 [{args.output}]：{exc}", file=sys.stderr)
        return 1

    print("=== LLM Live2D 控制计划 ===")
    print("输出文件：{0}".format(args.output))
    print("回复文本：{0}".format(plan.text))
    print("表情：{0}".format(plan.expression))
    print("动作：{0}".format(plan.motion))
    print("情绪：{0}".format(plan.emotion))
    return 0


if __name__ == "__main__":
    sys.exit(main())
