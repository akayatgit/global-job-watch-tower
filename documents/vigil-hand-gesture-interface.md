# VIGIL — Hand Gesture Interface

Living spec for air control of the Watch Tower ops shell.  
**Face name:** VIGIL · **Backend:** `ultron` (`/ws/ultron`)  
**Code:** `job_engine/vigil/src/gestures/` · `job_engine/vigil/src/hud/FingerOverlay.tsx`

Last updated: 2026-08-02

---

## Modes

| Mode | How to switch | Input |
|---|---|---|
| **Desktop (default)** | Top-right **VIGIL Mode** = OFF | Mouse click, drag, scroll, keyboard / typing |
| **VIGIL Mode** | Top-right **VIGIL Mode** = ON | Webcam + MediaPipe hands; finger guides on screen |

Preference is stored in `localStorage` key `vigil.mode` (`on` / `off`).

When VIGIL Mode is **OFF**:

- Camera / hand tracking stops
- Finger guides and webcam PiP hide
- Module dock + panels work with normal mouse & keyboard
- Drag a panel by its header with the mouse

When VIGIL Mode is **ON**:

- Hand Landmarker runs; gesture OS active
- Desktop mouse still works on HUD chrome (toggle, vitals) but panel/orbit control prefers hands

---

## Finger guides (VIGIL Mode ON)

| Guide | Landmark | Look |
|---|---|---|
| Index reticle | Tip (8) | Amber ring + crosshair |
| Thumb reticle | Tip (4) | Smaller crimson ring |
| Pinch tether | 4 ↔ 8 | Glowing line; bright when pinched |
| Press progress | Dwell on target | Expanding white ring |
| Snap magnet | Nearest orbit node | Dashed attractor line |

Smoothing: `lerp(current, target, 0.15)` every animation frame.

---

## Gesture vocabulary (VIGIL Mode ON)

| Gesture | Threshold / cue | Action |
|---|---|---|
| **Press-by-dot** | Index over target ~700ms | Open module / click chip / focus panel |
| **Pinch** | Thumb↔index distance &lt; **0.04** | Grab panel header or arm drag |
| **Pinch + move** | Hold pinch | Drag floating panel |
| **Release pinch** | Distance rises | Drop panel; sync via `ultron.panel` |
| **Two-hand pinch apart/together** | Both hands pinching | Scale energy core; status “SYNCING…” |
| **Point at orbit node** | Near projected node | Soft highlight + magnet line |

Pinch threshold and dwell time live in `useGestureOS.ts` / `useHandTracking.ts` — tune as Ashok’s feel improves.

---

## Module map (orbit / dock)

Readable names live **only** on the bottom **ModuleDock** chips (and status line).  
3D orbit spheres are unlabeled so HTML labels never stack above floating panels
(fixed 2026-08-02 — drei `Html` was painting over widgets).

| Node label (dock) | Panel id |
|---|---|
| Tech Jobs | `jobs` |
| Hiring Signals | `signals` |
| Searches | `searches` |
| Activity | `activity` |
| Live | `live` |
| Health | `health` |
| Watchlist | `watchlist` |
| Remote Trends | opens `jobs` with remote filter intent |

---

## Improvement backlog (hand feel)

Update this list whenever we change interaction:

1. ~~Desktop fallback with VIGIL Mode toggle~~ (done 2026-08-01)
2. Calibrate pinch threshold per user (UI slider)
3. Larger hit targets for orbit nodes
4. Optional “click” on quick pinch instead of long dwell only
5. Air typing / chip keyboard for search create
6. Voice status (“Hey Vigil”) — out of scope v1

---

## Related files

| Path | Role |
|---|---|
| `vigil/src/gestures/useHandTracking.ts` | MediaPipe Landmarker |
| `vigil/src/gestures/useGestureOS.ts` | Pinch / dwell / drag / zoom |
| `vigil/src/hud/FingerOverlay.tsx` | On-screen guides |
| `vigil/src/hud/StatusHud.tsx` | VIGIL Mode switch (top right) |
| `vigil/src/store/vigilStore.ts` | `vigilMode` state |
| `app/ultron/` | Backend bus |

When changing any gesture rule, **update this document in the same slice**.
