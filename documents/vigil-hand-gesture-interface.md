# VIGIL — Hand Gesture Interface

Living spec for air control of the Watch Tower ops shell.  
**Face name:** VIGIL · **Backend:** `ultron` (`/ws/ultron`)  
**Code:** `job_engine/vigil/src/gestures/` · `job_engine/vigil/src/training/`

Last updated: 2026-08-02

---

## Modes

| Mode | How to switch | Input |
|---|---|---|
| **Desktop (default)** | Top-right **VIGIL Mode** = OFF | Mouse click, drag, scroll, keyboard / typing |
| **VIGIL Mode** | Top-right **VIGIL Mode** = ON | Webcam + MediaPipe hands; finger guides on screen |
| **Training Ground** | Top-right **Train** | Forces VIGIL Mode ON; guided drills + auto-calibration |

Preference: `localStorage` `vigil.mode` (`on` / `off`).  
Calibration: `localStorage` `vigil.calibration.v1`.

### VIGIL Mode OFF

- Camera / hand tracking stops
- Finger guides and webcam PiP hide
- **No orbit dots** around the core (bottom ModuleDock is enough)
- Module dock + panels: mouse & keyboard
- Drag a panel by its header with the mouse

### VIGIL Mode ON

- Hand Landmarker runs; gesture OS active
- Orbit dots visible (for air targeting)
- Finger guides + PiP visible
- Thresholds come from **calibration** (not hard-coded forever)

---

## Training Ground (daily fine-tune)

Entry: **Train** button (top right, next to VIGIL Mode).

| Step | Ashok does | System learns |
|---|---|---|
| 1 Welcome | Begin | — |
| 2 Show hand | Hold hand in frame ~1.5s | Tracking lock |
| 3 Pinch | Pinch 5× | Pinch / open distance samples |
| 4 Move | Drag Tower panel into drop zone | Speed + grab reliability |
| 5 Close | Dwell on Close | Dwell timing |
| 6 Press | Dwell on Confirm | Dwell timing |
| 7 Done | Saves calibration | Updates live feel |

After each completed session, `computeCalibration()` updates:

| Param | Meaning |
|---|---|
| `pinchThreshold` | Thumb↔index distance for pinch |
| `dwellMs` | Hold time for press-by-dot |
| `hitPx` | Orbit hit radius (px) |
| `lerpFactor` | Guide smoothing (higher = snappier) |
| `sessionsCompleted` | Training count |

Code: `vigil/src/training/TrainingSession.tsx`, `calibration.ts`, `sampleBus.ts`.

Plan: train a few days in a row; each session tightens feel for Ashok’s hands.

---

## Finger guides (VIGIL Mode ON)

| Guide | Landmark | Look |
|---|---|---|
| Index reticle | Tip (8) | Amber ring + crosshair |
| Thumb reticle | Tip (4) | Smaller crimson ring |
| Pinch tether | 4 ↔ 8 | Glowing line; bright when pinched |
| Press progress | Dwell on target | Expanding white ring |
| Snap magnet | Nearest orbit node | Dashed attractor line |

Smoothing: `lerp(current, target, calibration.lerpFactor)`.

---

## Gesture vocabulary (VIGIL Mode ON)

| Gesture | Threshold / cue | Action |
|---|---|---|
| **Press-by-dot** | Index over target for `dwellMs` | Open module / click chip / focus panel |
| **Pinch** | Thumb↔index &lt; `pinchThreshold` | Grab panel header |
| **Pinch + move** | Hold pinch | Drag floating panel |
| **Release pinch** | Distance rises | Drop panel; sync via `ultron.panel` |
| **Two-hand pinch apart/together** | Both hands pinching | Scale energy core |
| **Point at orbit node** | Within `hitPx` | Soft highlight + magnet (VIGIL Mode) |

Defaults before first train: pinch `0.045`, dwell `700ms`, hit `64px`, lerp `0.15`.

---

## Module map (orbit / dock)

Readable names: bottom **ModuleDock** only.  
3D orbit spheres: **VIGIL Mode ON only**, unlabeled (no HTML titles over panels).

| Node label (dock) | Panel id |
|---|---|
| Tech Jobs | `jobs` |
| Hiring Signals | `signals` |
| Searches | `searches` |
| Activity | `activity` |
| Live | `live` |
| Health | `health` |
| Watchlist | `watchlist` |
| Remote Trends | opens `jobs` |

---

## Improvement backlog

1. ~~Desktop fallback with VIGIL Mode toggle~~ (2026-08-01)
2. ~~Orbit HTML labels under panels~~ (2026-08-02)
3. ~~Hide orbit dots when VIGIL Mode OFF~~ (2026-08-02)
4. ~~Training ground + auto-calibration~~ (2026-08-02)
5. Optional quick-pinch click (no dwell)
6. Air typing / chip keyboard for search create
7. Manual slider overrides next to Train
8. Voice status (“Hey Vigil”) — later

---

## Related files

| Path | Role |
|---|---|
| `vigil/src/gestures/useHandTracking.ts` | MediaPipe + calibrated pinch/lerp |
| `vigil/src/gestures/useGestureOS.ts` | Pinch / dwell / drag / zoom |
| `vigil/src/training/*` | Training session + calibration |
| `vigil/src/hud/StatusHud.tsx` | VIGIL Mode + Train |
| `vigil/src/store/vigilStore.ts` | Mode, training, calibration state |
| `app/ultron/` | Backend bus |

When changing any gesture rule, **update this document in the same slice**.
