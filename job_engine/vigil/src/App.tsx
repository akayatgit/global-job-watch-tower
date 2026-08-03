import { useEffect, useRef } from 'react'
import { VigilCanvas } from './scene/VigilCanvas'
import { StatusHud } from './hud/StatusHud'
import { CampusFocusNav } from './hud/CampusFocusNav'
import { VigilCursor } from './hud/VigilCursor'
import { FingerOverlay } from './hud/FingerOverlay'
import { WebcamPip } from './hud/WebcamPip'
import { ModuleDock } from './hud/ModuleDock'
import { PanelHost } from './panels/PanelHost'
import { TrainingScreen } from './training/TrainingScreen'
import { useHandTracking } from './gestures/useHandTracking'
import { useGestureOS } from './gestures/useGestureOS'
import { api } from './lib/api'
import { useUltronSocket } from './lib/ultronWs'
import { panelFromQuery, useVigilStore } from './store/vigilStore'

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const railOpen = useVigilStore((s) => s.railOpen)
  const layerFocus = Boolean(focusedPanel) && !trainingActive

  // Camera stays mounted — remounting the <video> killed hand tracking in Train
  const cameraOn = vigilMode || trainingActive
  useHandTracking(videoRef, cameraOn)
  useGestureOS()
  useUltronSocket()

  useEffect(() => {
    api
      .sectors()
      .then((d) => {
        const opts = d?.sector_options || []
        if (opts.length) useVigilStore.getState().setSectorOptions(opts)
      })
      .catch(() => {})
    api
      .citySignals(7)
      .then((d) => {
        const opts = d?.city_options || []
        if (opts.length) useVigilStore.getState().setCityOptions(opts)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (trainingActive) return
    const st = useVigilStore.getState()
    st.restoreDashboard()
    const panel = panelFromQuery()
    if (panel && panel !== 'tower') st.openPanel(panel)
  }, [trainingActive])

  useEffect(() => {
    document.body.dataset.vigilMode = vigilMode ? 'on' : 'off'
    document.body.dataset.layerFocus = layerFocus ? 'on' : 'off'
    document.body.dataset.rail = railOpen ? 'open' : 'collapsed'
  }, [vigilMode, layerFocus, railOpen])

  return (
    <div
      className={`vigil-root ${trainingActive ? 'mode-vigil mode-training' : vigilMode ? 'mode-vigil' : 'mode-desktop'}${layerFocus ? ' layer-focus' : ''}${railOpen ? ' rail-open' : ' rail-collapsed'}`}
    >
      {trainingActive ? (
        <TrainingScreen />
      ) : (
        <>
          <ModuleDock />
          <div className="vigil-stage">
            <VigilCanvas />
            <StatusHud />
            <CampusFocusNav />
            <PanelHost />
          </div>
        </>
      )}

      {cameraOn && <FingerOverlay />}
      <div
        className={cameraOn ? 'webcam-wrap' : 'webcam-wrap hidden'}
        aria-hidden={!cameraOn}
      >
        <WebcamPip ref={videoRef} />
      </div>
      {/* Immersive glowing cursor — above UI, never captures clicks */}
      <VigilCursor />
    </div>
  )
}
