# Milestone — Singularity Core v1 (recover here)

| Field | Value |
|---|---|
| Date | 2026-08-03 |
| Label | `milestone/singularity-core-v1` |
| Intent | Locked baseline Ashok accepted: living particle singularity + Miro/Figma 3D nav + Graph/City modes with tags. Evolve from here. |
| Git tip at lock | See tag `milestone/singularity-core-v1` |

## What was true at this milestone

- **Core** = GPU particle singularity (labor-market world-model heart). Brand-candidate shape (golden spiral shells, breath, orange heat). Ashok: “amazing — could be our logo.”
- **Nav** = OrbitControls: drag orbit · scroll/pinch dolly deep · right-drag pan · Esc/double-click reset. Particles dim inside (no whiteout).
- **Graph** = Obsidian-style clusters with text tags on nodes + strong edges (live Postgres world-model API).
- **City** = globe with city tags → district skyline with company building tags.
- Prior recovery still valid: `milestone/pre-neural-core-v0` (panel-first era before world-model rewrite).
- Push sovereignty unchanged: local commits free; push only with Ashok double-YES.

## Why we froze here

All of the above works good enough. Ashok ordered a revert point so evolution stays additive — never lose this locked aesthetic + navigation + mode split.

## How to recover

```bash
cd /home/user/Documents
git status
git tag -l 'milestone/*'
git checkout milestone/singularity-core-v1
# or branch:
git switch -c recover/singularity-core-v1 milestone/singularity-core-v1
```

Do **not** `reset --hard` unless Ashok explicitly orders it.
