"""Auto-detect hardware profile: low | mid | high."""

from __future__ import annotations

from dataclasses import dataclass
import platform


@dataclass(frozen=True)
class HardwareProfile:
    name: str  # low | mid | high
    reason: str
    asr_model_hint: str
    max_asr_workers: int


def detect_profile() -> HardwareProfile:
    """Best-effort profile. Refine with psutil/OpenVINO device query later."""
    ram_gb = _estimate_ram_gb()
    has_arcish_gpu = _guess_intel_gpu()

    if ram_gb is not None and ram_gb <= 8 and not has_arcish_gpu:
        return HardwareProfile(
            name="low",
            reason=f"RAM≈{ram_gb}GB, no Arc-class GPU detected",
            asr_model_hint="ggml-tiny / ggml-base (CPU)",
            max_asr_workers=1,
        )
    if has_arcish_gpu or (ram_gb is not None and ram_gb >= 12):
        return HardwareProfile(
            name="mid",
            reason=f"RAM≈{ram_gb}GB, Intel GPU likely — prefer whisper.cpp OpenVINO",
            asr_model_hint="ggml-base / ggml-small (OpenVINO first)",
            max_asr_workers=1,
        )
    return HardwareProfile(
        name="high",
        reason=f"RAM≈{ram_gb}GB / strong GPU assumed",
        asr_model_hint="ggml-medium / large-v3-turbo",
        max_asr_workers=2,
    )


def _estimate_ram_gb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return None


def _guess_intel_gpu() -> bool:
    # Stub: real probe via OpenVINO / DXGI later on Windows.
    sys = platform.system().lower()
    machine = platform.machine().lower()
    return sys == "windows" or "arc" in machine
