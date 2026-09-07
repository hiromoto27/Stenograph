"""Auto-detect hardware profile: low | mid | high."""

from __future__ import annotations

from dataclasses import dataclass
import platform
import shutil
import subprocess


@dataclass(frozen=True)
class HardwareProfile:
    name: str  # low | mid | high
    reason: str
    asr_model_hint: str
    max_asr_workers: int
    prefer_cuda: bool = False
    prefer_openvino: bool = False


def detect_profile() -> HardwareProfile:
    """Best-effort profile for Windows laptops (Arc) and desktops (NVIDIA)."""
    ram_gb = _estimate_ram_gb()
    nvidia = _detect_nvidia()
    intel_gpu = _guess_intel_gpu()

    if nvidia.get("available") and (ram_gb is None or ram_gb >= 16):
        name = nvidia.get("name") or "NVIDIA"
        vram = nvidia.get("vram_mb")
        reason = f"RAM≈{ram_gb}GB, {name}"
        if vram:
            reason += f", VRAM≈{vram}MB"
        # 8GB+ VRAM or 24GB+ system RAM → high; else mid with CUDA
        high = (vram is not None and vram >= 8000) or (ram_gb is not None and ram_gb >= 24)
        if high:
            return HardwareProfile(
                name="high",
                reason=reason,
                asr_model_hint="faster-whisper small/base (CUDA)",
                max_asr_workers=1,
                prefer_cuda=True,
                prefer_openvino=False,
            )
        return HardwareProfile(
            name="mid",
            reason=reason,
            asr_model_hint="faster-whisper base (CUDA)",
            max_asr_workers=1,
            prefer_cuda=True,
            prefer_openvino=False,
        )

    if intel_gpu or (ram_gb is not None and ram_gb >= 12):
        return HardwareProfile(
            name="mid",
            reason=f"RAM≈{ram_gb}GB, Intel GPU likely — whisper.cpp OpenVINO or faster-whisper CPU",
            asr_model_hint="ggml-base / ggml-small (OpenVINO first)",
            max_asr_workers=1,
            prefer_cuda=False,
            prefer_openvino=True,
        )

    if ram_gb is not None and ram_gb <= 8:
        return HardwareProfile(
            name="low",
            reason=f"RAM≈{ram_gb}GB, no discrete GPU detected",
            asr_model_hint="ggml-tiny / faster-whisper tiny (CPU)",
            max_asr_workers=1,
        )

    return HardwareProfile(
        name="mid",
        reason=f"RAM≈{ram_gb}GB / unknown GPU",
        asr_model_hint="faster-whisper base (CPU)",
        max_asr_workers=1,
    )


def _estimate_ram_gb() -> float | None:
    try:
        import psutil  # type: ignore

        return round(psutil.virtual_memory().total / (1024**3), 1)
    except Exception:
        return None


def _guess_intel_gpu() -> bool:
    sys = platform.system().lower()
    # Lightweight heuristic; Arc laptops often Windows + Intel.
    if sys != "windows":
        return False
    try:
        out = subprocess.check_output(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        )
        return "intel" in out.lower() or "arc" in out.lower()
    except Exception:
        return True  # soft default for Windows when WMIC unavailable


def _detect_nvidia() -> dict:
    """Return {available, name, vram_mb} via nvidia-smi when present."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return {"available": False}
    try:
        out = subprocess.check_output(
            [
                smi,
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not out:
            return {"available": False}
        line = out.splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        name = parts[0] if parts else "NVIDIA"
        vram_mb = None
        if len(parts) > 1:
            try:
                vram_mb = int(float(parts[1]))
            except ValueError:
                vram_mb = None
        return {"available": True, "name": name, "vram_mb": vram_mb}
    except Exception:
        return {"available": False}
