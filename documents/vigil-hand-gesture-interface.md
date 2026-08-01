# VIGIL — Hand Gesture Interface

Living spec for air control of the Watch Tower ops shell.  
**Face name:** VIGIL · **Backend:** `ultron`  
**Code:** `job_engine/vigil/src/gestures/` · `job_engine/vigil/src/training/`

Last updated: 2026-08-02 (show-hand hold loop fix)

---

## Modes

| Mode | Switch | Input |
|---|---|---|
| **Desktop (default)** | VIGIL Mode OFF | Mouse / keyboard |
| **VIGIL Mode** | VIGIL Mode ON | Webcam hands |
| **Training Ground** | **Train** button | **Separate dummy screen** (not the live tower) |

- Desktop: no orbit dots; bottom ModuleDock only  
- Training: full-screen dummy room; live panels/core hidden  
- Stuck / timeout 45s / **I'm stuck — dump data** → JSON report to copy for Akay  

---

## Hand guides

| Hand | Color | Label |
|---|---|---|
| Right (primary) | Amber `#FFAA00` / crimson thumb | **R** |
| Left (second) | Cyan `#22D3EE` | **L** |
| Two-hand stretch | Purple dashed line between centroids | — |

---

## Gesture map (VIGIL Mode)

| Gesture | Where | Action |
|---|---|---|
| **Dwell / press-by-dot** | Button / chip | Click (sticky dwell) |
| **Pinch + drag** | Panel **header** (title area) | Move window |
| **Pinch + move up/down** | Panel **body** | Scroll list inside window |
| **Two-hand pinch** (locked ~0.3s) | Over a **window** | Zoom that window (scale) |
| **Two-hand pinch** (locked ~0.3s) | **Empty canvas** | Zoom energy core |
| **One-hand pinch + move** | Empty canvas | Pan canvas left/right |

Two-hand zoom uses a **lock delay + dead zone** so the core does not jump randomly.

Status badge shows live mode: `SCROLL PANEL`, `ZOOM PANEL`, `PAN CANVAS`, `CORE ZOOM`, etc.

---

## Training steps (dummy screen)

1. Welcome → Begin  
2. Show hand (either hand, ~1s hold bar, or **Hand seen — continue**)  
3. Pinch ×5  
4. Move SAMPLE window into drop zone  
5. Scroll SAMPLE list (pinch in body)  
6. Zoom SAMPLE (two-hand over window)  
7. Two-hand core (two-hand over empty space)  
8. Close TARGET  
9. Confirm → save calibration  
10. Fail dump if stuck / timeout  

Calibration keys: `pinchThreshold`, `dwellMs`, `hitPx`, `lerpFactor` in `localStorage` `vigil.calibration.v1`.

### Camera note (2026-08-02)

Training used to remount `<video>` and kill MediaPipe. Webcam is now a **stable
singleton** in `App.tsx`. Coach shows **HAND SEEN / NO HAND YET** plus camera status.

### Show-hand stuck fix (2026-08-02)

Bug: training `requestAnimationFrame` effect depended on `hands` every frame →
loop restarted constantly → hold timer never reached 1s (stuck on “Show hand”
while status showed `HAND SEEN · PAN CANVAS`).

Fix: read hands from `getState()` inside the tick; deps = `[step]` only; accept
L or R; progress bar; Continue button; disable pan/scroll/zoom during early
train steps so status does not steal to `PAN CANVAS`.

### Guides buried under training (2026-08-02)

Training screen `z-index: 50` covered finger guides (`30`) and webcam PiP — Ashok
saw HAND SEEN but no aiming dots. Guides → `z-index: 80`, webcam wrap → `90`.
Pan canvas disabled for all training so status stays clean.

### Move / scroll feel (2026-08-02)

Ashok timed out on move: pinch-drag felt random; scroll list looked empty.

- One visible SAMPLE = real hit target (removed ghost/visual split)
- Move: grab from whole window; fat title bar; hold 0.5s in bigger DROP ZONE
- Pinch hysteresis (release needs wider open) to stop grab flicker
- Scroll: 48 rows, tall list, 40px pass, 2.2× scroll boost in training
- Skip buttons for move/scroll if stuck

### Session logs

Every Train session writes events (camera boot, hand seen/lost, step enter/fail,
calibration save) to:

- Browser: `localStorage` `vigil.training.logs`
- Disk: `job_engine/.data/vigil_training/{id}.json` via `POST /api/ultron/training-log`
- Latest pointer: `job_engine/.data/vigil_training/latest.json`

Akay reads these to improve gestures after Ashok trains.

---

## Related files

| Path | Role |
|---|---|
| `gestures/useGestureOS.ts` | State machine |
| `gestures/hitTest.ts` | Hits / scroll helper |
| `gestures/useHandTracking.ts` | MediaPipe + dual smooth hands |
| `hud/FingerOverlay.tsx` | R/L guides |
| `training/TrainingScreen.tsx` | Separate training room |
| `training/buildFailReport.ts` | Copy-paste debug JSON |

Update this file whenever gestures change.
