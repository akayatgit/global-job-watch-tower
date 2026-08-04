# Remote access — Cloudflare Tunnel + Access (Option B)

**Status (2026-08-03):** Tunnel **LIVE**. Access lock **must be verified** (see § Access fix).  
Brain stays on ThinkPad. Not Vercel / not Supabase / not port-forward.

## Live stamp

| Field | Value |
|---|---|
| Public URL | **https://tower.jobmaster.agency** |
| Access email (intended) | `ashokofficial55@gmail.com` |
| Tunnel name | `watch-tower` |
| Tunnel id | `5fe32c62-b99c-4793-90df-e629221650ef` |
| Origin | `http://127.0.0.1:8001` (loopback only) |
| Unit | `systemctl --user` → `watch-tower-tunnel.service` (enabled, linger on) |
| Credentials | `~/.cloudflared/` (never commit) |
| Stamp file | `job_engine/.data/cloudflare_tunnel.json` (gitignored) |

**Verified:** public HTTPS returns VIGIL (tunnel + DNS OK).  
**Not yet verified:** Cloudflare Access OTP gate — unauthenticated GET still served VIGIL HTML (2026-08-03). Do **not** share the URL until Access is confirmed in a private/incognito window.

## Architecture

```
Any browser  →  https://tower.jobmaster.agency
                     │
              Cloudflare edge (TLS + Access OTP — required)
                     │
              Cloudflare Tunnel (cloudflared on ThinkPad)
                     │
              http://127.0.0.1:8001
                     │
         Postgres / Redis / Celery / Chrome / Ollama  (never exposed)
```

## Access fix (do this if URL opens with no login)

Use **Zero Trust**, not the domain “Access” sidebar item alone.

1. Open **https://one.dash.cloudflare.com** (Zero Trust dashboard).
2. Left: **Access** → **Applications**.
3. **Add an application** → **Self-hosted**.
4. **Application name:** `Watch Tower`
5. **Public hostname:**
   - Subdomain: `tower`
   - Domain: `jobmaster.agency`
   - Path: leave empty (protects entire site)
6. **Identity providers:** leave default (One-time PIN / email is fine; Google optional).
7. **Add policy:**
   - Name: `Ashok only`
   - Action: **Allow**
   - Include → **Emails** → `ashokofficial55@gmail.com`
8. **Save**.
9. Test: open an **Incognito/Private** window → `https://tower.jobmaster.agency`  
   You **must** see Cloudflare Access login / email code — not VIGIL immediately.  
   After OTP → VIGIL.

**Common mistakes**

| Mistake | Result |
|---|---|
| App hostname = `jobmaster.agency` only (no `tower`) | `tower.` stays open |
| Policy Action = Bypass | No login |
| Only “Protect your app” Worker path | Wrong product |
| Already logged-in Cloudflare session in same browser | Looks “done” but strangers still get in — always test Incognito |

When Incognito shows the Access gate, reply so Akay can re-probe and mark Access **LOCKED** in this doc.

## One-shot setup (already run on ThinkPad)

```bash
HOSTNAME=tower.jobmaster.agency ACCESS_EMAIL=ashokofficial55@gmail.com \
  bash scripts/cloudflare_tunnel_setup.sh
```

Re-run is safe (idempotent tunnel reuse). Credentials stay under `~/.cloudflared/`.

## Day-2 ops

| Action | Command |
|---|---|
| Status | `systemctl --user status watch-tower-tunnel` |
| Logs | `journalctl --user -u watch-tower-tunnel -f` |
| Restart tunnel | `systemctl --user restart watch-tower-tunnel` |
| Tunnel info | `cloudflared tunnel info watch-tower` |

Tunnel does **not** disturb scrapes. Deploy restarts API/worker/beat only.

To confirm a merged PR actually deployed (Akay's post-merge check, works
from Cursor cloud with no ThinkPad access): see
[`deploy-verification.md`](./deploy-verification.md).

## Security rules

- Never expose Postgres `:5433` or Redis publicly.
- Never commit `~/.cloudflared/` credentials.
- Access allowlist = Ashok email only.
- Do not share the hostname until Incognito shows the Access gate.
- Laptop must stay awake/on network (lid policy already ignores suspend).

## What we deliberately do not do

| Idea | Why not (sole admin) |
|---|---|
| Vercel host the app | No Celery / Chrome / Ollama / local Postgres |
| Supabase 4–8h clone | Stale second brain; later for public insights only |
| Home router port-forward | Exposes origin |
| Quick `trycloudflare.com` only | Ephemeral; weak Access story |

## Rollback

```bash
systemctl --user disable --now watch-tower-tunnel
# Optional: delete tunnel in Zero Trust → Networks → Tunnels
# Optional: delete DNS CNAME tower.jobmaster.agency
```

Local `http://127.0.0.1:8001` unchanged.

## Change log

| Date | Note |
|---|---|
| 2026-08-03 | Option B chosen; `cloudflared` installed; setup script |
| 2026-08-03 | Tunnel LIVE: `tower.jobmaster.agency` → ThinkPad `:8001` |
| 2026-08-03 | Ashok reported Access done; Akay probe still open — Access fix checklist added |
