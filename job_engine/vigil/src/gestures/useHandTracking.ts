import { useEffect, useRef } from 'react'
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision'
import { useVigilStore, type HandSample, type HandsState } from '../store/vigilStore'
import { lerp } from '../lib/lerp'
import { logTrain } from '../training/sessionLog'

const WASM =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm'
const MODEL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'

function sampleFromLandmarks(
  lms: { x: number; y: number; z: number }[],
  pinchThreshold: number,
): HandSample {
  const thumb = lms[4]
  const index = lms[8]
  const pinchDist = Math.hypot(thumb.x - index.x, thumb.y - index.y)
  return {
    index: { x: 1 - index.x, y: index.y },
    thumb: { x: 1 - thumb.x, y: thumb.y },
    pinch: pinchDist < pinchThreshold,
    pinchDist,
    centroid: {
      x: 1 - (thumb.x + index.x) / 2,
      y: (thumb.y + index.y) / 2,
    },
  }
}

async function waitForVideo(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  active: () => boolean,
  tries = 40,
): Promise<HTMLVideoElement | null> {
  for (let i = 0; i < tries; i++) {
    if (!active()) return null
    const v = videoRef.current
    if (v) return v
    await new Promise((r) => setTimeout(r, 50))
  }
  return videoRef.current
}

export function useHandTracking(
  videoRef: React.RefObject<HTMLVideoElement | null>,
  cameraOn: boolean,
) {
  const setHands = useVigilStore((s) => s.setHands)
  const landmarkerRef = useRef<HandLandmarker | null>(null)
  const rafRef = useRef(0)
  const sawHand = useRef(false)

  useEffect(() => {
    if (!cameraOn) {
      setHands({ left: null, right: null, twoHandPinch: false, twoHandDist: 0 })
      useVigilStore.setState({ leftHandVisible: false })
      return
    }

    let active = true
    let stream: MediaStream | null = null
    sawHand.current = false

    const boot = async () => {
      try {
        logTrain('camera_boot_start')
        const vision = await FilesetResolver.forVisionTasks(WASM)
        if (!active) return
        landmarkerRef.current = await HandLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL, delegate: 'GPU' },
          runningMode: 'VIDEO',
          numHands: 2,
          minHandDetectionConfidence: 0.5,
          minHandPresenceConfidence: 0.5,
          minTrackingConfidence: 0.5,
        })
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: 640, height: 480 },
          audio: false,
        })
        const video = await waitForVideo(videoRef, () => active)
        if (!video || !active) {
          logTrain('camera_boot_fail', { reason: 'no_video_element' })
          useVigilStore.getState().setStatus('CAMERA ELEMENT MISSING — RETRY TRAIN')
          return
        }
        video.srcObject = stream
        await video.play()
        logTrain('camera_boot_ok', {
          w: video.videoWidth,
          h: video.videoHeight,
          readyState: video.readyState,
        })
        useVigilStore.getState().setStatus('CAMERA LIVE — SHOW YOUR HAND')
        loop()
      } catch (err) {
        console.warn('VIGIL hand tracking unavailable', err)
        logTrain('camera_boot_fail', {
          reason: err instanceof Error ? err.message : String(err),
        })
        useVigilStore.getState().setStatus('CAMERA OFFLINE — ALLOW WEBCAM ACCESS')
      }
    }

    const loop = () => {
      if (!active) return
      const video = videoRef.current
      const lm = landmarkerRef.current
      const cal = useVigilStore.getState().calibration
      if (video && lm && video.readyState >= 2) {
        const result = lm.detectForVideo(video, performance.now())
        const hands: HandsState = {
          left: null,
          right: null,
          twoHandPinch: false,
          twoHandDist: 0,
        }
        result.landmarks.forEach((landmarks, i) => {
          const handed = result.handednesses?.[i]?.[0]?.categoryName
          const sample = sampleFromLandmarks(landmarks, cal.pinchThreshold)
          if (handed === 'Left') hands.right = sample
          else if (handed === 'Right') hands.left = sample
          else hands.right = hands.right || sample
        })
        if (!hands.right && !hands.left && result.landmarks[0]) {
          hands.right = sampleFromLandmarks(result.landmarks[0], cal.pinchThreshold)
        }
        if (hands.left?.pinch && hands.right?.pinch && hands.left.centroid && hands.right.centroid) {
          hands.twoHandPinch = true
          hands.twoHandDist = Math.hypot(
            hands.left.centroid.x - hands.right.centroid.x,
            hands.left.centroid.y - hands.right.centroid.y,
          )
        }
        setHands(hands)

        const anyHand = Boolean(hands.left || hands.right)
        if (anyHand && !sawHand.current) {
          sawHand.current = true
          logTrain('hand_first_seen', {
            left: Boolean(hands.left),
            right: Boolean(hands.right),
          })
        }
        if (!anyHand && sawHand.current) {
          sawHand.current = false
          logTrain('hand_lost')
        }

        const factor = cal.lerpFactor
        const st = useVigilStore.getState()
        const patch: Record<string, unknown> = { leftHandVisible: Boolean(hands.left) }

        if (hands.right?.index) {
          patch.smoothIndex = {
            x: lerp(st.smoothIndex.x, hands.right.index.x, factor),
            y: lerp(st.smoothIndex.y, hands.right.index.y, factor),
          }
        }
        if (hands.right?.thumb) {
          const s = useVigilStore.getState()
          patch.smoothThumb = {
            x: lerp(s.smoothThumb.x, hands.right.thumb.x, factor),
            y: lerp(s.smoothThumb.y, hands.right.thumb.y, factor),
          }
        }
        if (hands.left?.index) {
          const s = useVigilStore.getState()
          patch.smoothLeftIndex = {
            x: lerp(s.smoothLeftIndex.x, hands.left.index.x, factor),
            y: lerp(s.smoothLeftIndex.y, hands.left.index.y, factor),
          }
        }
        if (hands.left?.thumb) {
          const s = useVigilStore.getState()
          patch.smoothLeftThumb = {
            x: lerp(s.smoothLeftThumb.x, hands.left.thumb.x, factor),
            y: lerp(s.smoothLeftThumb.y, hands.left.thumb.y, factor),
          }
        }
        if (!hands.right && hands.left?.index) {
          const s = useVigilStore.getState()
          patch.smoothIndex = {
            x: lerp(s.smoothIndex.x, hands.left.index.x, factor),
            y: lerp(s.smoothIndex.y, hands.left.index.y, factor),
          }
          if (hands.left.thumb) {
            patch.smoothThumb = {
              x: lerp(s.smoothThumb.x, hands.left.thumb.x, factor),
              y: lerp(s.smoothThumb.y, hands.left.thumb.y, factor),
            }
          }
        }
        useVigilStore.setState(patch)
      }
      rafRef.current = requestAnimationFrame(loop)
    }

    boot()
    return () => {
      active = false
      cancelAnimationFrame(rafRef.current)
      stream?.getTracks().forEach((t) => t.stop())
      landmarkerRef.current?.close()
      landmarkerRef.current = null
      const video = videoRef.current
      if (video) video.srcObject = null
      logTrain('camera_teardown')
    }
  }, [setHands, videoRef, cameraOn])
}
