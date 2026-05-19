"""Live2D 嘴型同步模块。

该模块负责把“测试音序列”转换成嘴型参数和临时声音参数。嘴型数据不再
硬编码在函数里，而是从 ``main/config/mouth_shapes.json`` 读取，这样可以
直接调整每个音对应的张嘴、横向展开、圆唇和临时发声参数。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


MOUTH_PARAMETER_KEYS = ("open", "width", "round", "jaw", "smile", "tension")
AUDIO_MODES = ("silence", "tone", "noise", "mixed")


@dataclass
class MouthSyncFrame:
    """某一时刻的嘴型同步值。"""

    timestamp_sec: float
    mouth_open: float


@dataclass
class TemporaryAudioCue:
    """可视化测试用的临时合成声音参数。

    这不是最终 TTS，只是为了让每个测试音播放时能听到对应的声响，便于
    同时观察“声音变化”和“嘴型变化”是否匹配。
    """

    mode: str
    frequency_hz: float
    second_frequency_hz: float
    noise: float
    gain: float
    syllable: str

    def as_dict(self) -> Dict[str, Any]:
        """转换成前端可直接使用的字段名。"""

        return {
            "mode": self.mode,
            "frequencyHz": self.frequency_hz,
            "secondFrequencyHz": self.second_frequency_hz,
            "noise": self.noise,
            "gain": self.gain,
            "syllable": self.syllable,
        }


@dataclass
class VisemeShape:
    """一个嘴型参数预设。

    参数范围统一为 0 到 1，方便后续映射到 Live2D 的 ParamMouthOpenY、
    ParamMouthForm 或自定义口型参数。HTML 报告会再做一层边界限制，避免
    视觉调试时嘴巴被拉到脸外。
    """

    name: str
    label: str
    mouth_open: float
    mouth_width: float
    mouth_round: float
    jaw_drop: float
    smile: float
    tension: float

    def as_dict(self) -> Dict[str, float]:
        """转换成前端可直接使用的字段名。"""

        return {
            "mouthOpen": self.mouth_open,
            "mouthWidth": self.mouth_width,
            "mouthRound": self.mouth_round,
            "jawDrop": self.jaw_drop,
            "smile": self.smile,
            "tension": self.tension,
        }


@dataclass
class VisemeSample:
    """可视化测试中的一个音素或音节片段。"""

    sound_key: str
    token: str
    group: str
    viseme: str
    duration_ms: int
    shape: VisemeShape
    audio: TemporaryAudioCue
    note: str = ""


VISEME_SHAPES: Dict[str, VisemeShape] = {
    "rest": VisemeShape("rest", "闭合/停顿", 0.02, 0.24, 0.0, 0.02, 0.04, 0.20),
    "closed": VisemeShape("closed", "双唇闭合", 0.04, 0.22, 0.0, 0.02, 0.02, 0.72),
    "open": VisemeShape("open", "大开口", 0.74, 0.52, 0.10, 0.72, 0.05, 0.35),
    "wide": VisemeShape("wide", "横向展开", 0.34, 0.76, 0.04, 0.22, 0.58, 0.45),
    "round": VisemeShape("round", "圆唇", 0.42, 0.34, 0.88, 0.30, 0.00, 0.40),
    "teeth": VisemeShape("teeth", "齿音/擦音", 0.22, 0.70, 0.04, 0.12, 0.20, 0.86),
    "alveolar": VisemeShape("alveolar", "舌尖音", 0.30, 0.58, 0.05, 0.18, 0.12, 0.62),
    "velar": VisemeShape("velar", "舌根音", 0.36, 0.48, 0.16, 0.28, 0.03, 0.55),
    "nasal": VisemeShape("nasal", "鼻音", 0.16, 0.38, 0.02, 0.08, 0.04, 0.50),
    "rhotic": VisemeShape("rhotic", "卷舌/儿化", 0.32, 0.44, 0.42, 0.20, 0.02, 0.58),
}


MANDARIN_TEST_TEXT = (
    "声母覆盖：ba pa ma fa, da ta na la, ge ke he, ji qi xi, "
    "zhi chi shi ri, zi ci si, ya wa。"
    "韵母覆盖：a o e i u ü, ai ei ui, ao ou iu, ie üe er, "
    "an en in un ün, ang eng ing ong。"
)

ENGLISH_TEST_TEXT = (
    "English coverage: AA AE AH AO EH ER EY IH IY OW OY UH UW, "
    "P B M F V T D K G N NG S Z SH ZH CH JH L R W Y H TH DH."
)

VISUAL_MOUTH_TEST_TEXT = MANDARIN_TEST_TEXT + " " + ENGLISH_TEST_TEXT


def default_mouth_config_path() -> Path:
    """定位默认嘴型配置文件。"""

    for parent in Path(__file__).resolve().parents:
        candidate = parent / "config" / "mouth_shapes.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到 main/config/mouth_shapes.json")


def load_mouth_shape_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """读取每个测试音的嘴型和临时声音配置。"""

    path = config_path or default_mouth_config_path()
    with path.open("r", encoding="utf-8") as config_file:
        data = json.load(config_file)
    if not isinstance(data, dict):
        raise ValueError("嘴型配置文件根节点必须是 JSON 对象。")
    return data


def validate_mouth_shape_config(config_path: Optional[Path] = None) -> List[str]:
    """校验配置是否覆盖所有序列音，并且参数都在安全范围内。"""

    errors: List[str] = []
    try:
        config = load_mouth_shape_config(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]

    sounds = config.get("sounds")
    sequence = config.get("sequence")
    if not isinstance(sounds, dict):
        errors.append("sounds 必须是对象。")
        sounds = {}
    if not isinstance(sequence, list):
        errors.append("sequence 必须是数组。")
        sequence = []

    for index, sound_key in enumerate(sequence):
        if sound_key not in sounds:
            errors.append("sequence[{0}] 引用了不存在的音：{1}".format(index, sound_key))

    for sound_key, sound in sounds.items():
        if not isinstance(sound, dict):
            errors.append("{0} 必须是对象。".format(sound_key))
            continue
        viseme = sound.get("viseme")
        if viseme not in VISEME_SHAPES:
            errors.append("{0} 使用了未知嘴型：{1}".format(sound_key, viseme))
        mouth = sound.get("mouth")
        if not isinstance(mouth, dict):
            errors.append("{0}.mouth 必须是对象。".format(sound_key))
            mouth = {}
        for key in MOUTH_PARAMETER_KEYS:
            value = mouth.get(key)
            if not isinstance(value, (int, float)):
                errors.append("{0}.mouth.{1} 必须是数字。".format(sound_key, key))
            elif not 0.0 <= float(value) <= 1.0:
                errors.append("{0}.mouth.{1} 必须在 0 到 1 之间。".format(sound_key, key))
        audio = sound.get("audio")
        if not isinstance(audio, dict):
            errors.append("{0}.audio 必须是对象。".format(sound_key))
            audio = {}
        if audio.get("mode") not in AUDIO_MODES:
            errors.append("{0}.audio.mode 必须是 {1} 之一。".format(sound_key, ", ".join(AUDIO_MODES)))
        for key in ("noise", "gain"):
            value = audio.get(key)
            if not isinstance(value, (int, float)):
                errors.append("{0}.audio.{1} 必须是数字。".format(sound_key, key))
            elif not 0.0 <= float(value) <= 1.0:
                errors.append("{0}.audio.{1} 必须在 0 到 1 之间。".format(sound_key, key))
        for key in ("frequencyHz", "secondFrequencyHz"):
            value = audio.get(key)
            if not isinstance(value, (int, float)):
                errors.append("{0}.audio.{1} 必须是数字。".format(sound_key, key))
            elif float(value) < 0.0:
                errors.append("{0}.audio.{1} 不能小于 0。".format(sound_key, key))
    return errors


def build_visual_mouth_test_sequence(
    duration_ms: Optional[int] = None,
    config_path: Optional[Path] = None,
) -> List[VisemeSample]:
    """生成覆盖元辅音的固定嘴型测试序列。"""

    config = load_mouth_shape_config(config_path)
    sequence = config.get("sequence", [])
    sounds = config.get("sounds", {})
    if not isinstance(sequence, list) or not isinstance(sounds, dict):
        raise ValueError("嘴型配置必须包含 sequence 数组和 sounds 对象。")

    default_duration_ms = int(duration_ms or config.get("defaultDurationMs", 180))
    samples: List[VisemeSample] = []
    for sound_key in sequence:
        if sound_key not in sounds:
            raise ValueError("sequence 引用了不存在的音：{0}".format(sound_key))
        sound = sounds[sound_key]
        if not isinstance(sound, dict):
            raise ValueError("{0} 必须是对象。".format(sound_key))
        samples.append(_sample_from_sound(sound_key, sound, default_duration_ms))
    return samples


def build_mouth_sync_frames(samples: Iterable[VisemeSample]) -> List[MouthSyncFrame]:
    """把嘴型样本转换成按时间推进的嘴巴开合帧。"""

    frames: List[MouthSyncFrame] = []
    current_ms = 0
    for sample in samples:
        frames.append(MouthSyncFrame(timestamp_sec=current_ms / 1000.0, mouth_open=sample.shape.mouth_open))
        current_ms += sample.duration_ms
    return frames


def summarize_viseme_coverage(samples: Iterable[VisemeSample]) -> Dict[str, List[str]]:
    """统计每类嘴型覆盖到的音素。"""

    coverage: Dict[str, List[str]] = {}
    for sample in samples:
        coverage.setdefault(sample.viseme, []).append(sample.token)
    return coverage


def _sample_from_sound(sound_key: str, sound: Dict[str, Any], duration_ms: int) -> VisemeSample:
    """把配置里的一个音转换成测试样本。"""

    viseme = str(sound.get("viseme", ""))
    if viseme not in VISEME_SHAPES:
        raise ValueError("{0} 使用了未知嘴型：{1}".format(sound_key, viseme))

    return VisemeSample(
        sound_key=sound_key,
        token=str(sound.get("token", sound_key)),
        group=str(sound.get("group", "未分组")),
        viseme=viseme,
        duration_ms=duration_ms,
        shape=_shape_from_sound(viseme, sound),
        audio=_audio_from_sound(sound_key, sound),
        note=str(sound.get("note", "")),
    )


def _shape_from_sound(viseme: str, sound: Dict[str, Any]) -> VisemeShape:
    """合并嘴型预设和单音配置。"""

    preset = VISEME_SHAPES[viseme]
    mouth = sound.get("mouth", {})
    if not isinstance(mouth, dict):
        mouth = {}
    return VisemeShape(
        name=viseme,
        label=str(sound.get("label", preset.label)),
        mouth_open=_read_unit(mouth, "open", preset.mouth_open),
        mouth_width=_read_unit(mouth, "width", preset.mouth_width),
        mouth_round=_read_unit(mouth, "round", preset.mouth_round),
        jaw_drop=_read_unit(mouth, "jaw", preset.jaw_drop),
        smile=_read_unit(mouth, "smile", preset.smile),
        tension=_read_unit(mouth, "tension", preset.tension),
    )


def _audio_from_sound(sound_key: str, sound: Dict[str, Any]) -> TemporaryAudioCue:
    """读取单音的临时声音配置。"""

    audio = sound.get("audio", {})
    if not isinstance(audio, dict):
        audio = {}
    mode = str(audio.get("mode", "tone"))
    if mode not in AUDIO_MODES:
        raise ValueError("{0} 使用了未知音频模式：{1}".format(sound_key, mode))
    return TemporaryAudioCue(
        mode=mode,
        frequency_hz=_read_float(audio, "frequencyHz", 220.0, minimum=0.0),
        second_frequency_hz=_read_float(audio, "secondFrequencyHz", 0.0, minimum=0.0),
        noise=_read_unit(audio, "noise", 0.0),
        gain=_read_unit(audio, "gain", 0.08),
        syllable=str(audio.get("syllable", sound.get("token", sound_key))),
    )


def _read_unit(mapping: Dict[str, Any], key: str, default: float) -> float:
    """读取并限制 0 到 1 范围内的小数。"""

    return max(0.0, min(1.0, _read_float(mapping, key, default)))


def _read_float(mapping: Dict[str, Any], key: str, default: float, minimum: Optional[float] = None) -> float:
    """从字典读取浮点数。"""

    value = mapping.get(key, default)
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = float(default)
    if minimum is not None:
        result = max(minimum, result)
    return result
