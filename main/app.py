"""板端程序入口。

本文件只负责启动最外层应用。当前项目仍处于结构重建阶段，所以入口暂时
保持极简：先验证目录、配置和模块边界是否可正常导入，后续再把摄像头、
语音、对话和 Live2D 显示流程逐步接入这里。
"""

from __future__ import annotations

import sys
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parent / "src"
if str(SRC_ROOT) not in sys.path:
    # 现阶段尚未做安装包，入口脚本显式加入 src，保证本地和 Firefly 直接运行一致。
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.runtime.config import load_app_config
from visual_companion_robot.ui.live2d.avatar import load_live2d_avatar


def main() -> None:
    """运行板端主程序。

    后续完整流程会在这里创建运行时上下文，并按顺序启动设备采集、感知、
    对话决策、语音播报和 Live2D 表情反馈等模块。
    """

    config = load_app_config()
    print(f"板端应用配置已加载：{config.app_name}（{config.mode}）")

    if config.live2d_display.enabled:
        avatar = load_live2d_avatar(
            config.live2d_display.manifest_path,
            expected_name=config.live2d_display.model_name,
            expected_model3_path=config.live2d_display.model_path,
        )
        print(
            "Live2D 资源已加载："
            f"{avatar.name}，表情 {len(avatar.expressions)} 个，动作 {len(avatar.motions)} 个。"
        )


if __name__ == "__main__":
    main()

