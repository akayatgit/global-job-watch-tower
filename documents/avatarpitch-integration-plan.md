# Prompt Tower → AvatarPitch assets

AvatarPitch on Vercel stores rendered reels and reference files on the
ThinkPad through the tower asset API.

| Rule | Detail |
|---|---|
| Runtime | AvatarPitch = Vercel only. Files live on the ThinkPad |
| API | `PUT` / `GET` `/api/partner/v1/assets/{key}` |
| Public GET | Media tags cannot send bearer headers — capability URLs, no listing |
| GC | 48 hours, tower-owned |
| Access | Cloudflare Access bypass on `/api/partner/*` |

Prompt Tower writes reverse clips and daily-deck reels into the same
root. See [`prompt-tower.md`](prompt-tower.md).
