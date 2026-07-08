"""Generate polished SVG diagrams for the competition technical report.

Each figure is saved as SVG and as a high-resolution PNG fallback for old Word/PDF renderers.
"""
from __future__ import annotations

from pathlib import Path
import html
import cairosvg

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "submission" / "figures"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FONT = "'Microsoft YaHei','SimHei','Noto Sans CJK SC',Arial,sans-serif"
BG = "#FFFFFF"
TEXT = "#172033"
MUTED = "#5B677A"
LINE = "#4B5568"
BLUE = "#2563EB"
BLUE_2 = "#DBEAFE"
TEAL = "#0F9F8F"
TEAL_2 = "#DDF8F3"
ORANGE = "#EA7A23"
ORANGE_2 = "#FFF0DF"
PURPLE = "#6D5BD0"
PURPLE_2 = "#ECE9FF"
GREEN = "#238B5E"
GREEN_2 = "#E4F6ED"
GRAY_2 = "#F5F7FA"
BORDER = "#CBD5E1"


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def svg_start(width: int, height: int) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<defs>',
        '<marker id="arrow" markerWidth="11" markerHeight="8" refX="9.5" refY="4" orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L10,4 L0,8 Z" fill="#4B5568"/></marker>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="130%">'
        '<feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#0F172A" flood-opacity="0.10"/></filter>',
        '<style>',
        f'text{{font-family:{FONT};fill:{TEXT};dominant-baseline:auto}}',
        '.title{font-size:24px;font-weight:700}.subtitle{font-size:14px;fill:#5B677A}',
        '.node-title{font-size:18px;font-weight:700}.node-text{font-size:13px;fill:#334155}',
        '.small{font-size:12px;fill:#64748B}.lane{font-size:14px;font-weight:700;fill:#475569}',
        '</style>',
        '</defs>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{BG}"/>',
    ]


def text_block(x: float, y: float, lines: list[str], size: int = 14, color: str = TEXT, weight: int | str = 400, anchor: str = "start", line_gap: int = 20, cls: str = "") -> str:
    cls_attr = f' class="{cls}"' if cls else ""
    parts = []
    for idx, line in enumerate(lines):
        parts.append(f'<text{cls_attr} x="{x}" y="{y + idx * line_gap}" text-anchor="{anchor}" font-size="{size}" font-weight="{weight}" fill="{color}">{esc(line)}</text>')
    return "".join(parts)


def pill(x: int, y: int, w: int, h: int, title: str, lines: list[str], fill: str, stroke: str, title_color: str = TEXT) -> str:
    cy = y + 30
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{fill}" stroke="{stroke}" stroke-width="1.6" filter="url(#shadow)"/>']
    out.append(text_block(x + w / 2, cy, [title], size=18, color=title_color, weight=700, anchor="middle"))
    out.append(text_block(x + w / 2, cy + 24, lines, size=13, color="#334155", weight=400, anchor="middle", line_gap=18))
    return "".join(out)


def line(x1: int, y1: int, x2: int, y2: int, arrow: bool = True, dash: bool = False, color: str = LINE, width: float = 2.2) -> str:
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    dash_attr = ' stroke-dasharray="7 5"' if dash else ""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" stroke-linecap="round"{marker}{dash_attr}/>'


def path(d: str, arrow: bool = True, dash: bool = False, color: str = LINE, width: float = 2.2) -> str:
    marker = ' marker-end="url(#arrow)"' if arrow else ""
    dash_attr = ' stroke-dasharray="7 5"' if dash else ""
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"{marker}{dash_attr}/>'


def save(name: str, width: int, height: int, body: list[str]) -> Path:
    svg = "".join(svg_start(width, height) + body + ["</svg>"])
    svg_path = OUTPUT_DIR / f"{name}.svg"
    png_path = OUTPUT_DIR / f"{name}.png"
    svg_path.write_text(svg, encoding="utf-8")
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(png_path), output_width=width * 3, output_height=height * 3)
    print(f"generated {svg_path} {png_path}")
    return png_path


def gen_fig_1_1() -> Path:
    w, h = 900, 470
    body: list[str] = []
    body.append(text_block(w / 2, 38, ["视觉-语音-对话-表达闭环"], size=24, weight=700, anchor="middle"))
    body.append(text_block(w / 2, 62, ["实时检测负责低等待感，异步语义补充负责上下文丰富度"], size=14, color=MUTED, anchor="middle"))
    cx, cy = 450, 250
    nodes = {
        "vision": (330, 90, 240, 86, "视觉感知", ["YOLO/Pose/人脸", "情绪与主动说话人"], BLUE_2, BLUE),
        "voice": (610, 207, 230, 86, "语音交互", ["SenseVoice ASR", "Matcha实时 + VoxCPM高质"], TEAL_2, TEAL),
        "dialog": (330, 330, 240, 86, "对话规划", ["视觉上下文 + 记忆", "DeepSeek Flash生成计划"], ORANGE_2, ORANGE),
        "live2d": (60, 207, 230, 86, "表达呈现", ["Live2D动作/表情", "音频驱动口型"], PURPLE_2, PURPLE),
    }
    for x, y, nw, nh, title, lines_, fill, stroke in nodes.values():
        body.append(pill(x, y, nw, nh, title, lines_, fill, stroke))
    body.append(f'<circle cx="{cx}" cy="{cy}" r="52" fill="{GRAY_2}" stroke="{BORDER}" stroke-width="1.5"/>')
    body.append(text_block(cx, cy - 6, ["低等待感"], size=17, weight=700, anchor="middle"))
    body.append(text_block(cx, cy + 20, ["交互闭环"], size=17, weight=700, anchor="middle"))
    body.append(path("M570 126 C675 130 740 160 756 207"))
    body.append(path("M760 293 C746 354 668 383 570 373"))
    body.append(path("M330 373 C230 385 148 354 140 293"))
    body.append(path("M140 207 C150 150 225 121 330 126"))
    body.append(text_block(660, 150, ["结构化视觉"], size=13, color=MUTED, anchor="middle"))
    body.append(text_block(682, 346, ["用户意图"], size=13, color=MUTED, anchor="middle"))
    body.append(text_block(220, 346, ["控制计划"], size=13, color=MUTED, anchor="middle"))
    body.append(text_block(218, 150, ["画面/语音"], size=13, color=MUTED, anchor="middle"))
    return save("fig_1_1", w, h, body)


def gen_fig_1_2() -> Path:
    w, h = 900, 330
    body: list[str] = []
    body.append(text_block(w / 2, 38, ["设计流程与迭代路径"], size=24, weight=700, anchor="middle"))
    steps = [
        ("场景定义", ["陪伴对话", "公网可达"], BLUE_2, BLUE),
        ("端侧环境", ["ELF2部署", "模型适配"], TEAL_2, TEAL),
        ("最小闭环", ["视觉/ASR", "TTS/Live2D"], ORANGE_2, ORANGE),
        ("跨端入口", ["Cloudflare", "PC/移动端"], PURPLE_2, PURPLE),
        ("稳定优化", ["VAD门控", "内存与恢复"], GREEN_2, GREEN),
        ("验收交付", ["一键启动", "强校验"], BLUE_2, BLUE),
    ]
    x0, y, bw, bh, gap = 38, 120, 120, 90, 28
    for i, (title, lines_, fill, stroke) in enumerate(steps):
        x = x0 + i * (bw + gap)
        body.append(pill(x, y, bw, bh, title, lines_, fill, stroke))
        body.append(text_block(x + bw/2, y + bh + 32, [f"0{i+1}"], size=17, color=stroke, weight=700, anchor="middle"))
        if i < len(steps) - 1:
            body.append(line(x + bw + 2, y + bh // 2, x + bw + gap - 4, y + bh // 2))
    body.append(text_block(w / 2, 284, ["按“先可用、再稳定、再优化体验”的顺序推进，避免一次性堆叠模型导致链路不可验收。"], size=14, color=MUTED, anchor="middle"))
    return save("fig_1_2", w, h, body)


def gen_fig_2_1() -> Path:
    w, h = 960, 660
    body: list[str] = []
    body.append(text_block(w / 2, 38, ["系统总体架构"], size=24, weight=700, anchor="middle"))
    body.append(text_block(w / 2, 62, ["Web负责交互呈现，ELF2负责本地推理、状态汇聚与服务编排"], size=14, color=MUTED, anchor="middle"))
    # layers
    body.append(pill(250, 92, 460, 76, "PC / 手机 Web / 小程序", ["Live2D渲染 · 摄像头/麦克风采集 · 音频播放"], BLUE_2, BLUE))
    body.append(line(470, 170, 470, 205)); body.append(text_block(395, 192, ["HTTPS/WSS"], size=13, color=MUTED, anchor="middle"))
    body.append(pill(250, 206, 460, 76, "Cloudflare Worker + Tunnel", ["静态资源 · 路由白名单 · 设备令牌注入 · QUIC出站隧道"], TEAL_2, TEAL))
    body.append(line(470, 284, 470, 320)); body.append(text_block(534, 306, ["QUIC Tunnel"], size=13, color=MUTED, anchor="middle"))
    body.append(pill(250, 322, 460, 78, "ELF2统一控制网关 :8765", ["鉴权 · 任务编排 · 背压控制 · 记忆读写 · 对话计划"], ORANGE_2, ORANGE))
    body.append(line(470, 402, 470, 448, arrow=False))
    body.append(line(130, 448, 830, 448, arrow=False))
    modules = [
        (50, 478, 190, 112, "实时视觉", ["YOLOv5s / Pose (NPU)", "YuNet/SFace/FER+", "Light-ASD"], BLUE_2, BLUE),
        (280, 478, 190, 112, "语义视觉", ["Qwen3-VL-2B W8A8", "6秒低频异步刷新", "帧指纹/冲突门控"], TEAL_2, TEAL),
        (510, 478, 190, 112, "语音链路", ["SenseVoice ASR", "Matcha-TTS实时", "VoxCPM按需"], ORANGE_2, ORANGE),
        (740, 478, 190, 112, "记忆与对话", ["SQLite长期记忆", "视觉上下文裁剪", "结构化控制计划"], PURPLE_2, PURPLE),
    ]
    for x, y, bw, bh, title, lines_, fill, stroke in modules:
        body.append(line(x + bw // 2, 448, x + bw // 2, y - 4))
        body.append(pill(x, y, bw, bh, title, lines_, fill, stroke))
    return save("fig_2_1", w, h, body)


def gen_fig_2_2() -> Path:
    w, h = 960, 570
    body: list[str] = []
    body.append(text_block(w / 2, 38, ["软件模块数据流与实时/异步分层"], size=24, weight=700, anchor="middle"))
    body.append(f'<rect x="30" y="78" width="900" height="155" rx="18" fill="#F8FAFC" stroke="{BORDER}" stroke-width="1.2"/>')
    body.append(text_block(52, 105, ["实时路径"], size=16, color=BLUE, weight=700))
    body.append(pill(70, 128, 145, 62, "浏览器采集", ["JPEG / PCM / 文本"], BLUE_2, BLUE))
    body.append(line(218, 159, 270, 159))
    body.append(pill(272, 128, 150, 62, "Worker路由", ["白名单 / 令牌"], TEAL_2, TEAL))
    body.append(line(425, 159, 478, 159))
    body.append(pill(480, 128, 160, 62, "控制网关", ["背压 / 编排"], ORANGE_2, ORANGE))
    body.append(line(642, 159, 694, 159))
    body.append(pill(696, 128, 175, 62, "实时响应", ["检测 / ASR / TTS"], PURPLE_2, PURPLE))

    body.append(f'<rect x="30" y="265" width="900" height="170" rx="18" fill="#FFFDF8" stroke="#F3D7B9" stroke-width="1.2"/>')
    body.append(text_block(52, 292, ["异步语义路径"], size=16, color=ORANGE, weight=700))
    body.append(pill(80, 320, 170, 66, "关键帧筛选", ["帧指纹 / 低频调度"], ORANGE_2, ORANGE))
    body.append(line(253, 353, 318, 353, dash=True))
    body.append(pill(320, 320, 190, 66, "Qwen3-VL语义", ["动作 / 背景 / 状态"], TEAL_2, TEAL))
    body.append(line(512, 353, 578, 353, dash=True))
    body.append(pill(580, 320, 170, 66, "语义缓存", ["不过期才进入上下文"], GREEN_2, GREEN))
    body.append(line(752, 353, 820, 245, dash=True))

    body.append(f'<rect x="692" y="238" width="190" height="58" rx="16" fill="{GRAY_2}" stroke="{BORDER}" stroke-width="1.2"/>')
    body.append(text_block(787, 264, ["对话计划合成"], size=17, color=TEXT, weight=700, anchor="middle"))
    body.append(text_block(787, 286, ["文本 + 表情 + 动作 + 音频"], size=12, color=MUTED, anchor="middle"))
    body.append(line(787, 296, 787, 452))
    body.append(pill(665, 454, 245, 64, "Live2D表现层", ["动作、表情、口型与气泡同步呈现"], BLUE_2, BLUE))
    body.append(text_block(w / 2, 548, ["实时路径不等待生成式视觉；异步语义仅在可信且新鲜时补充对话上下文。"], size=14, color=MUTED, anchor="middle"))
    return save("fig_2_2", w, h, body)


def main() -> None:
    gen_fig_1_1()
    gen_fig_1_2()
    gen_fig_2_1()
    gen_fig_2_2()


if __name__ == "__main__":
    main()
