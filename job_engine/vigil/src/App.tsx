import { useEffect, useRef } from 'react'
import { VigilCanvas } from './scene/VigilCanvas'
import { StatusHud } from './hud/StatusHud'
import { FingerOverlay } from './hud/FingerOverlay'
import { WebcamPip } from './hud/WebcamPip'
import { PanelHost } from './panels/PanelHost'
import { useHandTracking } from './gestures/useHandTracking'
import { useGestureOS } from './gestures/useGestureOS'
import { useUltronSocket } from './lib/ultronWs'
import { panelFromQuery, useVigilStore } from './store/vigilStore'

export default function App() {
  const videoRef = useRef<HTMLVideoElement>(null)
  useHandTracking(videoRef)
  useGestureOS()
  useUltronSocket()

  useEffect(() => {
    const panel = panelFromQuery()
    if (panel) useVigilStore.getState().openPanel(panel)
    else useVigilStore.getState().openPanel('tower')
  }, [])

  // Mouse fallback when camera unavailable — still guides the index reticle
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      const st = useVigilStore.getState()
      const hasHand = Boolean(st.hands.right || st.hands.left)
      if (hasHand) return
      useVigilStore.setState({
        smoothIndex: {
          x: e.clientX / window.innerWidth,
          y: e.clientY / window.innerHeight,
        },
        smoothThumb: {
          x: e.clientX / window.innerWidth - 0.03,
          y: e.clientY / window.innerHeight + 0.04,
        },
      })
    }
    const onDown = (e: MouseEvent) => {
      const st = useVigilStore.getState()
      if (st.hands.right || st.hands.left) return
      // Simulate pinch while holding Alt
      if (e.altKey) {
        useVigilStore.setState({
          hands: {
            left: null,
            right: {
              index: st.smoothIndex,
              thumb: st.smoothThumb,
              pinch: true,
              pinchDist: 0.02,
              centroid: st.smoothIndex,
            },
            twoHandPinch: false,
            twoHandDist: 0,
          },
        })
      }
    }
    const onUp = () => {
      const st = useVigilStore.getState()
      if (st.hands.right || st.hands.left) {
        const real = st.hands.right?.pinchDist !== 0.02
        if (!real && st.hands.right) {
          useVigilStore.setState({
            hands: { left: null, right: null, twoHandPinch: false, twoHandDist: 0 },
          })
        }
      }
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  return (
    <div className="vigil-root">
      <VigilCanvas />
      <StatusHud />
      <PanelHost />
      <FingerOverlay />
      <WebcamPip ref={videoRef} />
    </div>
  )
}
