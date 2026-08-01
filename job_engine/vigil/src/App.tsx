import { useEffect, useRef } from 'react'
import { VigilCanvas } from './scene/VigilCanvas'
import { StatusHud } from './hud/StatusHud'
import { FingerOverlay } from './hud/FingerOverlay'
import { WebcamPip } from './hud/WebcamPip'
import { ModuleDock } from './hud/ModuleDock'
import { PanelHost } from './panels/PanelHost'
import { TrainingScreen } from './training/TrainingScreen'
import { useHandTracking } from './gestures/useHandTracking'
import { useGestureOS } from './gestures/useGestureOS'
import { useUltronSocket } from './lib/ultronWs'
import { panelFromQuery, useVigilStore } from './store/vigilStore'

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const trainingActive = useVigilStore((s) => s.trainingActive)

  // Camera stays mounted — remounting the <video> killed hand tracking in Train
  const cameraOn = vigilMode || trainingActive
  useHandTracking(videoRef, cameraOn)
  useGestureOS()
  useUltronSocket()

  useEffect(() => {
    if (trainingActive) return
    const panel = panelFromQuery()
    if (panel) useVigilStore.getState().openPanel(panel)
    else useVigilStore.getState().openPanel('tower')
  }, [trainingActive])

  useEffect(() => {
    document.body.dataset.vigilMode = vigilMode ? 'on' : 'off'
  }, [vigilMode])

  return (
    <div
      className={`vigil-root ${trainingActive ? 'mode-vigil mode-training' : vigilMode ? 'mode-vigil' : 'mode-desktop'}`}
    >
      {trainingActive ? (
        <TrainingScreen />
      ) : (
        <>
          <VigilCanvas />
          <StatusHud />
          <ModuleDock />
          <PanelHost />
        </>
      )}

      {cameraOn && <FingerOverlay />}
      <div
        className={cameraOn ? 'webcam-wrap' : 'webcam-wrap hidden'}
        aria-hidden={!cameraOn}
      >
        <WebcamPip ref={videoRef} />
      </div>
    </div>
  )
}
