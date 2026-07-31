"""ThinkPad heat governor — dynamic breaks so Ollama + scrape don't cook the host.

Reads CPU package temp, optional NVIDIA GPU temp, and load average.
Used by relevance filtering (between batches) and beat enqueue (skip when hot).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import subprocess
import time

from app import config

logger = logging.getLogger(__name__)


@dataclass
class HeatSnapshot:
    level: str  # cool | warm | hot | critical
    cpu_c: float | None
    gpu_c: float | None
    load1: float
    break_s: float
    detail: str


def _read_cpu_temp_c() -> float | None:
    """Prefer Intel package temp — acpitz on ThinkPads is often a noisy outlier."""
    by_type: dict[str, float] = {}
    for zone in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            typ = (zone / 'type').read_text().strip()
            temp = int((zone / 'temp').read_text().strip()) / 1000.0
        except Exception:
            continue
        if typ in ('x86_pkg_temp', 'TCPU', 'TCPU_PCI', 'acpitz'):
            prev = by_type.get(typ)
            by_type[typ] = temp if prev is None else max(prev, temp)
    for key in ('x86_pkg_temp', 'TCPU', 'TCPU_PCI', 'acpitz'):
        if key in by_type:
            return by_type[key]
    return None


def _read_gpu_temp_c() -> float | None:
    try:
        out = subprocess.check_output(
            [
                'nvidia-smi',
                '--query-gpu=temperature.gpu',
                '--format=csv,noheader,nounits',
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        ).strip()
        if out:
            return float(out.splitlines()[0])
    except Exception:
        return None
    return None


def _load1() -> float:
    try:
        return float(Path('/proc/loadavg').read_text().split()[0])
    except Exception:
        return 0.0


def snapshot() -> HeatSnapshot:
    cpu = _read_cpu_temp_c()
    gpu = _read_gpu_temp_c()
    load1 = _load1()
    # Effective heat = hottest signal we have
    peak = max([t for t in (cpu, gpu) if t is not None] + [0.0])

    cool_max = config.HEAT_COOL_MAX_C
    warm_max = config.HEAT_WARM_MAX_C
    hot_max = config.HEAT_HOT_MAX_C

    if peak >= hot_max or load1 >= config.HEAT_CRITICAL_LOAD:
        level, break_s = 'critical', config.HEAT_BREAK_CRITICAL_S
    elif peak >= warm_max or load1 >= config.HEAT_HOT_LOAD:
        level, break_s = 'hot', config.HEAT_BREAK_HOT_S
    elif peak >= cool_max or load1 >= config.HEAT_WARM_LOAD:
        level, break_s = 'warm', config.HEAT_BREAK_WARM_S
    else:
        level, break_s = 'cool', config.HEAT_BREAK_COOL_S

    detail = (
        f'cpu={cpu:.0f}C' if cpu is not None else 'cpu=?'
    ) + (
        f' gpu={gpu:.0f}C' if gpu is not None else ' gpu=?'
    ) + f' load={load1:.2f}'

    return HeatSnapshot(
        level=level, cpu_c=cpu, gpu_c=gpu, load1=load1,
        break_s=break_s, detail=detail,
    )


def wait_for_breath(run_id: int | None = None, *, why: str = 'batch') -> HeatSnapshot:
    """Sleep a dynamic break based on current heat. Returns the snapshot used."""
    from app.console import console_log

    snap = snapshot()
    if snap.break_s <= 0:
        return snap
    console_log(
        'ai',
        f'Heat break ({why}): {snap.level} — {snap.detail}; '
        f'resting {snap.break_s:.0f}s before next Ollama work…',
        run_id=run_id,
        level='warn' if snap.level in ('hot', 'critical') else 'info',
    )
    time.sleep(snap.break_s)
    return snap


def allow_ollama(run_id: int | None = None) -> bool:
    """False → caller should use keyword filter (critical heat / no GPU)."""
    from app.console import console_log

    snap = snapshot()
    if snap.gpu_c is None and config.HEAT_REQUIRE_GPU:
        console_log(
            'ai',
            f'NVIDIA unavailable ({snap.detail}) — keyword filter to protect host.',
            run_id=run_id, level='warn',
        )
        return False
    if snap.level == 'critical':
        console_log(
            'ai',
            f'Critical heat ({snap.detail}) — keyword filter this round.',
            run_id=run_id, level='warn',
        )
        return False
    return True


def allow_new_scrape() -> tuple[bool, HeatSnapshot]:
    """Beat uses this: skip dispatching a new scrape while the laptop is hot."""
    snap = snapshot()
    if snap.level in ('hot', 'critical'):
        return False, snap
    return True, snap
