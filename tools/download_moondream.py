"""从 hf-mirror 下载 Moondream 2 模型文件"""
import os, requests

os.makedirs("main/models/moondream2", exist_ok=True)

files = [
    "model.safetensors",
    "config.json",
    "tokenizer_config.json",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.model",
    "tokenizer.json",
]
base = "https://hf-mirror.com/vikhyatk/moondream2/resolve/main"

for f in files:
    dest = f"main/models/moondream2/{f}"
    if os.path.exists(dest):
        size_mb = os.path.getsize(dest) / 1024 / 1024
        print(f"  SKIP {f} ({size_mb:.1f} MB)")
        continue

    url = f"{base}/{f}"
    print(f"  DOWNLOAD {f} ...")
    r = requests.get(url, stream=True, timeout=600)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))

    with open(dest, "wb") as out:
        downloaded = 0
        for chunk in r.iter_content(chunk_size=8192):
            out.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r    {pct}% ({downloaded//1024//1024}MB/{total//1024//1024}MB)", end="")

    size_mb = os.path.getsize(dest) / 1024 / 1024
    print(f"\n  DONE {f} ({size_mb:.1f} MB)")

print("All done")
