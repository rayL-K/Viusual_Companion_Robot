"""VoxCPM 本地推理模块 — 懒加载 + 进程内缓存。
"""

from __future__ import annotations

import gc
import importlib.util
import inspect
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


DEFAULT_LOCAL_MODEL_PATH = Path("main/models/voxcpm/VoxCPM2")
REQUIRED_PACKAGES = ("voxcpm", "soundfile", "numpy")
_MODEL_CACHE: Dict[Tuple[Any, ...], Any] = {}


class VoxCpmLocalError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoxCpmLocalConfig:
    model_path: Path
    device: str = "auto"
    zipenhancer_model_path: Optional[str] = None
    enable_denoiser: bool = False
    optimize: bool = False
    cfg_value: float = 2.0
    inference_timesteps: int = 10
    normalize: bool = True
    denoise: bool = False
    control_instruction: str = "年轻女性，温柔甜美，语气自然"

    @classmethod
    def from_mapping(cls, mapping: Dict[str, Any], project_root: Path) -> "VoxCpmLocalConfig":
        raw_model_path = os.environ.get("VOXCPM_MODEL_PATH") or mapping.get("model_path") or str(DEFAULT_LOCAL_MODEL_PATH)
        model_path = Path(str(raw_model_path))
        if not model_path.is_absolute():
            model_path = project_root / model_path

        zipenhancer_model_path = os.environ.get("VOXCPM_ZIPENHANCER_MODEL_PATH")
        if zipenhancer_model_path is None:
            zipenhancer_model_path = str(mapping.get("zipenhancer_model_path") or "").strip() or None

        return cls(
            model_path=model_path.resolve(),
            device=str(os.environ.get("VOXCPM_DEVICE") or mapping.get("device") or "auto"),
            zipenhancer_model_path=zipenhancer_model_path,
            enable_denoiser=bool(mapping.get("enable_denoiser", False)),
            optimize=bool(mapping.get("optimize", False)),
            cfg_value=float(mapping.get("cfg_value", 2.0)),
            inference_timesteps=int(mapping.get("inference_timesteps", 10)),
            normalize=bool(mapping.get("do_normalize", True)),
            denoise=bool(mapping.get("denoise", False)),
            control_instruction=str(mapping.get("control_instruction") or "年轻女性，温柔甜美，语气自然"),
        )


class VoxCpmLocalSynthesizer:
    def __init__(self, config: VoxCpmLocalConfig) -> None:
        self.config = config

    @staticmethod
    def environment_status(config: VoxCpmLocalConfig) -> Dict[str, Any]:
        missing_packages = [name for name in REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]
        missing_model = not config.model_path.exists()
        ok = not missing_packages and not missing_model
        messages = []
        if missing_packages:
            messages.append("缺少 Python 包：" + ", ".join(missing_packages))
        if missing_model:
            messages.append(f"缺少 VoxCPM2 模型目录：{config.model_path}")
        if ok:
            messages.append("项目内 VoxCPM 本地推理环境可用。")
        return {"ok": ok, "backend": "voxcpm_project_local", "model_path": str(config.model_path), "device": config.device, "message": "；".join(messages)}

    def synthesize(self, text: str, rate: float, reference_audio_path: str = "", prompt_text: str = "") -> Tuple[bytes, str]:
        status = self.environment_status(self.config)
        if not status["ok"]:
            raise VoxCpmLocalError(status["message"])

        model = self._get_model(self.config)
        kwargs = self.build_generation_kwargs(text=text, rate=rate, reference_audio_path=reference_audio_path, prompt_text=prompt_text)
        try:
            wav = model.generate(**kwargs)
            sample_rate = int(model.tts_model.sample_rate)
            return encode_wav_bytes(wav, sample_rate), "audio/wav"
        except Exception as exc:
            raise VoxCpmLocalError(f"VoxCPM 本地推理失败：{exc}") from exc

    def prepare(self) -> Dict[str, Any]:
        status = self.environment_status(self.config)
        if not status["ok"]:
            return status
        try:
            self._get_model(self.config)
        except Exception as exc:
            raise VoxCpmLocalError(f"VoxCPM 本地模型启动失败：{exc}") from exc
        status["loaded"] = True
        status["cached_models"] = cached_model_count()
        return status

    @staticmethod
    def _resolve_reference_path(reference_audio_path: str, prompt_text: str) -> tuple[Optional[str], Optional[str], bool]:
        ref_path = str(reference_audio_path or "").strip() or None
        clean_prompt = str(prompt_text or "").strip() or None
        return ref_path, clean_prompt, bool(ref_path and clean_prompt)

    def build_generation_kwargs(self, text: str, rate: float, reference_audio_path: str = "", prompt_text: str = "") -> Dict[str, Any]:
        clean_text = str(text or "").strip()
        if not clean_text:
            raise VoxCpmLocalError("待合成文本不能为空。")

        reference_path, clean_prompt_text, use_prompt_mode = self._resolve_reference_path(reference_audio_path, prompt_text)
        control = "" if use_prompt_mode else build_control_instruction(self.config.control_instruction, rate)

        kwargs: Dict[str, Any] = {
            "text": build_final_text(clean_text, control),
            "cfg_value": self.config.cfg_value,
            "inference_timesteps": self.config.inference_timesteps,
            "normalize": self.config.normalize,
            "denoise": self.config.denoise and bool(reference_path),
        }
        if reference_path:
            kwargs["reference_wav_path"] = reference_path
        if use_prompt_mode:
            kwargs["prompt_wav_path"] = reference_path
            kwargs["prompt_text"] = clean_prompt_text
        return kwargs

    @staticmethod
    def _get_model(config: VoxCpmLocalConfig) -> Any:
        cache_key = cache_key_for_config(config)
        if cache_key in _MODEL_CACHE:
            return _MODEL_CACHE[cache_key]

        try:
            from voxcpm import VoxCPM
        except ImportError:
            raise VoxCpmLocalError("voxcpm 包未安装或当前平台不支持")

        kwargs: Dict[str, Any] = {
            "voxcpm_model_path": str(config.model_path),
            "zipenhancer_model_path": config.zipenhancer_model_path,
            "enable_denoiser": config.enable_denoiser,
            "optimize": config.optimize,
        }
        if "device" in inspect.signature(VoxCPM).parameters:
            kwargs["device"] = config.device
        model = VoxCPM(**kwargs)
        _MODEL_CACHE[cache_key] = model
        return model


def cache_key_for_config(config: VoxCpmLocalConfig) -> Tuple[Any, ...]:
    return (str(config.model_path), config.device, config.zipenhancer_model_path, config.enable_denoiser, config.optimize)


def cached_model_count() -> int:
    return len(_MODEL_CACHE)


def release_cached_models(config: Optional[VoxCpmLocalConfig] = None) -> int:
    if config is None:
        released_count = len(_MODEL_CACHE)
        _MODEL_CACHE.clear()
    else:
        cache_key = cache_key_for_config(config)
        released_count = 1 if cache_key in _MODEL_CACHE else 0
        _MODEL_CACHE.pop(cache_key, None)

    if released_count:
        gc.collect()
        try:
            import torch
            if hasattr(torch, "cuda") and torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    return released_count


def build_control_instruction(control_instruction: str, rate: float) -> str:
    control = str(control_instruction or "").strip()
    if rate >= 1.08 and "语速" not in control:
        return f"{control}，语速稍快" if control else "语速稍快"
    if rate <= 0.92 and "语速" not in control:
        return f"{control}，语速稍慢" if control else "语速稍慢"
    return control


def build_final_text(text: str, control_instruction: str) -> str:
    control = str(control_instruction or "").strip()
    return f"({control}){text}" if control else text


def encode_wav_bytes(wav: Any, sample_rate: int) -> bytes:
    import numpy as np
    import soundfile as sf
    audio = np.asarray(wav, dtype=np.float32).reshape(-1)
    buffer = BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def encode_wav_file(wav: Any, sample_rate: int, file_path: str) -> str:
    data = encode_wav_bytes(wav, sample_rate)
    with open(file_path, "wb") as f:
        f.write(data)
    return file_path


class VoxCpmTTS:
    def __init__(self, project_root: Optional[Path] = None, **config_overrides) -> None:
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._config = self._build_config(config_overrides)
        self._synthesizer = VoxCpmLocalSynthesizer(self._config)

    def generate_audio(self, text: str, rate: float = 1.0, **kwargs) -> str:
        import tempfile
        file_path = str(Path(tempfile.gettempdir()) / f"voxcpm_{id(self)}.wav")
        wav, sample_rate = self._synthesizer.synthesize(text=text, rate=rate, **kwargs)
        return encode_wav_file(wav, sample_rate, file_path)

    def _build_config(self, overrides: dict) -> "VoxCpmLocalConfig":
        model_path = str(os.environ.get("VOXCPM_MODEL_PATH") or overrides.get("model_path") or str(DEFAULT_LOCAL_MODEL_PATH))
        if not Path(model_path).is_absolute():
            model_path = str(self._project_root / model_path)
        return VoxCpmLocalConfig(
            model_path=Path(model_path).resolve(),
            device=str(os.environ.get("VOXCPM_DEVICE") or overrides.get("device") or "auto"),
            control_instruction=str(overrides.get("control_instruction") or "年轻女性，温柔自然，语气友好"),
            cfg_value=float(overrides.get("cfg_value", 2.0)),
            inference_timesteps=int(overrides.get("inference_timesteps", 10)),
            normalize=bool(overrides.get("do_normalize", True)),
            denoise=bool(overrides.get("denoise", False)),
        )
