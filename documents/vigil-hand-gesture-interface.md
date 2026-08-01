# VIGIL — Hand Gesture Interface

Living spec for air control of the Watch Tower ops shell.  
**Face name:** VIGIL · **Backend:** `ultron`  
**Code:** `job_engine/vigil/src/gestures/` · `job_engine/vigil/src/training/`

Last updated: 2026-08-02 (layer stack + free practice + flick/fist)

---

## Modes

| Mode | Switch | Input |
|---|---|---|
| **Desktop (default)** | VIGIL Mode OFF | Mouse / keyboard |
| **VIGIL Mode** | VIGIL Mode ON | Webcam hands |
| **Training Ground** | **Train** button | **Separate dummy screen** + practice hub |

- Desktop: no orbit dots; bottom ModuleDock only  
- Training: hub → skip, guided tour, or pick any drill anytime  
- Calibration + feel from training apply to the live tower  

---

## Layer stack (one window at a time)

When a window is **focused / on top**:

- Core, canvas, dock (VIGIL Mode), and **all other windows** blur and dim  
- Hand dwell / pinch / scroll only hit the **focused** window (+ its Close)  
- Opening another window (dock / orbit when no focus lock) brings it to top  
- Closing promotes the next highest open window  

Goal: stop accidental dwell on everything behind the active dialog.

---

## Hand guides (training = live)

| Hand | Color | Label |
|---|---|---|
| Right (primary) | Amber `#FFAA00` / crimson thumb | **R** |
| Left (second) | Cyan `#22D3EE` | **L** |
| Fist | Red | **FIST** |
| Two-hand stretch | Purple dashed line | — |

- Soft spotlight under the fingertip + glow (same illumination as training)  
- Window under the hand gets **hand-hot** cyan border / luminance  

---

## Gesture map (VIGIL Mode)

| Gesture | Where | Action |
|---|---|---|
| **Dwell** | Button on focused layer | Click |
| **Pinch + drag** | Panel header (or whole panel in move drill) | Move window |
| **Pinch + move** | Panel body | Scroll list |
| **Two-hand pinch** (lock ~0.3s) | Over window | Zoom window |
| **Two-hand pinch** (lock ~0.3s) | Empty canvas (no layer lock) | Zoom energy core |
| **Flick zoom** | Pinch then snap fingers wide & fast | Max zoom current window |
| **Fist (5 fingers curled)** | Over / focused window | Close that window |
| **One-hand pinch + move** | Empty canvas (no layer lock) | Pan canvas |

Status badge: `SCROLL PANEL`, `ZOOM PANEL`, `FLICK ZOOM`, `FIST CLOSE`, etc.

---

## Training hub

1. **Skip training — go to tower**  
2. **Start guided tour** (optional chain)  
3. **Practice any drill** (no timer): show hand, pinch, move, scroll, zoom, flick zoom, fist close, dwell close, core zoom  
4. **← Practice hub** from any drill  

Logs: every hover, drag, scroll, dwell fire, flick, fist, practice select/pass →  
`localStorage` `vigil.training.logs` + `job_engine/.data/vigil_training/`  
Live VIGIL Mode also starts a `live-*` session log.

Calibration keys: `pinchThreshold`, `dwellMs`, `hitPx`, `lerpFactor` in `localStorage` `vigil.calibration.v1`.

---

## History fixes (2026-08-02)

- Show-hand rAF dependency bug; guides under training z-index; move ghost panel; long scroll list  
- Layer stack + flick/fist + free practice hub (this slice)  
