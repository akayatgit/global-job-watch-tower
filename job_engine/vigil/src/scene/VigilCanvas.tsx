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
          intensity={sceneMode === 'core' ? 1.45 : 1.05}
          luminanceThreshold={0.22}
          luminanceSmoothing={0.75}
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
    const onWheel = (e: WheelEvent) => {
      // Capture zoom for the 3D orb — never zoom the HTML page
      e.preventDefault()
      const st = useVigilStore.getState()
      if (st.focusedPanel || st.trainingActive) return
      const delta = e.deltaY > 0 ? -0.055 : 0.055
      st.setSceneZoom(st.sceneZoom + delta)
      if (st.sceneMode === 'core' && st.sceneZoom > 0.55) {
        st.setStatus('INSIDE SINGULARITY · switch to Graph or City')
      }
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [])

  return (
    <div className="vigil-canvas" ref={wrap}>
      <Canvas
        dpr={[1, 1.5]}
        camera={{ position: [0, 0, 8.5], fov: 45 }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
        onPointerMissed={() => {
          const st = useVigilStore.getState()
          if (st.sceneMode === 'city' && st.cityFocus) {
            st.setCityFocus(null)
            st.setSceneZoom(0.25)
            st.setStatus('CITY · GLOBE')
          }
        }}
      >
        <color attach="background" args={['#050302']} />
        <ambientLight intensity={0.35} />
        <pointLight position={[4, 3, 4]} intensity={1.2} color="#ff5500" />
        <pointLight position={[-3, -2, 2]} intensity={0.6} color="#ffaa00" />
        <SceneBody />
      </Canvas>
    </div>
  )
}
