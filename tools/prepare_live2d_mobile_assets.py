"""从桌面级 Live2D 纹理生成移动端低显存资源。"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = PROJECT_ROOT / "main" / "assets" / "live2d" / "Strawberry_Rabbit"
SOURCE_TEXTURE_DIR = MODEL_ROOT / "textures_4096"
ASSET_REVISION = "r2"
MOBILE_TEXTURE_DIR_NAME = f"textures_1024_{ASSET_REVISION}"
MOBILE_TEXTURE_DIR = MODEL_ROOT / MOBILE_TEXTURE_DIR_NAME
SOURCE_MODEL_PATH = MODEL_ROOT / "Strawberry_Rabbit.model3.json"
MOBILE_MODEL_PATH = MODEL_ROOT / f"Strawberry_Rabbit.mobile-1024-{ASSET_REVISION}.model3.json"
MOBILE_TEXTURE_SIZE = (1024, 1024)


def generate_mobile_assets() -> None:
    MOBILE_TEXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(SOURCE_TEXTURE_DIR.glob("*.png")):
        target_path = MOBILE_TEXTURE_DIR / source_path.name
        with Image.open(source_path) as image:
            resized = image.resize(MOBILE_TEXTURE_SIZE, Image.Resampling.LANCZOS)
            resized.save(target_path, format="PNG", optimize=True)

    model = json.loads(SOURCE_MODEL_PATH.read_text(encoding="utf-8"))
    references = model.get("FileReferences")
    if not isinstance(references, dict) or not isinstance(references.get("Textures"), list):
        raise ValueError("Live2D model3.json 缺少 FileReferences.Textures。")
    references["Textures"] = [
        str(texture).replace("textures_4096/", f"{MOBILE_TEXTURE_DIR_NAME}/")
        for texture in references["Textures"]
    ]
    MOBILE_MODEL_PATH.write_text(
        json.dumps(model, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate_mobile_assets()
