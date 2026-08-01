import { useEffect, useRef, useState } from 'react'
import { useVigilStore } from '../store/vigilStore'
import { computeCalibration } from './calibration'
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
  { id: 'intro', title: '1 · Welcome', hint: 'We will teach VIGIL your hand speed and pinch.' },
  { id: 'show_hand', title: '2 · Show your hand', hint: 'Raise one hand so the amber guide follows your index finger.' },
  { id: 'pinch', title: '3 · Pinch', hint: 'Pinch thumb + index 5 times. Hold each pinch briefly.' },
  { id: 'move', title: '4 · Move a widget', hint: 'Pinch the TRAIN panel header and drag it into the glowing drop zone.' },
  { id: 'close', title: '5 · Close', hint: 'Point at the big CLOSE TARGET and hold until 100%. The ring stays sticky — small shakes are OK.' },
  { id: 'press', title: '6 · Press a chip', hint: 'Point at CONFIRM and hold until it lights up.' },
  { id: 'done', title: '7 · Calibrated', hint: 'Your feel is saved. Keep training daily to refine.' },
] as const

export function TrainingSession() {
  const active = useVigilStore((s) => s.trainingActive)
  const step = useVigilStore((s) => s.trainingStep)
  const feedback = useVigilStore((s) => s.trainingFeedback)
  const setStep = useVigilStore((s) => s.setTrainingStep)
  const setFeedback = useVigilStore((s) => s.setTrainingFeedback)
  const stopTraining = useVigilStore((s) => s.stopTraining)
  const setCalibration = useVigilStore((s) => s.setCalibration)
  const calibration = useVigilStore((s) => s.calibration)
  const hands = useVigilStore((s) => s.hands)
  const grabTarget = useVigilStore((s) => s.grabTarget)
  const pressProgress = useVigilStore((s) => s.pressProgress)
  const panels = useVigilStore((s) => s.panels)
  const openPanel = useVigilStore((s) => s.openPanel)
  const closePanel = useVigilStore((s) => s.closePanel)
  const movePanel = useVigilStore((s) => s.movePanel)

  const [pinchCount, setPinchCount] = useState(0)
  const [, setHandHold] = useState(0)
  const [movedOk, setMovedOk] = useState(false)
  const [closedOk, setClosedOk] = useState(false)
  const [pressedOk, setPressedOk] = useState(false)
  const lastPinch = useRef(false)
  const lastPos = useRef<{ x: number; y: number; t: number } | null>(null)
  const jitterBuf = useRef<{ x: number; y: number }[]>([])
  const dwellStart = useRef<number | null>(null)

  useEffect(() => {
    if (!active) return
    resetSamples()
    setPinchCount(0)
    setHandHold(0)
    setMovedOk(false)
    setClosedOk(false)
    setPressedOk(false)
    setStep('intro')
    setFeedback('Ready when you are — click Begin, or dwell on Begin with your hand.')
  }, [active, setStep, setFeedback])

  // Continuous sampling + step automation
  useEffect(() => {
    if (!active || step === 'idle' || step === 'intro' || step === 'done') return
    let raf = 0
    const tick = () => {
      const st = useVigilStore.getState()
      const primary = st.hands.right || st.hands.left
      const idx = st.smoothIndex
      const now = performance.now()

      if (primary) {
        if (primary.pinch) pushPinch(primary.pinchDist)
        else if (primary.pinchDist > 0) pushOpen(primary.pinchDist)

        if (lastPos.current) {
          const dt = (now - lastPos.current.t) / 1000
          if (dt > 0.01 && dt < 0.2) {
            const dist = Math.hypot(idx.x - lastPos.current.x, idx.y - lastPos.current.y)
            pushSpeed(dist / dt)
          }
        }
        lastPos.current = { x: idx.x, y: idx.y, t: now }
        jitterBuf.current.push({ x: idx.x, y: idx.y })
        if (jitterBuf.current.length > 20) {
          const buf = jitterBuf.current
          const mx = buf.reduce((a, p) => a + p.x, 0) / buf.length
          const my = buf.reduce((a, p) => a + p.y, 0) / buf.length
          const j =
            buf.reduce((a, p) => a + Math.hypot(p.x - mx, p.y - my), 0) / buf.length
          pushJitter(j)
          jitterBuf.current = []
        }
      }

      if (step === 'show_hand') {
        if (primary?.index) {
          setHandHold((h) => {
            const next = h + 1
            if (next >= 90) {
              setFeedback('Hand locked — great. Next: pinch.')
              setStep('pinch')
              return 0
            }
            setFeedback(`Hold steady… ${Math.min(100, Math.round((next / 90) * 100))}%`)
            return next
          })
        } else {
          setHandHold(0)
          setFeedback('Raise your hand into the camera frame')
        }
      }

      if (step === 'pinch' && primary) {
        if (primary.pinch && !lastPinch.current) {
          setPinchCount((c) => {
            const n = c + 1
            setFeedback(n >= 5 ? 'Pinch mastered!' : `Pinch ${n} / 5 — release and pinch again`)
            if (n >= 5) {
              window.setTimeout(() => {
                openPanel('tower')
                movePanel('tower', 12, 28)
                setStep('move')
                setFeedback('Pinch the TRAIN / TOWER panel header and drag into the drop zone')
              }, 500)
            }
            return n
          })
        }
        lastPinch.current = primary.pinch
      }

      if (step === 'move') {
        const p = st.panels.tower
        const inZone = p.open && p.x > 55 && p.x < 78 && p.y > 20 && p.y < 55
        if (inZone && !st.grabTarget) {
          setMovedOk(true)
          setFeedback('Drop accepted — now close the panel')
          setStep('close')
        } else if (st.grabTarget === 'tower') {
          setFeedback('Keep pinching — drag toward the glowing zone on the right')
        }
      }

      if (step === 'close') {
        if (closedOk) {
          /* wait for press step */
        } else if (st.pressProgress > 0) {
          if (!dwellStart.current) dwellStart.current = now
          setFeedback(`Hold on CLOSE TARGET… ${Math.round(st.pressProgress * 100)}% — shakes OK`)
        } else {
          dwellStart.current = null
          setFeedback('Point the amber guide at the big CLOSE TARGET')
        }
      }

      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [active, step, setStep, setFeedback, openPanel, movePanel, closedOk])

  if (!active) return null

  const meta = STEPS.find((s) => s.id === step) || STEPS[0]
  const sessionN = calibration.sessionsCompleted

  const finish = () => {
    const next = computeCalibration(getSamples(), calibration)
    setCalibration(next)
    setStep('done')
    setFeedback(
      `Saved · pinch ${next.pinchThreshold.toFixed(3)} · dwell ${next.dwellMs}ms · session #${next.sessionsCompleted}`,
    )
  }

  const begin = () => {
    resetSamples()
    setStep('show_hand')
    setFeedback('Raise your hand — follow the amber guide')
  }

  return (
    <div className="training-layer interactive">
      <div className="training-card">
        <div className="training-head">
          <h2>TRAINING GROUND</h2>
          <span className="muted">Session history: {sessionN}</span>
          <button type="button" className="chip" onClick={stopTraining}>
            Exit
          </button>
        </div>
        <h3>{meta.title}</h3>
        <p className="training-hint">{meta.hint}</p>
        <p className="training-feedback">{feedback}</p>

        {step === 'intro' && (
          <div className="chip-row">
            <button type="button" className="chip active" data-gesture-action="train-begin" onClick={begin}>
              Begin
            </button>
          </div>
        )}

        {step === 'pinch' && (
          <div className="training-meter">
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${(pinchCount / 5) * 100}%` }} />
            </div>
            <span>{pinchCount} / 5 pinches</span>
          </div>
        )}

        {step === 'move' && (
          <p className="muted">
            Grabbed: {grabTarget || '—'} · panel x={panels.tower?.x.toFixed(0)}%
            {movedOk ? ' · zone OK' : ''}
          </p>
        )}

        {step === 'close' && (
          <>
            <p className="muted">Press progress: {Math.round(pressProgress * 100)}%</p>
            <button
              type="button"
              className="training-close-target"
              data-gesture-action="train-close"
              onClick={() => {
                const held = dwellStart.current
                  ? performance.now() - dwellStart.current
                  : calibration.dwellMs
                pushDwell(held)
                closePanel('tower')
                setClosedOk(true)
                setFeedback('Closed — last step: press CONFIRM')
                setStep('press')
              }}
            >
              CLOSE TARGET
              <span>Hold the amber ring here</span>
            </button>
          </>
        )}

        {step === 'press' && (
          <div className="chip-row">
            <button
              type="button"
              className={`chip ${pressedOk ? 'active' : ''}`}
              data-gesture-action="train-confirm"
              onClick={() => {
                if (dwellStart.current) pushDwell(performance.now() - dwellStart.current)
                else pushDwell(calibration.dwellMs)
                setPressedOk(true)
                finish()
              }}
            >
              Confirm
            </button>
          </div>
        )}

        {step === 'done' && (
          <div className="chip-row">
            <button type="button" className="chip active" onClick={stopTraining}>
              Use VIGIL
            </button>
            <button
              type="button"
              className="chip"
              onClick={() => {
                resetSamples()
                setPinchCount(0)
                setMovedOk(false)
                setClosedOk(false)
                setPressedOk(false)
                setStep('show_hand')
                setFeedback('Another round — raise your hand')
              }}
            >
              Train again
            </button>
          </div>
        )}

        <div className="training-cal muted">
          Live feel: pinch &lt; {calibration.pinchThreshold.toFixed(3)} · dwell{' '}
          {calibration.dwellMs}ms · lerp {calibration.lerpFactor.toFixed(2)}
          {hands.right || hands.left ? ' · hand seen' : ' · no hand'}
        </div>
      </div>

      {step === 'move' && <div className="training-dropzone">DROP ZONE</div>}

      {(step === 'move' || step === 'close') && (
        <div className="training-sample-label">Sample widget = Tower panel (TRAIN)</div>
      )}
    </div>
  )
}
