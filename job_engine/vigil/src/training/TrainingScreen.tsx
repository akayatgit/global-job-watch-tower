import { useEffect, useRef, useState } from 'react'
import { useVigilStore } from '../store/vigilStore'
import { computeCalibration } from './calibration'
import { buildFailReport } from './buildFailReport'
import {
  getSamples,
  pushDwell,
  pushJitter,
  pushOpen,
  pushPinch,
  pushSpeed,
  resetSamples,
} from './sampleBus'
import { endTrainLog, logTrain } from './sessionLog'
import type { TrainingStepId } from '../store/vigilStore'

const STEPS = [
  {
    id: 'hub',
    title: 'Practice hub',
    hint: 'Skip anytime, or pick any drill. Guided tour is optional — spend as long as you want.',
  },
  { id: 'intro', title: 'Welcome', hint: 'Guided tour — dummy room, not the live tower.' },
  { id: 'show_hand', title: 'Show hand', hint: 'Raise either hand. Watch the bar fill to 100%, or click Continue when HAND SEEN.' },
  { id: 'pinch', title: 'Pinch', hint: 'Pinch thumb + index 5 times.' },
  {
    id: 'move',
    title: 'Move window',
    hint: '1) Point L/R at SAMPLE title  2) Pinch  3) Drag to DROP ZONE  4) Hold or open fingers.',
  },
  {
    id: 'scroll',
    title: 'Scroll window',
    hint: 'Pinch inside the SAMPLE list and move hand up/down.',
  },
  { id: 'zoom_window', title: 'Zoom window', hint: 'Both hands pinch over SAMPLE — slowly apart, or flick-release for max zoom.' },
  { id: 'flick_zoom', title: 'Flick zoom', hint: 'Pinch on SAMPLE, then snap fingers wide & fast → window zooms to max.' },
  { id: 'two_hand', title: 'Two-hand core', hint: 'Both hands pinch over empty space — slow apart.' },
  { id: 'fist_close', title: 'Fist close', hint: 'Curl all five fingers (fist) over SAMPLE to close it.' },
  { id: 'close', title: 'Close (dwell)', hint: 'Hold on the big CLOSE TARGET until 100%.' },
  { id: 'press', title: 'Confirm', hint: 'Hold on CONFIRM to save your calibration.' },
  { id: 'done', title: 'Saved', hint: 'Feel is stored. Exit back to the live tower.' },
  { id: 'fail', title: 'Needs help', hint: 'Copy the report below and paste it to Akay.' },
] as const

const PRACTICE_DRILLS: { id: (typeof STEPS)[number]['id']; label: string }[] = [
  { id: 'show_hand', label: 'Show hand' },
  { id: 'pinch', label: 'Pinch' },
  { id: 'move', label: 'Move window' },
  { id: 'scroll', label: 'Scroll list' },
  { id: 'zoom_window', label: 'Two-hand zoom' },
  { id: 'flick_zoom', label: 'Flick zoom max' },
  { id: 'fist_close', label: 'Fist close' },
  { id: 'close', label: 'Dwell close' },
  { id: 'two_hand', label: 'Core zoom' },
]

const DUMMY_ROWS = Array.from(
  { length: 48 },
  (_, i) => `Sample row ${i + 1} — scroll practice line · keep pinching and move hand`,
)

export function TrainingScreen() {
  const step = useVigilStore((s) => s.trainingStep)
  const feedback = useVigilStore((s) => s.trainingFeedback)
  const failReport = useVigilStore((s) => s.trainingFailReport)
  const setStep = useVigilStore((s) => s.setTrainingStep)
  const setFeedback = useVigilStore((s) => s.setTrainingFeedback)
  const setFailReport = useVigilStore((s) => s.setTrainingFailReport)
  const setPractice = useVigilStore((s) => s.setTrainingPractice)
  const stopTraining = useVigilStore((s) => s.stopTraining)
  const setCalibration = useVigilStore((s) => s.setCalibration)
  const calibration = useVigilStore((s) => s.calibration)
  const hands = useVigilStore((s) => s.hands)
  const pressProgress = useVigilStore((s) => s.pressProgress)
  const gestureMode = useVigilStore((s) => s.gestureMode)

  const [pinchCount, setPinchCount] = useState(0)
  const [sampleOpen, setSampleOpen] = useState(true)
  const [copied, setCopied] = useState(false)
  const [scrollDelta, setScrollDelta] = useState(0)
  const zoneHold = useRef(0)
  const lastPinch = useRef(false)
  const lastPos = useRef<{ x: number; y: number; t: number } | null>(null)
  const stepStarted = useRef(performance.now())
  const scrollStart = useRef(0)
  const zoomBase = useRef(1)
  const twoBase = useRef(0)
  const dwellStart = useRef<number | null>(null)

  const failStep = (why: string) => {
    const report = buildFailReport({
      step,
      feedback: why,
      calibration,
      handsSummary: `L=${hands.left ? 'yes' : 'no'} R=${hands.right ? 'yes' : 'no'} two=${hands.twoHandPinch}`,
      gestureMode,
    })
    logTrain('step_fail', { step, why })
    endTrainLog({ reason: 'fail', step, why })
    setFailReport(report)
    setFeedback(why)
    setStep('fail')
  }

  const handSeen = Boolean(hands.left || hands.right)
  const statusLine = useVigilStore((s) => s.statusLine)

  const passOrHub = (next: TrainingStepId, msg: string) => {
    const st = useVigilStore.getState()
    logTrain('practice_pass', { step: st.trainingStep, next, practice: st.trainingPractice })
    if (st.trainingPractice) {
      setFeedback(`${msg} — back to hub`)
      setPractice(false)
      setStep('hub')
      return
    }
    setFeedback(msg)
    setStep(next)
  }

  const startPractice = (id: TrainingStepId) => {
    resetSamples()
    setPinchCount(0)
    setScrollDelta(0)
    zoneHold.current = 0
    setPractice(true)
    setSampleOpen(true)
    const st = useVigilStore.getState()
    st.openPanel('tower')
    st.movePanel('tower', 18, 28)
    st.scalePanel('tower', 1)
    logTrain('practice_select', { id })
    setStep(id)
    setFeedback(`Practice: ${id.replace('_', ' ')} — take your time`)
    stepStarted.current = performance.now()
  }

  useEffect(() => {
    resetSamples()
    setPinchCount(0)
    setSampleOpen(true)
    setScrollDelta(0)
    zoneHold.current = 0
    setPractice(false)
    setStep('hub')
    setFeedback('Pick any drill, start a guided tour, or skip to the tower')
    stepStarted.current = performance.now()
    logTrain('training_screen_mount')
  }, [setStep, setFeedback, setPractice])

  useEffect(() => {
    stepStarted.current = performance.now()
    logTrain('step_enter', { step })
  }, [step])

  const holdMs = useRef(0)
  const [holdPct, setHoldPct] = useState(0)

  useEffect(() => {
    if (step === 'idle' || step === 'hub' || step === 'intro' || step === 'done' || step === 'fail') return
    let raf = 0
    let lastTick = performance.now()
    holdMs.current = 0
    setHoldPct(0)

    const tick = () => {
      const st = useVigilStore.getState()
      const currentStep = st.trainingStep
      const primary = st.hands.right || st.hands.left
      const idx = st.smoothIndex
      const now = performance.now()
      const dt = Math.min(100, now - lastTick)
      lastTick = now

      // Free practice: no timeout. Guided tour: 90s soft fail.
      const limit = st.trainingPractice ? 0 : 90000
      if (
        limit > 0 &&
        now - stepStarted.current > limit &&
        !['done', 'fail', 'hub'].includes(currentStep)
      ) {
        failStep(`Timed out on step "${currentStep}" after ${limit / 1000}s`)
        return
      }

      if (primary) {
        if (primary.pinch) pushPinch(primary.pinchDist)
        else if (primary.pinchDist > 0) pushOpen(primary.pinchDist)
        if (lastPos.current) {
          const dtp = (now - lastPos.current.t) / 1000
          if (dtp > 0.01 && dtp < 0.2) {
            pushSpeed(
              Math.hypot(idx.x - lastPos.current.x, idx.y - lastPos.current.y) / dtp,
            )
          }
        }
        lastPos.current = { x: idx.x, y: idx.y, t: now }
        pushJitter(0.008)
      }

      if (currentStep === 'show_hand') {
        // Accept either hand presence (index tip optional — MediaPipe can lag a frame)
        if (st.hands.left || st.hands.right) {
          holdMs.current += dt
          const pct = Math.min(100, Math.round((holdMs.current / 1000) * 100))
          setHoldPct(pct)
          setFeedback(`Hand seen — hold steady… ${pct}%`)
          if (holdMs.current >= 1000) {
            logTrain('show_hand_pass', { holdMs: holdMs.current, which: st.hands.right ? 'R' : 'L' })
            passOrHub('pinch', 'Hand locked')
          }
        } else {
          holdMs.current = Math.max(0, holdMs.current - dt * 2)
          setHoldPct(Math.min(100, Math.round((holdMs.current / 1000) * 100)))
          setFeedback('Raise either hand until HAND SEEN stays on')
        }
      }

      if (currentStep === 'pinch' && primary) {
        if (primary.pinch && !lastPinch.current) {
          setPinchCount((c) => {
            const n = c + 1
            setFeedback(n >= 5 ? 'Pinch OK' : `Pinch ${n}/5`)
            logTrain('pinch_count', { n })
            if (n >= 5) {
              st.openPanel('tower')
              st.movePanel('tower', 18, 28)
              st.scalePanel('tower', 1)
              setSampleOpen(true)
              window.setTimeout(() => passOrHub('move', 'Pinch OK'), 300)
            }
            return n
          })
        }
        lastPinch.current = primary.pinch
      }

      if (currentStep === 'move') {
        const p = st.panels.tower
        // Panel center vs DROP ZONE (right side of stage)
        const cx = p.x + 14
        const cy = p.y + 12
        const inZone = cx >= 58 && cx <= 94 && cy >= 18 && cy <= 62
        if (st.grabTarget === 'tower') {
          if (inZone) {
            zoneHold.current += dt
            setFeedback(`In DROP ZONE — hold… ${Math.min(100, Math.round((zoneHold.current / 500) * 100))}%`)
            if (zoneHold.current >= 500) {
              logTrain('move_pass', { x: p.x, y: p.y })
              const body = document.querySelector(
                '[data-panel-id="tower"] .panel-body',
              ) as HTMLElement | null
              scrollStart.current = body?.scrollTop || 0
              setScrollDelta(0)
              zoneHold.current = 0
              passOrHub('scroll', 'Move OK')
            }
          } else {
            zoneHold.current = 0
            setFeedback('Dragging… keep pinch, move into the glowing DROP ZONE')
          }
        } else if (inZone && st.gestureMode === 'none') {
          logTrain('move_pass_release', { x: p.x, y: p.y })
          const body = document.querySelector(
            '[data-panel-id="tower"] .panel-body',
          ) as HTMLElement | null
          scrollStart.current = body?.scrollTop || 0
          setScrollDelta(0)
          passOrHub('scroll', 'Move OK')
        } else if (st.hoverTarget === 'panel:tower') {
          setFeedback('GRAB READY — pinch now, then drag to DROP ZONE')
        } else {
          setFeedback('Point L/R dot at amber SAMPLE title → pinch → drag to DROP ZONE')
        }
      }

      if (currentStep === 'scroll') {
        const body = document.querySelector(
          '[data-panel-id="tower"] .panel-body',
        ) as HTMLElement | null
        const delta = Math.abs((body?.scrollTop || 0) - scrollStart.current)
        setScrollDelta(delta)
        if (st.gestureMode === 'scroll_panel') {
          setFeedback(`Scrolling… ${Math.round(delta)}px (need 40+)`)
        } else if (st.hoverTarget === 'body:tower') {
          setFeedback('Over the list — pinch and move hand up/down')
        } else {
          setFeedback('Point at the SAMPLE list (below title), pinch, move hand up/down')
        }
        if (delta > 40) {
          zoomBase.current = st.panels.tower.scale
          passOrHub('zoom_window', 'Scroll OK')
        }
      }

      if (currentStep === 'zoom_window' || currentStep === 'flick_zoom') {
        const scale = st.panels.tower.scale
        if (st.gestureMode === 'zoom_panel') {
          setFeedback(`Zooming window… scale ${scale.toFixed(2)}`)
        } else if (currentStep === 'flick_zoom') {
          setFeedback('Pinch then snap fingers wide & fast for MAX zoom')
        } else {
          setFeedback('Both hands pinch OVER SAMPLE — or flick-release for max zoom')
        }
        if (scale >= 1.75 || Math.abs(scale - zoomBase.current) > 0.12) {
          twoBase.current = st.coreScale
          st.movePanel('tower', 12, 30)
          passOrHub('two_hand', 'Zoom OK')
        }
      }

      if (currentStep === 'fist_close') {
        if (!st.panels.tower.open) {
          passOrHub('hub', 'Fist close OK')
        } else if (primary?.fist) {
          setFeedback('Fist detected — closing…')
        } else {
          setFeedback('Curl all five fingers into a fist over SAMPLE')
        }
      }

      if (currentStep === 'two_hand') {
        if (st.gestureMode === 'core_zoom') {
          setFeedback(`Core zoom… ${st.coreScale.toFixed(2)}`)
        } else if (st.hands.twoHandPinch) {
          setFeedback('Locked… keep both pinched, slowly change distance')
        } else {
          setFeedback('Pinch BOTH hands in empty space (not on the window)')
        }
        if (Math.abs(st.coreScale - twoBase.current) > 0.15) {
          passOrHub('fist_close', 'Two-hand OK')
        }
      }

      if (currentStep === 'close') {
        if (st.pressProgress > 0) {
          if (!dwellStart.current) dwellStart.current = now
          setFeedback(`Close… ${Math.round(st.pressProgress * 100)}%`)
        } else setFeedback('Hold on CLOSE TARGET')
      }

      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // Only rebind when the step changes — never on every hands frame
  }, [step, setStep, setFeedback])

  const meta = STEPS.find((s) => s.id === step) || STEPS[0]

  const finish = () => {
    const next = computeCalibration(getSamples(), calibration)
    setCalibration(next)
    logTrain('calibration_saved', { ...next })
    endTrainLog({ reason: 'success', sessionsCompleted: next.sessionsCompleted })
    setStep('done')
    setFeedback(
      `Saved pinch=${next.pinchThreshold.toFixed(3)} dwell=${next.dwellMs}ms hit=${next.hitPx} #${next.sessionsCompleted}`,
    )
  }

  const copyFail = async () => {
    try {
      await navigator.clipboard.writeText(failReport || buildFailReport({
        step,
        feedback,
        calibration,
        handsSummary: 'n/a',
        gestureMode,
      }))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setFeedback('Copy failed — select the text manually')
    }
  }

  // Hide real tower panel chrome during training by overlaying our dummy;
  // keep tower panel in DOM for hit-tests but visually covered / synced
  useEffect(() => {
    if (step === 'move' || step === 'scroll' || step === 'zoom_window' || step === 'close') {
      useVigilStore.getState().openPanel('tower')
    }
  }, [step])

  return (
    <div className="training-screen">
      <header className="training-screen-bar">
        <div>
          <h1>VIGIL TRAINING GROUND</h1>
          <p>Dummy widgets only · live tower is paused</p>
        </div>
        <div className="training-screen-actions">
          <button type="button" className="chip" onClick={() => failStep('Marked failed by Ashok')}>
            I&apos;m stuck — dump data
          </button>
          <button type="button" className="chip" onClick={stopTraining}>
            Exit to tower
          </button>
        </div>
      </header>

      <aside className="training-coach">
        <h2>{meta.title}</h2>
        <p className="training-hint">{meta.hint}</p>
        <p className="training-feedback">{feedback}</p>
        <p className={`train-cam-status ${handSeen ? 'ok' : 'warn'}`}>
          {handSeen ? 'HAND SEEN' : 'NO HAND YET'} · {statusLine}
        </p>
        <p className="muted">
          Mode: {gestureMode} · L:{hands.left ? 'on' : '—'} R:{hands.right ? 'on' : '—'} · sessions{' '}
          {calibration.sessionsCompleted}
        </p>

        {step === 'hub' && (
          <>
            <button
              type="button"
              className="chip active train-hit"
              data-gesture-action="train-skip-all"
              onClick={() => {
                logTrain('training_skipped')
                stopTraining()
              }}
            >
              Skip training — go to tower
            </button>
            <button
              type="button"
              className="chip train-hit"
              data-gesture-action="train-guided"
              onClick={() => {
                resetSamples()
                setPractice(false)
                logTrain('guided_tour_start', { handSeen })
                setStep('show_hand')
                setFeedback(
                  handSeen
                    ? 'Guided tour — hand already seen, hold steady'
                    : 'Guided tour — show hand until HAND SEEN',
                )
              }}
            >
              Start guided tour
            </button>
            <p className="muted" style={{ marginTop: 10 }}>
              Practice any drill (no timer):
            </p>
            <div className="training-hub-grid">
              {PRACTICE_DRILLS.map((d) => (
                <button
                  key={d.id}
                  type="button"
                  className="chip train-hit"
                  data-gesture-action={`train-practice-${d.id}`}
                  onClick={() => startPractice(d.id as TrainingStepId)}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </>
        )}

        {step !== 'hub' && step !== 'done' && step !== 'fail' && (
          <button
            type="button"
            className="chip train-hit"
            data-gesture-action="train-back-hub"
            onClick={() => {
              logTrain('back_to_hub', { from: step })
              setPractice(false)
              setStep('hub')
              setFeedback('Back at hub — pick another drill or skip')
            }}
            style={{ marginTop: 8 }}
          >
            ← Practice hub
          </button>
        )}

        {step === 'show_hand' && (
          <>
            <div className="training-meter">
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${holdPct}%` }} />
              </div>
              <span>{holdPct}%</span>
            </div>
            {handSeen && (
              <button
                type="button"
                className="chip active train-hit"
                data-gesture-action="train-skip-hand"
                onClick={() => {
                  logTrain('show_hand_manual_continue')
                  setFeedback('Hand accepted — pinch next')
                  setStep('pinch')
                }}
              >
                Hand seen — continue
              </button>
            )}
          </>
        )}

        {step === 'pinch' && (
          <div className="training-meter">
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(pinchCount / 5) * 100}%` }} />
            </div>
            <span>{pinchCount}/5</span>
          </div>
        )}

        {step === 'move' && (
          <button
            type="button"
            className="chip train-hit"
            data-gesture-action="train-skip-move"
            onClick={() => {
              logTrain('move_manual_skip')
              const st = useVigilStore.getState()
              st.movePanel('tower', 62, 30)
              const body = document.querySelector(
                '[data-panel-id="tower"] .panel-body',
              ) as HTMLElement | null
              scrollStart.current = body?.scrollTop || 0
              setScrollDelta(0)
              setFeedback('Skipped move — scroll the SAMPLE list next')
              setStep('scroll')
            }}
          >
            Skip move — I understand
          </button>
        )}

        {step === 'scroll' && (
          <>
            <div className="training-meter">
              <div className="bar-track">
                <div className="bar-fill" style={{ width: `${Math.min(100, (scrollDelta / 40) * 100)}%` }} />
              </div>
              <span>{Math.round(scrollDelta)}/40px</span>
            </div>
            <button
              type="button"
              className="chip train-hit"
              data-gesture-action="train-skip-scroll"
              onClick={() => {
                logTrain('scroll_manual_skip')
                zoomBase.current = useVigilStore.getState().panels.tower.scale
                setFeedback('Skipped scroll — zoom next')
                setStep('zoom_window')
              }}
            >
              Skip scroll — I understand
            </button>
          </>
        )}

        {step === 'close' && (
          <button
            type="button"
            className="training-close-target train-hit"
            data-gesture-action="train-close"
            onClick={() => {
              pushDwell(dwellStart.current ? performance.now() - dwellStart.current : calibration.dwellMs)
              useVigilStore.getState().closePanel('tower', { force: true })
              setSampleOpen(false)
              setStep('press')
              setFeedback('Hold CONFIRM to save')
            }}
          >
            CLOSE TARGET
            <span>{Math.round(pressProgress * 100)}%</span>
          </button>
        )}

        {step === 'press' && (
          <button
            type="button"
            className="chip active train-hit"
            data-gesture-action="train-confirm"
            onClick={finish}
          >
            Confirm & save
          </button>
        )}

        {step === 'done' && (
          <div className="chip-row">
            <button type="button" className="chip active" onClick={stopTraining}>
              Back to tower
            </button>
            <button
              type="button"
              className="chip"
              onClick={() => useVigilStore.getState().startTraining()}
            >
              Train again
            </button>
          </div>
        )}

        {step === 'fail' && (
          <>
            <button type="button" className="chip active" onClick={copyFail}>
              {copied ? 'Copied!' : 'Copy calibration report'}
            </button>
            <pre className="training-fail-dump">{failReport}</pre>
            <button type="button" className="chip" onClick={() => useVigilStore.getState().startTraining()}>
              Retry training
            </button>
          </>
        )}
      </aside>

      {/* Dummy workspace — one visible SAMPLE = real hit target */}
      <div className="training-stage">
        {step === 'move' && (
          <div className={`training-dropzone ${gestureMode === 'drag_panel' ? 'hot' : ''}`}>
            DROP ZONE
            <span>drag SAMPLE here</span>
          </div>
        )}
        {sampleOpen &&
          ['move', 'scroll', 'zoom_window', 'flick_zoom', 'two_hand', 'fist_close', 'close'].includes(
            step,
          ) && (
          <TrainingSamplePanel
            rows={DUMMY_ROWS}
            step={step}
            grabbed={gestureMode === 'drag_panel'}
          />
        )}
        <p className="training-legend">
          Glowing L/R dots = your fingers · pinch on what you see (SAMPLE is the real target)
        </p>
      </div>
    </div>
  )
}

function TrainingSamplePanel({
  rows,
  step,
  grabbed,
}: {
  rows: string[]
  step: string
  grabbed: boolean
}) {
  const panel = useVigilStore((s) => s.panels.tower)
  const hoverTarget = useVigilStore((s) => s.hoverTarget)
  if (!panel.open) return null
  const grabReady = hoverTarget === 'panel:tower' || hoverTarget === 'body:tower'
  return (
    <div
      className={`float-panel focused training-sample ${grabbed ? 'grabbed' : ''} ${grabReady ? 'grab-ready' : ''}`}
      data-panel-id="tower"
      style={{
        left: `${panel.x}%`,
        top: `${panel.y}%`,
        transform: `scale(${panel.scale})`,
        transformOrigin: 'top left',
      }}
    >
      <div className="panel-head training-grab-bar">
        <h2>SAMPLE — PINCH HERE TO MOVE</h2>
        <div className="ops">
          <span className="muted">{step === 'move' ? 'grab bar' : 'title'}</span>
        </div>
      </div>
      <div className="panel-body training-scroll-body">
        <p className="muted">
          {step === 'scroll'
            ? 'Pinch in this list and move your hand up/down — 48 rows to scroll.'
            : 'This window is the real target (what you see is what you grab).'}
        </p>
        {rows.map((r) => (
          <div className="list-row" key={r}>
            <div>{r}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
