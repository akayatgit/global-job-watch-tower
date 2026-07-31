"""Friendly schedule picker <-> cron conversion.

The DB and Celery Beat keep using cron strings (croniter, UTC), but the
admin UI shows and accepts human choices like "Every 5 minutes" or
"Weekly on Monday at 09:00" in the machine's local time.
"""

from datetime import datetime, timedelta, timezone

MINUTE_FREQS = {'m2': 2, 'm5': 5, 'm10': 10, 'm15': 15, 'm30': 30}
HOUR_FREQS = {'h1': 1, 'h2': 2, 'h3': 3, 'h6': 6, 'h12': 12}

FREQ_OPTIONS = [
    # Default recommendation for past-24h LinkedIn captures at scale
    ('daily', 'Every day (pick a time) — recommended'),
    ('h12', 'Every 12 hours'),
    ('h6', 'Every 6 hours'),
    ('h3', 'Every 3 hours'),
    ('h2', 'Every 2 hours'),
    ('h1', 'Every hour'),
    ('m30', 'Every 30 minutes'),
    ('m15', 'Every 15 minutes'),
    ('m10', 'Every 10 minutes'),
    ('m5', 'Every 5 minutes'),
    ('m2', 'Every 2 minutes'),
    ('weekly', 'Once a week (pick day + time)'),
]

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _local_tz_name() -> str:
    return datetime.now().astimezone().tzname() or 'local'


def staggered_daily_cron(index: int, *, start_hour: int = 5,
                         interval_minutes: int = 14) -> str:
    """UTC cron for once-daily run, staggered by index across the day.

    Spreads searches so a single worker can finish human-paced scrapes
    without stacking 100 roles at the same minute. Times are computed in
    local timezone then converted to UTC cron (same as build_cron daily).
    """
    total_minutes = (start_hour * 60) + (index * interval_minutes)
    # Wrap within 24h so a large catalogue still gets one slot each day
    total_minutes %= (24 * 60)
    hour, minute = divmod(total_minutes, 60)
    return build_cron('daily', f'{hour:02d}:{minute:02d}')


def build_cron(freq: str, time_str: str = '', weekday: str = '') -> str:
    """Build a UTC cron string from friendly inputs (times are local)."""
    if freq in MINUTE_FREQS:
        return f'*/{MINUTE_FREQS[freq]} * * * *'
    if freq in HOUR_FREQS:
        n = HOUR_FREQS[freq]
        return '0 * * * *' if n == 1 else f'0 */{n} * * *'

    hour, minute = 9, 0
    if time_str:
        try:
            hour, minute = (int(x) for x in time_str.split(':')[:2])
        except ValueError:
            pass

    if freq == 'daily':
        local = datetime.now(_local_tz()).replace(hour=hour, minute=minute, second=0, microsecond=0)
        utc = local.astimezone(timezone.utc)
        return f'{utc.minute} {utc.hour} * * *'

    if freq == 'weekly':
        try:
            target_dow = WEEKDAYS.index(weekday)
        except ValueError:
            target_dow = 0
        now = datetime.now(_local_tz())
        local = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        local += timedelta(days=(target_dow - local.weekday()) % 7)
        utc = local.astimezone(timezone.utc)
        cron_dow = (utc.weekday() + 1) % 7  # cron: 0=Sunday
        return f'{utc.minute} {utc.hour} * * {cron_dow}'

    # unknown -> hourly
    return '0 * * * *'


def cron_to_human(cron: str) -> str:
    """Describe the cron strings we generate; falls back to the raw string."""
    try:
        minute, hour, dom, month, dow = cron.split()
    except ValueError:
        return cron

    tzname = _local_tz_name()

    if hour == '*' and dom == '*' and dow == '*':
        if minute == '*':
            return 'Every minute'
        if minute.startswith('*/'):
            return f'Every {minute[2:]} minutes'
        if minute == '0':
            return 'Every hour'

    if dom == '*' and dow == '*' and minute.isdigit():
        if hour.startswith('*/'):
            return f'Every {hour[2:]} hours'
        if hour.isdigit():
            local = _utc_hm_to_local(int(hour), int(minute))
            return f'Every day at {local} ({tzname})'

    if dom == '*' and dow.isdigit() and minute.isdigit() and hour.isdigit():
        utc_now = datetime.now(timezone.utc)
        # find the next UTC datetime matching this cron day/time, then localize
        days_ahead = (int(dow) - (utc_now.weekday() + 1) % 7) % 7
        utc_dt = utc_now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0) + timedelta(days=days_ahead)
        local_dt = utc_dt.astimezone(_local_tz())
        return f'Weekly on {WEEKDAYS[local_dt.weekday()]} at {local_dt.strftime("%H:%M")} ({tzname})'

    return cron


def _utc_hm_to_local(hour: int, minute: int) -> str:
    utc_dt = datetime.now(timezone.utc).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return utc_dt.astimezone(_local_tz()).strftime('%H:%M')
