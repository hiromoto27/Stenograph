"""ASR backends: OpenVINO whisper.cpp (preferred on Arc) + faster-whisper fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import os
import shutil
import subprocess
import time

from worker.hw_profile import HardwareProfile
from worker.models_catalog import ModelEntry, load_index, models_root


@dataclass
class Transcription:
    text: str
    confidence: float | None
    backend: str
    duration_sec: float | None = None


class AsrBackend(Protocol):
    name: str

    def transcribe(self, wav_path: Path, language: str = "ru") -> Transcription: ...


class StubBackend:
    name = "stub"

    def transcribe(self, wav_path: Path, language: str = "ru") -> Transcription:
        return Transcription(
            text=f"[stub ASR] {wav_path.name}",
            confidence=None,
            backend=self.name,
        )


class FasterWhisperBackend:
    """CPU/int8 or CUDA — downloads CT2 weights from HF on first use."""

    name = "faster-whisper"

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8") -> None:
        import os

        # Slow networks: default HF read timeout is too aggressive for first download.
        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")

        from faster_whisper import WhisperModel  # type: ignore

        try:
            self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"faster-whisper failed to load '{model_size}' on {device}/{compute_type}: {exc}. "
                "Retry with HF_HUB_DOWNLOAD_TIMEOUT=300, or pre-download via huggingface-cli, "
                "or use --backend stub / whisper.cpp ggml from our catalog "
                "(python -m worker.main --download-model whisper-base)."
            ) from exc
        self._model_size = model_size

    def transcribe(self, wav_path: Path, language: str = "ru") -> Transcription:
        t0 = time.time()
        segments, info = self._model.transcribe(str(wav_path), language=language, vad_filter=True)
        parts: list[str] = []
        probs: list[float] = []
        for seg in segments:
            parts.append(seg.text.strip())
            if seg.avg_logprob is not None:
                # map logprob roughly into 0..1 for UI only
                probs.append(max(0.0, min(1.0, 1.0 + float(seg.avg_logprob) / 5.0)))
        text = " ".join(p for p in parts if p).strip()
        conf = sum(probs) / len(probs) if probs else None
        return Transcription(
            text=text,
            confidence=conf,
            backend=f"{self.name}:{self._model_size}",
            duration_sec=time.time() - t0,
        )


class WhisperCppOpenVinoBackend:
    """
    Windows/Arc path: call whisper.cpp binary built with OpenVINO.

    Env:
      STENOGRAF_WHISPER_CPP — path to whisper-cli / main.exe
      STENOGRAF_WHISPER_MODEL — path to ggml-*.bin (optional; else catalog)
    """

    name = "whisper.cpp-openvino"

    def __init__(self, binary: Path, model: Path) -> None:
        self.binary = binary
        self.model = model

    def transcribe(self, wav_path: Path, language: str = "ru") -> Transcription:
        t0 = time.time()
        cmd = [
            str(self.binary),
            "-m",
            str(self.model),
            "-f",
            str(wav_path),
            "-l",
            language,
            "-nt",
        ]
        # OpenVINO build may accept -ngpu / OV device flags — keep minimal portable set.
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:500]
            raise RuntimeError(f"whisper.cpp failed ({proc.returncode}): {err}")
        text = (proc.stdout or "").strip()
        return Transcription(
            text=text,
            confidence=None,
            backend=self.name,
            duration_sec=time.time() - t0,
        )


def _pick_model_file(profile: HardwareProfile) -> Path | None:
    env_model = os.environ.get("STENOGRAF_WHISPER_MODEL")
    if env_model:
        p = Path(env_model)
        return p if p.exists() else None

    hint = profile.asr_model_hint.lower()
    preferred_ids = []
    if "tiny" in hint:
        preferred_ids = ["whisper-tiny", "whisper-base"]
    elif "small" in hint:
        preferred_ids = ["whisper-small", "whisper-base", "whisper-tiny"]
    elif "medium" in hint or "large" in hint:
        preferred_ids = ["whisper-small", "whisper-base"]
    else:
        preferred_ids = ["whisper-base", "whisper-small", "whisper-tiny"]

    by_id = {e.id: e for e in load_index()}
    root = models_root()
    for mid in preferred_ids:
        entry = by_id.get(mid)
        if not entry:
            continue
        path = root / entry.filename
        if path.exists():
            return path
    # any ggml in models dir
    if root.exists():
        found = sorted(root.glob("ggml-*.bin"))
        if found:
            return found[0]
    return None


def _find_whisper_cpp() -> Path | None:
    env = os.environ.get("STENOGRAF_WHISPER_CPP")
    if env and Path(env).exists():
        return Path(env)
    for name in ("whisper-cli", "whisper-cli.exe", "main", "main.exe"):
        which = shutil.which(name)
        if which:
            return Path(which)
    return None


def select_backend(profile: HardwareProfile) -> AsrBackend:
    """
    Preference:
      high/CUDA → faster-whisper CUDA
      mid + prefer_openvino + whisper.cpp binary/model → OpenVINO
      else faster-whisper CPU
      else stub
    """
    size = "base"
    if profile.name == "low":
        size = "tiny"
    elif profile.name == "high":
        size = "small"

    if getattr(profile, "prefer_cuda", False):
        try:
            return FasterWhisperBackend(model_size=size, device="cuda", compute_type="float16")
        except Exception:
            try:
                return FasterWhisperBackend(model_size=size, device="cuda", compute_type="int8_float16")
            except Exception:
                pass  # fall through to CPU / OpenVINO

    binary = _find_whisper_cpp()
    model = _pick_model_file(profile)
    if (
        binary
        and model
        and getattr(profile, "prefer_openvino", profile.name in ("mid", "high"))
        and not getattr(profile, "prefer_cuda", False)
    ):
        return WhisperCppOpenVinoBackend(binary, model)

    try:
        return FasterWhisperBackend(model_size=size, device="cpu", compute_type="int8")
    except Exception:
        return StubBackend()


def describe_backend(backend: AsrBackend) -> dict:
    info: dict = {"backend": getattr(backend, "name", type(backend).__name__)}
    if isinstance(backend, WhisperCppOpenVinoBackend):
        info["binary"] = str(backend.binary)
        info["model"] = str(backend.model)
    if isinstance(backend, FasterWhisperBackend):
        info["model_size"] = backend._model_size
    return info
