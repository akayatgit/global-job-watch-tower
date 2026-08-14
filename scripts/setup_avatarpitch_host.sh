#!/usr/bin/env bash
# One-time ThinkPad setup for the AvatarPitch integration (contract
# documents/avatarpitch-integration-plan.md, §5.2) — Ashok runs this once.
#
# What it does (idempotent, safe to re-run):
#   1. Creates /srv/avatarpitch/{uploads,data} owned by the current user.
#   2. Installs a systemd --user timer: 48h garbage collection of
#      /srv/avatarpitch/uploads (Ashok's ruling — AvatarPitch runs on
#      Vercel now, so the tower owns retention; everything under uploads
#      is re-renderable, nothing is precious).
#   3. Installs a systemd --user timer: nightly pg_dump of the tower db
#      into ~/backups/pg (keeps the newest 7 dumps).
#
# What it does NOT do: set PARTNER_API_TOKEN. Generate one yourself, e.g.
#   openssl rand -hex 32
# then put the SAME value in job_engine/.env (PARTNER_API_TOKEN=...) and in
# AvatarPitch's env. Tokens never enter git.
set -euo pipefail

AVATAR_ROOT="/srv/avatarpitch"
UNIT_DIR="${HOME}/.config/systemd/user"
BACKUP_DIR="${HOME}/backups/pg"
PG_URL="${TOWER_PG_URL:-postgresql://jobengine:jobengine@127.0.0.1:5433/jobengine}"

echo "==> Directories"
sudo mkdir -p "${AVATAR_ROOT}/uploads" "${AVATAR_ROOT}/data"
sudo chown -R "$(id -un):$(id -gn)" "${AVATAR_ROOT}"
mkdir -p "${UNIT_DIR}" "${BACKUP_DIR}"

echo "==> GC units (48h = 2880 min — Ashok's retention ruling)"
cat > "${UNIT_DIR}/avatarpitch-gc.service" <<EOF
[Unit]
Description=AvatarPitch uploads 48h GC (tower owns retention)

[Service]
Type=oneshot
ExecStart=/usr/bin/find ${AVATAR_ROOT}/uploads -mindepth 1 -type f -mmin +2880 -delete
ExecStartPost=/usr/bin/find ${AVATAR_ROOT}/uploads -mindepth 1 -type d -empty -delete
EOF

cat > "${UNIT_DIR}/avatarpitch-gc.timer" <<EOF
[Unit]
Description=Hourly AvatarPitch 48h GC

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "==> Nightly pg_dump units (keeps newest 7 dumps in ${BACKUP_DIR})"
cat > "${UNIT_DIR}/tower-pgdump.service" <<EOF
[Unit]
Description=Nightly pg_dump of the Watch Tower database

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'pg_dump "${PG_URL}" -Fc -f "${BACKUP_DIR}/jobengine-\$(date +%%Y%%m%%d).dump" && ls -1t "${BACKUP_DIR}"/jobengine-*.dump | tail -n +8 | xargs -r rm -f'
EOF

cat > "${UNIT_DIR}/tower-pgdump.timer" <<EOF
[Unit]
Description=Nightly Watch Tower pg_dump (03:30 local — scrape lane is quiet)

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo "==> Enabling timers"
systemctl --user daemon-reload
systemctl --user enable --now avatarpitch-gc.timer tower-pgdump.timer

echo
echo "Done. Verify with:  systemctl --user list-timers | grep -E 'avatarpitch|pgdump'"
echo "Remember: set PARTNER_API_TOKEN in job_engine/.env AND AvatarPitch's env."
