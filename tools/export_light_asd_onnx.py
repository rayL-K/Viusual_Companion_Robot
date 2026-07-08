"""把 Light-ASD 官方 PyTorch 权重导出为 ELF2 可运行的 ONNX。

先克隆 https://github.com/Junhua-Liao/Light-ASD，再把仓库目录传给 --source。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="导出 Light-ASD ONNX")
    parser.add_argument("--source", type=Path, required=True, help="Light-ASD 官方仓库目录")
    parser.add_argument("--weights", type=Path, help="默认使用 weight/pretrain_AVA_CVPR.model")
    parser.add_argument("--output", type=Path, required=True, help="输出 .onnx 路径")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    weights = (args.weights or source / "weight" / "pretrain_AVA_CVPR.model").resolve()
    if not (source / "model" / "Model.py").is_file() or not weights.is_file():
        raise SystemExit("Light-ASD 源码或官方权重不存在")

    try:
        import torch
        from torch import nn
    except ImportError as exc:
        raise SystemExit("导出环境需要 torch 和 onnx") from exc

    sys.path.insert(0, str(source))
    from model.Model import ASD_Model  # type: ignore[import-not-found]  # noqa: PLC0415

    class DeployModel(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = ASD_Model()
            self.classifier = nn.Linear(128, 2)
            # 上游在四维音频张量上使用 MaxPool3d；等价 MaxPool2d 可生成合法 ONNX。
            self.model.audioEncoder.pool1 = nn.MaxPool2d(
                kernel_size=(1, 3), stride=(1, 2), padding=(0, 1)
            )
            self.model.audioEncoder.pool2 = nn.MaxPool2d(
                kernel_size=(1, 3), stride=(1, 2), padding=(0, 1)
            )

        def forward(self, audio_mfcc, face_frames):  # type: ignore[no-untyped-def]
            audio = self.model.forward_audio_frontend(audio_mfcc)
            video = self.model.forward_visual_frontend(face_frames)
            fused = self.model.forward_audio_visual_backend(audio, video)
            return torch.softmax(self.classifier(fused), dim=-1)[:, 1]

    state = torch.load(weights, map_location="cpu", weights_only=True)
    deploy_model = DeployModel().eval()
    deploy_model.model.load_state_dict(
        {key.removeprefix("model."): value for key, value in state.items() if key.startswith("model.")}
    )
    deploy_model.classifier.load_state_dict(
        {key.removeprefix("lossAV.FC."): value for key, value in state.items() if key.startswith("lossAV.FC.")}
    )

    audio = torch.zeros((1, 200, 13), dtype=torch.float32)
    video = torch.zeros((1, 50, 112, 112), dtype=torch.float32)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        deploy_model,
        (audio, video),
        args.output,
        input_names=["audio_mfcc", "face_frames"],
        output_names=["speaking_probability"],
        opset_version=17,
        dynamic_axes={
            "audio_mfcc": {1: "audio_frames"},
            "face_frames": {1: "video_frames"},
            "speaking_probability": {0: "video_frames"},
        },
        dynamo=False,
    )
    print(f"已导出：{args.output} ({args.output.stat().st_size / 1024 / 1024:.2f} MiB)")


if __name__ == "__main__":
    main()
