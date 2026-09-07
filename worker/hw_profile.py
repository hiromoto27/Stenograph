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
    """Best-effort profile for Windows desktops (NVIDIA) and Arc laptops."""
    ram_gb = _estimate_ram_gb()
    nvidia = _detect_nvidia()
    intel_gpu = _detect_intel_gpu()

    # Discrete NVIDIA wins over Intel iGPU (common on gaming desktops).
    if nvidia.get("available"):
        name = nvidia.get("name") or "NVIDIA"
        vram = nvidia.get("vram_mb")
        reason = f"RAM≈{ram_gb}GB, {name}"
        if vram:
            reason += f", VRAM≈{vram}MB"
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

    # High RAM without nvidia-smi: still treat as high CPU, not OpenVINO-mid.
    if ram_gb is not None and ram_gb >= 24:
        return HardwareProfile(
            name="high",
            reason=f"RAM≈{ram_gb}GB, no nvidia-smi — faster-whisper CPU/CUDA if torch sees GPU",
            asr_model_hint="faster-whisper small/base",
            max_asr_workers=1,
            prefer_cuda=True,  # try CUDA; backend falls back to CPU
            prefer_openvino=False,
        )

    if intel_gpu:
        return HardwareProfile(
            name="mid",
            reason=f"RAM≈{ram_gb}GB, Intel GPU — whisper.cpp OpenVINO or faster-whisper CPU",
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


def _detect_intel_gpu() -> bool:
    """True only with positive evidence — never soft-default True."""
    if platform.system().lower() != "windows":
        return False
    try:
        out = subprocess.check_output(
            ["wmic", "path", "win32_VideoController", "get", "Name"],
            text=True,
            timeout=5,
            stderr=subprocess.DEVNULL,
        ).lower()
        has_intel = "intel" in out or "arc" in out
        has_nvidia = "nvidia" in out
        # If both, caller already preferred NVIDIA via nvidia-smi; here Intel-only.
        return has_intel and not has_nvidia
    except Exception:
        return False


def _detect_nvidia() -> dict:
    """Return {available, name, vram_mb} via nvidia-smi when present."""
    candidates = []
    which = shutil.which("nvidia-smi")
    if which:
        candidates.append(which)
    # Common Windows install paths when PATH is incomplete in venv shells.
    candidates.extend(
        [
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ]
    )
    seen: set[str] = set()
    for smi in candidates:
        if not smi or smi in seen:
            continue
        seen.add(smi)
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
                continue
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
            continue
    return {"available": False}
