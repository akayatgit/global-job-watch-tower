import { useEffect, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { EnergyCore } from './EnergyCore'
import { NeuralCore } from './NeuralCore'
import { CityGlobe } from './CityGlobe'
import { Starfield } from './Starfield'
import { OrbitNodes } from './OrbitNodes'
import { SceneControls } from './SceneControls'
import { useVigilStore } from '../store/vigilStore'

function SceneBody() {
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityFocus = useVigilStore((s) => s.cityFocus)
  const nightDistrict = sceneMode === 'city' && Boolean(cityFocus)
  return (
    <>
      {!nightDistrict && <Starfield />}
      {!nightDistrict && <EnergyCore />}
      {sceneMode === 'graph' && <NeuralCore />}
      {sceneMode === 'city' && <CityGlobe />}
      {vigilMode && sceneMode === 'core' && <OrbitNodes />}
      <SceneControls />
      {nightDistrict && <color attach="background" args={['#1a0830']} />}
      {nightDistrict && <fog attach="fog" args={['#3d1830', 8, 26]} />}
      <EffectComposer multisampling={0}>
        <Bloom
          intensity={
            nightDistrict
              ? 0.55
              : sceneMode === 'core'
                ? 0.45
                : sceneMode === 'graph'
                  ? 0.22
                  : 0.55
          }
          luminanceThreshold={nightDistrict ? 0.35 : sceneMode === 'graph' ? 0.72 : 0.5}
          luminanceSmoothing={0.88}
          mipmapBlur
        />
      </EffectComposer>
    </>
  )
}

export function VigilCanvas() {
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const st = useVigilStore.getState()
    st.resetView()

    // Only block browser page-zoom; OrbitControls owns the actual dolly
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
    }
    const onKey = (e: KeyboardEvent) => {
      const s = useVigilStore.getState()
      if (s.focusedPanel || s.trainingActive) return
      if (e.key === 'Escape' || e.key === 'Home' || e.key === '0') {
        e.preventDefault()
        s.setGraphFocusId(null)
        s.resetView()
      }
      if (e.key === ' ' || e.code === 'Space') {
        e.preventDefault()
        s.toggleSceneSpin()
      }
    }
    const onDbl = () => {
      const s = useVigilStore.getState()
      if (s.focusedPanel || s.trainingActive) return
      s.resetView()
    }
    // Stop context menu so right-drag pan feels like Figma
    const onCtx = (e: Event) => e.preventDefault()

    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('dblclick', onDbl)
    el.addEventListener('contextmenu', onCtx)
    window.addEventListener('keydown', onKey)
    return () => {
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('dblclick', onDbl)
      el.removeEventListener('contextmenu', onCtx)
      window.removeEventListener('keydown', onKey)
    }
  }, [])

  return (
    <div className="vigil-canvas" ref={wrap}>
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [0, 0.6, 7.2], fov: 45 }}
        shadows
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
        onPointerMissed={() => {
          const st = useVigilStore.getState()
          if (st.sceneMode === 'graph' && st.graphFocusId) {
            st.setGraphFocusId(null)
            st.clearCameraFocus()
            st.setStatus('GRAPH · global view')
            return
          }
          // City campus: empty click may clear tower focus — never leave immersive
          if (st.sceneMode === 'city' && st.cityFocus) {
            if (st.selectFocusId?.startsWith('company:')) {
              st.clearCameraFocus()
              st.setStatus('CAMPUS · use exit to return to globe')
            }
          }
        }}
      >
        <color attach="background" args={['#050302']} />
        <ambientLight intensity={0.28} />
        <pointLight position={[4, 3, 4]} intensity={0.65} color="#ff5500" />
        <pointLight position={[-3, -2, 2]} intensity={0.3} color="#ffaa00" />
        <SceneBody />
      </Canvas>
    </div>
  )
}
