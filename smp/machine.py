"""This computer: GPU memory, which local vision model fits it, and where ExifTool and Ollama are.

Tools come from the installer's own copies in the tools folder first, then from PATH. Models are chosen from the GPU's
memory (on Apple Silicon: a share of the unified memory)."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from smp import config

IS_WINDOWS = os.name == "nt"


@dataclass(frozen=True)
class Profile:
    name: str
    min_gb: float          # GPU memory needed
    tags: tuple[str, ...]  # Ollama tags, best first; the first is the one downloaded
    approx_gb: float       # download size


# The model for each amount of GPU memory, biggest first.
PROFILES = (
    Profile("xl", 40, ("qwen3-vl:32b-instruct-q8_0", "qwen3-vl:32b-instruct", "qwen3-vl:32b"), 36),
    Profile("large", 22, ("qwen3-vl:30b-a3b-instruct-q4_K_M", "qwen3-vl:30b-a3b-instruct", "qwen3-vl:30b"), 19),
    Profile("medium", 14, ("qwen3-vl:8b-instruct-q8_0", "qwen3-vl:8b-instruct", "qwen3-vl:8b"), 10),
    Profile("small", 0, ("qwen3-vl:8b-instruct-q4_K_M", "qwen3-vl:8b-instruct", "qwen3-vl:8b", "qwen3-vl:4b"), 6),
)
MIN_USEFUL_GB = 8          # below this a local model is too slow to be worth it


@dataclass(frozen=True)
class Gpu:
    name: str
    memory_gb: float       # usable for a model
    kind: str              # "nvidia", "apple" or "none"


@lru_cache(maxsize=1)
def gpu() -> Gpu:
    smi = shutil.which("nvidia-smi") or (os.path.join(os.environ.get("SystemRoot", ""), "System32", "nvidia-smi.exe")
                                          if IS_WINDOWS else "")
    if smi and os.path.exists(smi):
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout
            best = max((ln.rsplit(",", 1) for ln in out.strip().splitlines() if "," in ln),
                       key=lambda p: float(p[1]), default=None)
            if best:
                return Gpu(best[0].strip(), round(float(best[1]) / 1024, 1), "nvidia")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        try:
            mem = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                     timeout=5).stdout.strip())
            # macOS lets the GPU use roughly two thirds of unified memory
            return Gpu("Apple Silicon", round(mem / 1024 ** 3 * 0.65, 1), "apple")
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return Gpu("", 0.0, "none")


def recommended(memory_gb: float | None = None) -> Profile:
    mem = gpu().memory_gb if memory_gb is None else memory_gb
    return next(p for p in PROFILES if mem >= p.min_gb)


def size_of(tag: str) -> float:
    """Approximate download size in GB of a model from the table (0 when unknown)."""
    return next((p.approx_gb for p in PROFILES if p.tags[0] == tag), 0.0)


def pick_model(installed: list[str], memory_gb: float | None = None) -> str:
    """The best model that fits: an installed one if any fits, else the recommended one to download."""
    mem = gpu().memory_gb if memory_gb is None else memory_gb
    names = set(installed) | {n.removesuffix(":latest") for n in installed}
    for p in PROFILES:
        if mem >= p.min_gb:
            hit = next((t for t in p.tags if t in names), None)
            if hit:
                return hit
    return recommended(mem).tags[0]


def installed_models(models_dir: str) -> list[str]:
    """Models in an Ollama models folder, read from its manifests (works while Ollama isn't running)."""
    root = Path(models_dir) / "manifests" / "registry.ollama.ai"
    if not root.is_dir():
        return []
    out = []
    for tag in root.glob("*/*/*"):
        if tag.is_file():
            ns, name = tag.parent.parent.name, tag.parent.name
            out.append(f"{name}:{tag.name}" if ns == "library" else f"{ns}/{name}:{tag.name}")
    return sorted(out)


def find_exiftool() -> str:
    tools = config.tools_dir()
    for cand in (tools / "exiftool" / ("exiftool.exe" if IS_WINDOWS else "exiftool"),
                 tools / "exiftool" / "Image-ExifTool" / "exiftool"):
        if cand.exists():
            return str(cand)
    return shutil.which("exiftool") or ""


def find_ollama() -> str:
    cand = config.tools_dir() / "ollama" / ("ollama.exe" if IS_WINDOWS else "ollama")
    if cand.exists():
        return str(cand)
    found = shutil.which("ollama")
    if found:
        return found
    if IS_WINDOWS:     # the Ollama desktop installer puts it here without always updating PATH
        cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if cand.exists():
            return str(cand)
    if platform.system() == "Darwin":
        cand = Path("/Applications/Ollama.app/Contents/Resources/ollama")
        if cand.exists():
            return str(cand)
    return ""


def version_of(exe: str, args: tuple[str, ...]) -> str:
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"\d+\.\d+(\.\d+)?", (r.stdout or "") + (r.stderr or ""))
    return m.group(0) if m else ""
