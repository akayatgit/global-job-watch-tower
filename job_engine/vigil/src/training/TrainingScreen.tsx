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

const STEPS = [
  { id: 'intro', title: 'Welcome', hint: 'This is a dummy training room — not the live tower.' },
  { id: 'show_hand', title: 'Show hand', hint: 'Raise your right hand until the amber R guide locks.' },
  { id: 'pinch', title: 'Pinch', hint: 'Pinch thumb + index 5 times (amber hand).' },
  { id: 'move', title: 'Move window', hint: 'Pinch the SAMPLE header and drag into the drop zone.' },
  { id: 'scroll', title: 'Scroll window', hint: 'Pinch inside the SAMPLE list and move hand up/down to scroll.' },
  { id: 'zoom_window', title: 'Zoom window', hint: 'Both hands pinch over SAMPLE — slowly apart/together (wait for lock).' },
  { id: 'two_hand', title: 'Two-hand core', hint: 'Both hands pinch over empty space (not the window) — slow apart.' },
  { id: 'close', title: 'Close', hint: 'Hold on the big CLOSE TARGET until 100%.' },
  { id: 'press', title: 'Confirm', hint: 'Hold on CONFIRM to save your calibration.' },
  { id: 'done', title: 'Saved', hint: 'Feel is stored. Exit back to the live tower.' },
  { id: 'fail', title: 'Needs help', hint: 'Copy the report below and paste it to Akay.' },
] as const

const DUMMY_ROWS = Array.from({ length: 24 }, (_, i) => `Sample row ${i + 1} — scroll practice line`)

export function TrainingScreen() {
  const step = useVigilStore((s) => s.trainingStep)
  const feedback = useVigilStore((s) => s.trainingFeedback)
  const failReport = useVigilStore((s) => s.trainingFailReport)
  const setStep = useVigilStore((s) => s.setTrainingStep)
  const setFeedback = useVigilStore((s) => s.setTrainingFeedback)
  const setFailReport = useVigilStore((s) => s.setTrainingFailReport)
  const stopTraining = useVigilStore((s) => s.stopTraining)
  const setCalibration = useVigilStore((s) => s.setCalibration)
  const calibration = useVigilStore((s) => s.calibration)
  const hands = useVigilStore((s) => s.hands)
  const pressProgress = useVigilStore((s) => s.pressProgress)
  const gestureMode = useVigilStore((s) => s.gestureMode)
  const grabTarget = useVigilStore((s) => s.grabTarget)

  const [pinchCount, setPinchCount] = useState(0)
  const [sampleOpen, setSampleOpen] = useState(true)
  const [samplePos, setSamplePos] = useState({ x: 18, y: 28 })
  const [sampleScale, setSampleScale] = useState(1)
  const [scrollOk, setScrollOk] = useState(false)
  const [zoomOk, setZoomOk] = useState(false)
  const [twoOk, setTwoOk] = useState(false)
  const [copied, setCopied] = useState(false)
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
    setFailReport(report)
    setFeedback(why)
    setStep('fail')
  }

  useEffect(() => {
    resetSamples()
    setPinchCount(0)
    setSampleOpen(true)
    setSamplePos({ x: 18, y: 28 })
    setSampleScale(1)
    setScrollOk(false)
    setZoomOk(false)
    setTwoOk(false)
    setStep('intro')
    setFeedback('Dummy training room — Begin when ready')
    stepStarted.current = performance.now()
  }, [setStep, setFeedback])

  useEffect(() => {
    stepStarted.current = performance.now()
  }, [step])

  // Drive dummy panel from real gesture mode during move/scroll/zoom
  useEffect(() => {
    if (step !== 'move' && step !== 'scroll' && step !== 'zoom_window') return
    const id = window.setInterval(() => {
      const st = useVigilStore.getState()
      // Hijack tower panel geometry for training drills visually via local state
      if (step === 'move' && st.grabTarget === 'tower') {
        const p = st.panels.tower
        setSamplePos({ x: p.x, y: p.y })
      }
      if (step === 'zoom_window' && st.gestureMode === 'zoom_panel') {
        setSampleScale(st.panels.tower?.scale || sampleScale)
      }
    }, 50)
    return () => clearInterval(id)
  }, [step, sampleScale])

  useEffect(() => {
    if (step === 'idle' || step === 'intro' || step === 'done' || step === 'fail') return
    let raf = 0
    const tick = () => {
      const st = useVigilStore.getState()
      const primary = st.hands.right || st.hands.left
      const idx = st.smoothIndex
      const now = performance.now()

      // Timeout per step (45s) → fail with dump
      if (now - stepStarted.current > 45000 && !['done', 'fail'].includes(step)) {
        failStep(`Timed out on step "${step}" after 45s`)
        return
      }

      if (primary) {
        if (primary.pinch) pushPinch(primary.pinchDist)
        else if (primary.pinchDist > 0) pushOpen(primary.pinchDist)
        if (lastPos.current) {
          const dt = (now - lastPos.current.t) / 1000
          if (dt > 0.01 && dt < 0.2) {
            pushSpeed(
              Math.hypot(idx.x - lastPos.current.x, idx.y - lastPos.current.y) / dt,
            )
          }
        }
        lastPos.current = { x: idx.x, y: idx.y, t: now }
        pushJitter(0.008)
      }

      if (step === 'show_hand') {
        if (primary?.index) {
          if (now - stepStarted.current > 1200) {
            setFeedback('Hand locked')
            setStep('pinch')
          } else {
            setFeedback(`Hold steady… ${Math.round(((now - stepStarted.current) / 1200) * 100)}%`)
          }
        } else {
          stepStarted.current = now
          setFeedback('Raise amber (R) hand into camera')
        }
      }

      if (step === 'pinch' && primary) {
        if (primary.pinch && !lastPinch.current) {
          setPinchCount((c) => {
            const n = c + 1
            setFeedback(n >= 5 ? 'Pinch OK' : `Pinch ${n}/5`)
            if (n >= 5) {
              // Open dummy via real tower panel for gesture OS hit-testing
              st.openPanel('tower')
              st.movePanel('tower', 18, 28)
              st.scalePanel('tower', 1)
              setSampleOpen(true)
              window.setTimeout(() => {
                setStep('move')
                setFeedback('Pinch SAMPLE header → drag to drop zone')
              }, 300)
            }
            return n
          })
        }
        lastPinch.current = primary.pinch
      }

      if (step === 'move') {
        const p = st.panels.tower
        setSamplePos({ x: p.x, y: p.y })
        if (p.open && p.x > 55 && p.x < 80 && p.y > 18 && p.y < 55 && !st.grabTarget) {
          setFeedback('Move OK — next: scroll')
          const body = document.querySelector('[data-panel-id="tower"] .panel-body') as HTMLElement | null
          scrollStart.current = body?.scrollTop || 0
          setStep('scroll')
        } else if (grabTarget) setFeedback('Dragging… drop in the zone')
      }

      if (step === 'scroll') {
        const body = document.querySelector('[data-panel-id="tower"] .panel-body') as HTMLElement | null
        const delta = Math.abs((body?.scrollTop || 0) - scrollStart.current)
        if (st.gestureMode === 'scroll_panel') {
          setFeedback(`Scrolling… ${Math.round(delta)}px (need 80+)`)
        }
        if (delta > 80 && !scrollOk) {
          setScrollOk(true)
          zoomBase.current = st.panels.tower.scale
          setFeedback('Scroll OK — both-hand zoom on the window')
          setStep('zoom_window')
        }
      }

      if (step === 'zoom_window') {
        const scale = st.panels.tower.scale
        setSampleScale(scale)
        if (st.gestureMode === 'zoom_panel') {
          setFeedback(`Zooming window… scale ${scale.toFixed(2)}`)
        } else {
          setFeedback('Both hands pinch OVER the sample window — hold 0.3s then slowly move apart')
        }
        if (Math.abs(scale - zoomBase.current) > 0.12 && !zoomOk) {
          setZoomOk(true)
          twoBase.current = st.coreScale
          st.movePanel('tower', 8, 55)
          setFeedback('Window zoom OK — two-hand over EMPTY space for core')
          setStep('two_hand')
        }
      }

      if (step === 'two_hand') {
        if (st.gestureMode === 'core_zoom') {
          setFeedback(`Core zoom… ${st.coreScale.toFixed(2)}`)
        } else if (st.hands.twoHandPinch) {
          setFeedback('Locked… keep both pinched, slowly change distance')
        } else {
          setFeedback('Pinch BOTH hands in empty space (not on the window)')
        }
        if (Math.abs(st.coreScale - twoBase.current) > 0.15 && !twoOk) {
          setTwoOk(true)
          setFeedback('Two-hand OK — close target next')
          setStep('close')
        }
      }

      if (step === 'close') {
        if (st.pressProgress > 0) {
          if (!dwellStart.current) dwellStart.current = now
          setFeedback(`Close… ${Math.round(st.pressProgress * 100)}%`)
        } else setFeedback('Hold on CLOSE TARGET')
      }

      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [step, setStep, setFeedback, grabTarget, scrollOk, zoomOk, twoOk, calibration, gestureMode, hands])

  const meta = STEPS.find((s) => s.id === step) || STEPS[0]

  const finish = () => {
    const next = computeCalibration(getSamples(), calibration)
    setCalibration(next)
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
        <p className="muted">
          Mode: {gestureMode} · L:{hands.left ? 'on' : '—'} R:{hands.right ? 'on' : '—'} · sessions{' '}
          {calibration.sessionsCompleted}
        </p>

        {step === 'intro' && (
          <button
            type="button"
            className="chip active train-hit"
            data-gesture-action="train-begin"
            onClick={() => {
              resetSamples()
              setStep('show_hand')
              setFeedback('Show amber (R) hand')
            }}
          >
            Begin
          </button>
        )}

        {step === 'pinch' && (
          <div className="training-meter">
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(pinchCount / 5) * 100}%` }} />
            </div>
            <span>{pinchCount}/5</span>
          </div>
        )}

        {step === 'close' && (
          <button
            type="button"
            className="training-close-target train-hit"
            data-gesture-action="train-close"
            onClick={() => {
              pushDwell(dwellStart.current ? performance.now() - dwellStart.current : calibration.dwellMs)
              useVigilStore.getState().closePanel('tower')
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

      {/* Dummy workspace */}
      <div className="training-stage">
        {(step === 'move' || step === 'scroll' || step === 'zoom_window') && (
          <div className="training-dropzone">DROP ZONE</div>
        )}
        {sampleOpen && ['move', 'scroll', 'zoom_window', 'two_hand', 'close'].includes(step) && (
          <div
            className="float-panel focused training-dummy-visual"
            style={{
              left: `${samplePos.x}%`,
              top: `${samplePos.y}%`,
              transform: `scale(${sampleScale})`,
              transformOrigin: 'top left',
              pointerEvents: 'none',
            }}
          >
            <div className="panel-head">
              <h2>SAMPLE WIDGET</h2>
              <div className="ops"><span className="muted">visual</span></div>
            </div>
            <div className="panel-body">
              <p className="muted">Real hit-target is the live panel under this (synced).</p>
              {DUMMY_ROWS.slice(0, 6).map((r) => (
                <div className="list-row" key={r}><div>{r}</div></div>
              ))}
            </div>
          </div>
        )}
        <p className="training-legend">
          R amber = primary · L cyan = second hand · purple line = two-hand stretch
        </p>
      </div>

      {/* Hidden-but-real panel for gesture hit testing during drills */}
      <div className="training-hit-host" aria-hidden>
        <TrainingHitPanel rows={DUMMY_ROWS} />
      </div>
    </div>
  )
}

function TrainingHitPanel({ rows }: { rows: string[] }) {
  const panel = useVigilStore((s) => s.panels.tower)
  const closePanel = useVigilStore((s) => s.closePanel)
  if (!panel.open) return null
  return (
    <div
      className="float-panel focused"
      data-panel-id="tower"
      style={{
        left: `${panel.x}%`,
        top: `${panel.y}%`,
        zIndex: 5,
        transform: `scale(${panel.scale})`,
        transformOrigin: 'top left',
        opacity: 0.12,
      }}
    >
      <div className="panel-head">
        <h2>SAMPLE</h2>
        <div className="ops">
          <button type="button" data-gesture-action="close-tower" onClick={() => closePanel('tower')}>
            Close
          </button>
        </div>
      </div>
      <div className="panel-body" style={{ maxHeight: 220 }}>
        {rows.map((r) => (
          <div className="list-row" key={r}><div>{r}</div></div>
        ))}
      </div>
    </div>
  )
}
