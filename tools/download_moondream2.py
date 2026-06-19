"""补下 Moondream 2 完整模型文件"""
import requests, os

token = os.getenv("HF_TOKEN", "")
api = "https://hf-mirror.com/api/models/vikhyatk/moondream2"
headers = {"Authorization": f"Bearer {token}"} if token else {}

# 获取文件列表
files = requests.get(api, headers=headers, timeout=10).json()["siblings"]
names = [s["rfilename"] for s in files if not s["rfilename"].startswith(".git")]

dest = "main/models/moondream2"
base = "https://hf-mirror.com/vikhyatk/moondream2/resolve/main"

for name in names:
    path = f"{dest}/{name}"
    if os.path.exists(path):
        sz = os.path.getsize(path)
        print(f"  SKIP {name} ({sz}B)")
        continue

    url = f"{base}/{name}"
    print(f"  GET {name} ...", end=" ", flush=True)
    r = requests.get(url, timeout=30, allow_redirects=True)
    if r.status_code == 200:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            out.write(r.content)
        print(f"OK ({len(r.content)}B)")
    else:
        print(f"FAIL ({r.status_code})")

print("Done")
