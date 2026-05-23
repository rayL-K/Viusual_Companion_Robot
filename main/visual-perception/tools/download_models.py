"""模型下载工具"""
import argparse, sys
from pathlib import Path
from urllib.request import urlretrieve

_HERE = Path(__file__).resolve().parent.parent
_WDIR = _HERE / "models" / "weights"

MODELS = [
    ("scrfd", "https://github.com/deepinsight/insightface/releases/download/v0.7/scrfd_2.5g_bnkps.onnx", "scrfd_2.5g_bnkps.onnx"),
    ("pfld", "https://github.com/Hsintao/pfld_106_face_landmarks/releases/download/v1.0/pfld-106.onnx", "pfld-106.onnx"),
    ("emotion", "https://github.com/serengil/deepface/raw/master/deepface/models/emotion_model/mini_xception.onnx", "mini-xception.onnx"),
    ("movenet", "https://storage.googleapis.com/tfhub-models/tensorflow/lite-model/movenet/singlepose/lightning/tflite/float16/4.tflite", "movenet_lightning.tflite"),
]

_done = set()


def _progress(b, bs, total):
    if total <= 0: return
    pct = min(100, b * bs * 100 // total)
    bar = "#" * (pct // 5) + "." * (20 - pct // 5)
    sys.stdout.write(f"\r[{bar}] {pct}%  {b * bs // 1024}KB / {total // 1024}KB")
    sys.stdout.flush()


def download(name, url, fn):
    target = _WDIR / fn
    if target.exists():
        print(f"  ✓ {fn} 已存在")
        return
    print(f"  ↓ {fn}...")
    _WDIR.mkdir(parents=True, exist_ok=True)
    urlretrieve(url, str(target), _progress)
    print(f"\n  ✓ {fn} ({target.stat().st_size // 1024}KB)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("names", nargs="*")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for name, url, fn in MODELS:
            print(f"  {name:12s} {url}")
        return

    targets = args.names if args.names else [m[0] for m in MODELS]
    for m in MODELS:
        if m[0] in targets:
            download(*m)


if __name__ == "__main__":
    main()
