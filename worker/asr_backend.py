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


def cuda_runtime_available() -> bool:
    """True only if a cuBLAS DLL actually loads (driver != toolkit)."""
    import os
    if os.environ.get("STENOGRAF_FORCE_CPU", "").strip() in {"1", "true", "yes"}:
        return False
    if os.environ.get("STENOGRAF_FORCE_CUDA", "").strip() in {"1", "true", "yes"}:
        return True
    try:
        import ctypes
        from ctypes import wintypes  # noqa: F401
    except Exception:
        return False
    for name in ("cublas64_12.dll", "cublas64_11.dll", "cublas64_10.dll"):
        try:
            ctypes.WinDLL(name)
            return True
        except OSError:
            continue
    return False




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

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        *,
        allow_cpu_fallback: bool = True,
    ) -> None:
        import os

        os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "300")
        os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "60")

        from faster_whisper import WhisperModel  # type: ignore

        self._model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.fallback_note: str | None = None

        attempts: list[tuple[str, str]] = [(device, compute_type)]
        if allow_cpu_fallback and device != "cpu":
            attempts.append(("cpu", "int8"))

        last_exc: Exception | None = None
        for dev, ctype in attempts:
            try:
                self._model = WhisperModel(model_size, device=dev, compute_type=ctype)
                self.device = dev
                self.compute_type = ctype
                if (dev, ctype) != (device, compute_type):
                    self.fallback_note = (
                        f"requested {device}/{compute_type} failed ({last_exc}); using {dev}/{ctype}"
                    )
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = str(exc).lower()
                # Missing CUDA runtime libs (cublas64_12.dll etc.) — try CPU.
                if allow_cpu_fallback and device != "cpu" and (
                    "cublas" in msg or "cuda" in msg or "dll" in msg or "cannot be loaded" in msg
                ):
                    continue
                if (dev, ctype) == attempts[-1]:
                    raise RuntimeError(
                        f"faster-whisper failed to load '{model_size}' on {device}/{compute_type}: {exc}. "
                        "Install CUDA toolkit 12.x (cublas64_12.dll) for GPU, or use CPU "
                        "(--backend faster-whisper will auto-fallback), or whisper.cpp ggml."
                    ) from exc
        else:
            raise RuntimeError(
                f"faster-whisper failed to load '{model_size}': {last_exc}"
            )

    def transcribe(self, wav_path: Path, language: str = "ru") -> Transcription:
        t0 = time.time()
        try:
            segments, info = self._model.transcribe(str(wav_path), language=language, vad_filter=True)
        except Exception as exc:  # noqa: BLE001
            if self.device == "cpu":
                raise
            # Any CUDA-side failure (cublas DLL missing often surfaces here, not at load).
            from faster_whisper import WhisperModel  # type: ignore

            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
            self.fallback_note = f"CUDA infer failed ({exc}); switched to cpu/int8"
            self.device = "cpu"
            self.compute_type = "int8"
            segments, info = self._model.transcribe(str(wav_path), language=language, vad_filter=True)
        parts: list[str] = []
        probs: list[float] = []
        for seg in segments:
            parts.append(seg.text.strip())
            if seg.avg_logprob is not None:
                probs.append(max(0.0, min(1.0, 1.0 + float(seg.avg_logprob) / 5.0)))
        text = " ".join(p for p in parts if p).strip()
        conf = sum(probs) / len(probs) if probs else None
        backend = f"{self.name}:{self._model_size}:{self.device}"
        return Transcription(
            text=text,
            confidence=conf,
            backend=backend,
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

    if getattr(profile, "prefer_cuda", False) and cuda_runtime_available():
        try:
            return FasterWhisperBackend(
                model_size=size,
                device="cuda",
                compute_type="float16",
                allow_cpu_fallback=True,
            )
        except Exception:
            try:
                return FasterWhisperBackend(
                    model_size=size,
                    device="cuda",
                    compute_type="int8_float16",
                    allow_cpu_fallback=True,
                )
            except Exception:
                pass  # fall through to CPU / OpenVINO
    elif getattr(profile, "prefer_cuda", False) and not cuda_runtime_available():
        # Driver present but no cublas DLL — skip CUDA entirely.
        pass

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
        info["device"] = backend.device
        info["compute_type"] = backend.compute_type
        if backend.fallback_note:
            info["warning"] = backend.fallback_note
    return info
