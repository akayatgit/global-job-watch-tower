import { useEffect, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { EnergyCore } from './EnergyCore'
import { NeuralCore } from './NeuralCore'
import { CityGlobe } from './CityGlobe'
import { Starfield } from './Starfield'
import { OrbitNodes } from './OrbitNodes'
import { CameraRig } from './CameraRig'
import { useVigilStore } from '../store/vigilStore'

function SceneBody() {
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  return (
    <>
      <Starfield />
      <EnergyCore />
      {sceneMode === 'graph' && <NeuralCore />}
      {sceneMode === 'city' && <CityGlobe />}
      {vigilMode && sceneMode === 'core' && <OrbitNodes />}
      <CameraRig />
      <EffectComposer multisampling={0}>
        <Bloom
          intensity={sceneMode === 'core' ? 0.55 : 0.7}
          luminanceThreshold={0.45}
          luminanceSmoothing={0.85}
          mipmapBlur
        />
      </EffectComposer>
    </>
  )
}

function resetView() {
  const st = useVigilStore.getState()
  st.setSceneZoom(0)
  st.setCanvasPan({ x: 0, y: 0 })
  st.setStatus('VIEW RESET · scroll to approach the orb')
}

export function VigilCanvas() {
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = wrap.current
    if (!el) return

    // Hard reset on load — escape any stuck whiteout from prior session
    resetView()

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const st = useVigilStore.getState()
      if (st.focusedPanel || st.trainingActive) return
      // Firefox often sends large pixel deltas — normalize
      let step = 0.06
      if (e.deltaMode === 1) step = 0.1 // line mode
      if (Math.abs(e.deltaY) > 80) step = 0.1
      const dir = e.deltaY > 0 ? -1 : 1
      const next = Math.max(0, Math.min(0.85, st.sceneZoom + dir * step))
      st.setSceneZoom(next)
      st.setStatus(
        dir > 0
          ? `APPROACH · ${Math.round(next * 100)}%`
          : `PULL BACK · ${Math.round(next * 100)}%`,
      )
    }

    const onKey = (e: KeyboardEvent) => {
      const st = useVigilStore.getState()
      if (st.focusedPanel || st.trainingActive) return
      if (e.key === 'Escape' || e.key === 'Home' || e.key === '0') {
        e.preventDefault()
        resetView()
      }
      if (e.key === '+' || e.key === '=') {
        e.preventDefault()
        st.setSceneZoom(st.sceneZoom + 0.08)
      }
      if (e.key === '-' || e.key === '_') {
        e.preventDefault()
        st.setSceneZoom(st.sceneZoom - 0.08)
      }
    }

    const onDbl = () => {
      const st = useVigilStore.getState()
      if (st.focusedPanel || st.trainingActive) return
      resetView()
    }

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('dblclick', onDbl)
    window.addEventListener('keydown', onKey)
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('dblclick', onDbl)
      window.removeEventListener('keydown', onKey)
    }
  }, [])

  return (
    <div className="vigil-canvas" ref={wrap}>
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [0, 0, 8.8], fov: 45 }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
        onPointerMissed={() => {
          const st = useVigilStore.getState()
          if (st.sceneMode === 'city' && st.cityFocus) {
            st.setCityFocus(null)
            st.setSceneZoom(0.15)
            st.setStatus('CITY · GLOBE')
          }
        }}
      >
        <color attach="background" args={['#050302']} />
        <ambientLight intensity={0.28} />
        <pointLight position={[4, 3, 4]} intensity={0.7} color="#ff5500" />
        <pointLight position={[-3, -2, 2]} intensity={0.35} color="#ffaa00" />
        <SceneBody />
      </Canvas>
    </div>
  )
}
