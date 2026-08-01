import { useEffect, useRef } from 'react'
import { VigilCanvas } from './scene/VigilCanvas'
import { StatusHud } from './hud/StatusHud'
import { FingerOverlay } from './hud/FingerOverlay'
import { WebcamPip } from './hud/WebcamPip'
import { ModuleDock } from './hud/ModuleDock'
import { PanelHost } from './panels/PanelHost'
import { TrainingSession } from './training/TrainingSession'
import { useHandTracking } from './gestures/useHandTracking'
import { useGestureOS } from './gestures/useGestureOS'
import { useUltronSocket } from './lib/ultronWs'
import { panelFromQuery, useVigilStore } from './store/vigilStore'

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const trainingActive = useVigilStore((s) => s.trainingActive)

  useHandTracking(videoRef)
  useGestureOS()
  useUltronSocket()

  useEffect(() => {
    const panel = panelFromQuery()
    if (panel) useVigilStore.getState().openPanel(panel)
    else useVigilStore.getState().openPanel('tower')
  }, [])

  useEffect(() => {
    document.body.dataset.vigilMode = vigilMode ? 'on' : 'off'
  }, [vigilMode])

  return (
    <div className={`vigil-root ${vigilMode ? 'mode-vigil' : 'mode-desktop'}${trainingActive ? ' mode-training' : ''}`}>
      <VigilCanvas />
      <StatusHud />
      {!trainingActive && <ModuleDock />}
      <PanelHost />
      <TrainingSession />
      {vigilMode && <FingerOverlay />}
      <div className={vigilMode ? 'webcam-wrap' : 'webcam-wrap hidden'} aria-hidden={!vigilMode}>
        <WebcamPip ref={videoRef} />
      </div>
    </div>
  )
}
