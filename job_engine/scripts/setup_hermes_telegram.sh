#!/usr/bin/env bash
# Wire Hermes Telegram for Watch Tower briefs. Token never goes into git.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
ENVF="$HOME/.hermes/.env"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Usage:"
  echo "  1) Talk to @BotFather → create bot → copy token"
  echo "  2) TELEGRAM_BOT_TOKEN=xxxx TELEGRAM_ALLOWED_USERS=your_id \\"
  echo "       $0"
  echo "  Optional: TELEGRAM_HOME_CHANNEL=chat_id for cron delivery"
  exit 1
fi

touch "$ENVF"
# upsert keys
python3 - <<'PY'
import os
from pathlib import Path
envf = Path.home()/'.hermes'/'.env'
text = envf.read_text(encoding='utf-8') if envf.exists() else ''
pairs = {
    'TELEGRAM_BOT_TOKEN': os.environ['TELEGRAM_BOT_TOKEN'],
}
if os.environ.get('TELEGRAM_ALLOWED_USERS'):
    pairs['TELEGRAM_ALLOWED_USERS'] = os.environ['TELEGRAM_ALLOWED_USERS']
if os.environ.get('TELEGRAM_HOME_CHANNEL'):
    pairs['TELEGRAM_HOME_CHANNEL'] = os.environ['TELEGRAM_HOME_CHANNEL']
lines = text.splitlines()
keys = set(pairs)
out = []
for ln in lines:
    key = ln.split('=',1)[0].lstrip('#').strip() if '=' in ln else ''
    if key in keys:
        continue
    out.append(ln)
for k,v in pairs.items():
    out.append(f'{k}={v}')
envf.write_text('\n'.join(out).rstrip()+'\n', encoding='utf-8')
print('Wrote Telegram keys to', envf)
PY

hermes gateway install || true
echo "Next: hermes gateway start"
echo "Then: hermes cron edit — set deliver to telegram (or telegram:CHAT_ID)"
echo "Test brief: python3 /home/user/Documents/job_engine/scripts/hermes_daily_brief.py"
