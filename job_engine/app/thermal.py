"""ThinkPad heat governor — dynamic breaks so Ollama + scrape don't cook the host.

Reads CPU package temp, optional NVIDIA GPU temp, and load average.
Used by relevance filtering (between batches) and beat enqueue (skip when hot).

Ideal path: longer Warm/Hot rests + cool-before-Plan-B retries so we stay on
Ollama quality filtering and the orange Plan B banner stops flapping.
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
    peak_c: float = 0.0


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
    margin = max(0.0, config.HEAT_PREEMPT_MARGIN_C)

    if peak >= hot_max or load1 >= config.HEAT_CRITICAL_LOAD:
        level, break_s = 'critical', config.HEAT_BREAK_CRITICAL_S
    elif peak >= warm_max or load1 >= config.HEAT_HOT_LOAD:
        level, break_s = 'hot', config.HEAT_BREAK_HOT_S
        # Near critical: rest harder while Plan A is still allowed
        if peak >= hot_max - margin:
            break_s = max(break_s, config.HEAT_BREAK_CRITICAL_S * 0.85)
    elif peak >= cool_max or load1 >= config.HEAT_WARM_LOAD:
        level, break_s = 'warm', config.HEAT_BREAK_WARM_S
        if peak >= warm_max - margin:
            break_s = max(break_s, config.HEAT_BREAK_HOT_S * 0.6)
    else:
        level, break_s = 'cool', config.HEAT_BREAK_COOL_S

    detail = (
        f'cpu={cpu:.0f}C' if cpu is not None else 'cpu=?'
    ) + (
        f' gpu={gpu:.0f}C' if gpu is not None else ' gpu=?'
    ) + f' load={load1:.2f}'

    return HeatSnapshot(
        level=level, cpu_c=cpu, gpu_c=gpu, load1=load1,
        break_s=break_s, detail=detail, peak_c=peak,
    )


def wait_for_breath(
    run_id: int | None = None,
    *,
    why: str = 'batch',
    settle: bool = True,
) -> HeatSnapshot:
    """Sleep a dynamic break based on current heat.

    When settle=True, take a second rest if still hot/critical after the first
    so the next Ollama batch starts cooler — fewer Plan B trips.
    """
    from app.console import console_log

    snap = snapshot()
    if snap.break_s <= 0:
        return snap

    rounds = 1
    if settle and snap.level == 'hot':
        rounds = 2
    elif settle and snap.level == 'critical':
        rounds = 2  # full Plan B avoidance uses wait_for_ollama_ready

    for i in range(rounds):
        snap = snapshot()
        if i > 0 and snap.level in ('cool', 'warm'):
            break
        if snap.break_s <= 0:
            break
        label = f'{why}' + (f' · settle {i + 1}' if i else '')
        console_log(
            'ai',
            f'Heat break ({label}): {snap.level} — {snap.detail}; '
            f'resting {snap.break_s:.0f}s before next Ollama work…',
            run_id=run_id,
            level='warn' if snap.level in ('hot', 'critical') else 'info',
        )
        time.sleep(snap.break_s)
        if snap.level == 'cool':
            break

    return snapshot()


def ollama_path_open() -> bool:
    """Quiet check — True when Plan A (Ollama) is allowed right now."""
    snap = snapshot()
    if snap.gpu_c is None and config.HEAT_REQUIRE_GPU:
        return False
    if snap.level == 'critical':
        return False
    return True


def wait_for_ollama_ready(run_id: int | None = None) -> bool:
    """Cool down and retry before surrendering to Plan B keyword filter.

    Returns True if Plan A (Ollama) is open. False only after cooldown retries
    fail (or GPU missing). Prefer waiting over corrupting relevance data.
    """
    from app.console import console_log

    if ollama_path_open():
        return True

    snap = snapshot()
    if snap.gpu_c is None and config.HEAT_REQUIRE_GPU:
        console_log(
            'ai',
            f'NVIDIA unavailable ({snap.detail}) — Plan B keyword filter '
            f'(emergency only; prefer fixing GPU).',
            run_id=run_id, level='warn',
        )
        return False

    retries = max(1, config.HEAT_COOLDOWN_RETRIES)
    for attempt in range(1, retries + 1):
        rest = max(config.HEAT_BREAK_CRITICAL_S, 90.0)
        console_log(
            'ai',
            f'Critical heat ({snap.detail}) — cool-down {attempt}/{retries} '
            f'({rest:.0f}s) to keep Ollama (avoid Plan B)…',
            run_id=run_id, level='warn',
        )
        time.sleep(rest)
        if ollama_path_open():
            console_log(
                'ai',
                f'Heat recovered after cool-down {attempt}/{retries} — resuming Ollama.',
                run_id=run_id,
            )
            return True
        snap = snapshot()

    console_log(
        'ai',
        f'Still critical after {retries} cool-down(s) ({snap.detail}) — '
        f'Plan B keyword filter this round only.',
        run_id=run_id, level='warn',
    )
    return False


def allow_ollama(run_id: int | None = None, *, cool: bool = False) -> bool:
    """True when Plan A is open. With cool=True, rest/retry before saying no."""
    from app.console import console_log

    if cool:
        return wait_for_ollama_ready(run_id)
    if ollama_path_open():
        return True
    snap = snapshot()
    if snap.gpu_c is None and config.HEAT_REQUIRE_GPU:
        console_log(
            'ai',
            f'NVIDIA unavailable ({snap.detail}) — need cool/retry or Plan B.',
            run_id=run_id, level='warn',
        )
    else:
        console_log(
            'ai',
            f'Critical heat ({snap.detail}) — need cool/retry before Ollama.',
            run_id=run_id, level='warn',
        )
    return False


def allow_new_scrape() -> tuple[bool, HeatSnapshot]:
    """Beat uses this: skip dispatching a new scrape while the laptop is hot."""
    snap = snapshot()
    if snap.level in ('hot', 'critical'):
        return False, snap
    return True, snap
