# Remote access — Cloudflare Tunnel + Access (Option B)

**Status:** Chosen 2026-08-03 (Ashok YES — Option B). Brain stays on ThinkPad.  
**Goal:** Open VIGIL from any browser / any machine over HTTPS, with email gate (Ashok only).  
**Not:** Vercel deploy, Supabase mirror, or public port-forward.

## Architecture

```
Any browser  →  https://tower.<your-domain>
                     │
              Cloudflare edge (TLS + Access OTP)
                     │
              Cloudflare Tunnel (cloudflared on ThinkPad)
                     │
              http://127.0.0.1:8001  (uvicorn — loopback only)
                     │
         Postgres / Redis / Celery / Chrome / Ollama  (never exposed)
```

| Piece | Where | Notes |
|---|---|---|
| VIGIL + API | ThinkPad `:8001` | Still binds `127.0.0.1` — good |
| Tunnel daemon | `watch-tower-tunnel` systemd --user | `cloudflared tunnel run` |
| Credentials | `~/.cloudflared/` | Never commit; cert + tunnel JSON |
| Access allowlist | Cloudflare Zero Trust | Email = Ashok only |
| Stamp | `job_engine/.data/cloudflare_tunnel.json` | Hostname / tunnel id (no secrets) |

## Prerequisites (Ashok)

1. **Cloudflare account** with a **domain** whose DNS is on Cloudflare (free plan is enough).
2. **Zero Trust** enabled (free seat is enough for one user).
3. **Access email** — the address that receives the one-time login code (e.g. Gmail).

If you do not own a domain yet: buy any cheap domain, add it to Cloudflare (nameservers), wait for active zone, then continue.

## One-shot setup (ThinkPad)

```bash
cd /home/user/Documents
HOSTNAME=tower.YOURDOMAIN.com ACCESS_EMAIL=you@example.com \
  bash scripts/cloudflare_tunnel_setup.sh
```

The script:

1. Opens browser for `cloudflared tunnel login` (authorize the zone).
2. Creates named tunnel `watch-tower` (or reuses it).
3. Writes `~/.cloudflared/config.yml` → ingress to `http://127.0.0.1:8001`.
4. Routes DNS CNAME `HOSTNAME` → tunnel.
5. Enables `systemctl --user` unit `watch-tower-tunnel`.
6. Prints Access dashboard steps.

Then in **Cloudflare Zero Trust → Access → Applications**:

1. Add application → **Self-hosted**
2. Domain: same `HOSTNAME`
3. Policy: **Allow** → Include → **Emails** → your `ACCESS_EMAIL`
4. Save

Open `https://HOSTNAME` → email OTP → VIGIL.

## Day-2 ops

| Action | Command |
|---|---|
| Status | `systemctl --user status watch-tower-tunnel` |
| Logs | `journalctl --user -u watch-tower-tunnel -f` |
| Restart tunnel | `systemctl --user restart watch-tower-tunnel` |
| Tunnel info | `cloudflared tunnel info watch-tower` |

Tunnel does **not** disturb scrapes. Deploy (`deploy_local.sh`) restarts API/worker/beat only — tunnel keeps running.

After reboot: user linger already enabled for watch-tower units; ensure `watch-tower-tunnel` is `enabled` (setup script does this).

## Security rules

- **Never** bind Postgres (`5433`) or Redis to the public internet.
- **Never** put tunnel credentials in git.
- Access policy = Ashok email only (tighten later with Google Workspace if needed).
- Do not share the hostname publicly; Access is the lock, obscurity is not.
- If laptop is off / asleep / offline, the HTTPS URL will fail — tower must stay up (lid policy already ignores suspend).

## What we deliberately do not do

| Idea | Why not (sole admin) |
|---|---|
| Vercel host the app | No Celery / Chrome / Ollama / local Postgres |
| Supabase 4–8h clone | Stale second brain; skip until public read-only insights |
| Home router port-forward | Exposes origin; no Access OTP |
| Quick `trycloudflare.com` only | Ephemeral URL; no durable Access hostname |

## Rollback

```bash
systemctl --user disable --now watch-tower-tunnel
# Optional: delete tunnel in Cloudflare Zero Trust → Networks → Tunnels
# Optional: delete DNS CNAME for HOSTNAME
```

Local tower on `http://127.0.0.1:8001` is unchanged.

## Change log

| Date | Note |
|---|---|
| 2026-08-03 | Option B chosen; `cloudflared` installed; setup script + this doc |
