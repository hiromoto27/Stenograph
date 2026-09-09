from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from importlib.resources import files

import psutil


@dataclass
class Hardware:
    os: str
    cpu: str
    threads: int
    ram_gb: float
    available_gb: float
    disk_free_gb: float
    gpu: str
    vram_gb: float
    cuda_ready: bool


def detect(root) -> Hardware:
    gpu, vram = "Не определена / встроенная", 0.0
    try:
        output = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=4,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        if output.strip():
            # STT explicitly uses device_index=0, so recommendations describe that same GPU.
            name, memory = output.splitlines()[0].rsplit(",", 1)
            gpu, vram = name.strip(), float(memory.strip()) / 1024
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    cuda = False
    try:
        import ctranslate2
        cuda = ctranslate2.get_cuda_device_count() > 0
    except (ImportError, RuntimeError):
        pass
    mem = psutil.virtual_memory()
    return Hardware(platform.platform(), platform.processor() or platform.machine(), os.cpu_count() or 1,
                    round(mem.total / 1024**3, 1), round(mem.available / 1024**3, 1),
                    round(shutil.disk_usage(root).free / 1024**3, 1), gpu, round(vram, 1), cuda)


def catalogue():
    return json.loads(files("stenograph").joinpath("resources/catalogue.json").read_text(encoding="utf-8"))


def compatibility(item, hw):
    if hw.ram_gb < item["ram_gb"] or hw.disk_free_gb < item["disk_gb"]:
        return "Недостаточно RAM / места"
    if hw.available_gb < item["working_gb"]:
        return "Мало свободной RAM: закройте программы"
    if item.get("vram_gb", 0) and hw.vram_gb >= item["vram_gb"]:
        return "По памяти подходит; проверьте драйвер / скорость"
    return "По RAM подходит; CPU, скорость требует замера"


def recommend(hw):
    strong = hw.ram_gb >= 16 and hw.available_gb >= 6
    return {
        "stt": "small" if strong else "base",
        "llm": "qwen3:4b" if strong else "qwen3:1.7b",
        "device": "cpu", "compute_type": "int8",
        "cpu_threads": max(1, min(8, hw.threads // 2)),
        "chunk_seconds": 10,
        "note": "Оценка предварительная. Начните с CPU/int8. CUDA включайте после проверки библиотек и пробной записи. "
                "Для двух источников сумма времени распознавания должна укладываться в длительность записи.",
    }
