import { useEffect, useRef } from 'react'
import { FilesetResolver, HandLandmarker } from '@mediapipe/tasks-vision'
import { useVigilStore, type HandSample, type HandsState } from '../store/vigilStore'
import { lerp } from '../lib/lerp'

const PINCH_THRESHOLD = 0.04
const WASM =
  'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.18/wasm'
const MODEL =
  'https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task'

function sampleFromLandmarks(lms: { x: number; y: number; z: number }[]): HandSample {
  const thumb = lms[4]
  const index = lms[8]
  const pinchDist = Math.hypot(thumb.x - index.x, thumb.y - index.y)
  // Mirror X so movement matches screen (selfie view)
  return {
    index: { x: 1 - index.x, y: index.y },
    thumb: { x: 1 - thumb.x, y: thumb.y },
    pinch: pinchDist < PINCH_THRESHOLD,
    pinchDist,
    centroid: {
      x: 1 - (thumb.x + index.x) / 2,
      y: (thumb.y + index.y) / 2,
    },
  }
}

export function useHandTracking(videoRef: React.RefObject<HTMLVideoElement | null>) {
  const setHands = useVigilStore((s) => s.setHands)
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const landmarkerRef = useRef<HandLandmarker | null>(null)
  const rafRef = useRef(0)

  useEffect(() => {
    if (!vigilMode) {
      setHands({ left: null, right: null, twoHandPinch: false, twoHandDist: 0 })
      return
    }

    let active = true
    let stream: MediaStream | null = null

    const boot = async () => {
      try {
        const vision = await FilesetResolver.forVisionTasks(WASM)
        if (!active) return
        landmarkerRef.current = await HandLandmarker.createFromOptions(vision, {
          baseOptions: { modelAssetPath: MODEL, delegate: 'GPU' },
          runningMode: 'VIDEO',
          numHands: 2,
          minHandDetectionConfidence: 0.55,
          minHandPresenceConfidence: 0.5,
          minTrackingConfidence: 0.5,
        })
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: 640, height: 480 },
          audio: false,
        })
        const video = videoRef.current
        if (!video || !active) return
        video.srcObject = stream
        await video.play()
        loop()
      } catch (err) {
        console.warn('VIGIL hand tracking unavailable', err)
        useVigilStore.getState().setStatus('CAMERA OFFLINE — TURN VIGIL MODE OFF FOR MOUSE')
      }
    }

    const loop = () => {
      if (!active) return
      if (!useVigilStore.getState().vigilMode) {
        rafRef.current = requestAnimationFrame(loop)
        return
      }
      const video = videoRef.current
      const lm = landmarkerRef.current
      if (video && lm && video.readyState >= 2) {
        const result = lm.detectForVideo(video, performance.now())
        const hands: HandsState = {
          left: null,
          right: null,
          twoHandPinch: false,
          twoHandDist: 0,
        }
        const samples: HandSample[] = []
        result.landmarks.forEach((landmarks, i) => {
          const handed = result.handednesses?.[i]?.[0]?.categoryName
          const sample = sampleFromLandmarks(landmarks)
          samples.push(sample)
          if (handed === 'Left') hands.left = sample
          else hands.right = sample
        })
        if (samples.length === 1) {
          hands.right = samples[0]
        }
        if (samples.length >= 2 && samples[0].pinch && samples[1].pinch) {
          const a = samples[0].centroid!
          const b = samples[1].centroid!
          hands.twoHandPinch = true
          hands.twoHandDist = Math.hypot(a.x - b.x, a.y - b.y)
        }
        setHands(hands)

        const primary = hands.right?.index || hands.left?.index
        const thumb = hands.right?.thumb || hands.left?.thumb
        const st = useVigilStore.getState()
        if (primary) {
          useVigilStore.setState({
            smoothIndex: {
              x: lerp(st.smoothIndex.x, primary.x, 0.15),
              y: lerp(st.smoothIndex.y, primary.y, 0.15),
            },
          })
        }
        if (thumb) {
          const s2 = useVigilStore.getState()
          useVigilStore.setState({
            smoothThumb: {
              x: lerp(s2.smoothThumb.x, thumb.x, 0.15),
              y: lerp(s2.smoothThumb.y, thumb.y, 0.15),
            },
          })
        }
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
    }
  }, [setHands, videoRef, vigilMode])
}
