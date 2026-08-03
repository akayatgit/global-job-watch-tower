import { useEffect, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { EnergyCore } from './EnergyCore'
import { NeuralCore } from './NeuralCore'
import { CityMap } from './CityMap'
import { CampusHost } from './CampusHost'
import { Starfield } from './Starfield'
import { OrbitNodes } from './OrbitNodes'
import { SceneControls } from './SceneControls'
import { useVigilStore } from '../store/vigilStore'

function SceneBody() {
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityViewMode = useVigilStore((s) => s.cityViewMode)
  const campusOn = sceneMode === 'city' && cityViewMode === 'campus'
  return (
    <>
      {!campusOn && <Starfield />}
      {!campusOn && <EnergyCore />}
      {sceneMode === 'graph' && <NeuralCore />}
      {campusOn && <CampusHost />}
      {vigilMode && sceneMode === 'core' && <OrbitNodes />}
      <SceneControls />
      <EffectComposer multisampling={0}>
        <Bloom
          intensity={
            campusOn
              ? 0.55
              : sceneMode === 'core'
                ? 0.45
                : sceneMode === 'graph'
                  ? 0.22
                  : 0.55
          }
          luminanceThreshold={campusOn ? 0.35 : sceneMode === 'graph' ? 0.72 : 0.5}
          luminanceSmoothing={0.88}
          mipmapBlur
        />
      </EffectComposer>
    </>
  )
}

export function VigilCanvas() {
  const wrap = useRef<HTMLDivElement>(null)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityViewMode = useVigilStore((s) => s.cityViewMode)
  const mapOn = sceneMode === 'city' && cityViewMode === 'map'
  const campusOn = sceneMode === 'city' && cityViewMode === 'campus'

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const st = useVigilStore.getState()
    st.resetView()

    const onWheel = (e: WheelEvent) => {
      // MapLibre owns wheel; campus/core/graph need preventDefault
      const s = useVigilStore.getState()
      if (s.sceneMode === 'city' && s.cityViewMode === 'map') return
      e.preventDefault()
    }
    const onKey = (e: KeyboardEvent) => {
      const s = useVigilStore.getState()
      if (s.focusedPanel || s.trainingActive) return
      if (e.key === 'Escape' || e.key === 'Home' || e.key === '0') {
        e.preventDefault()
        if (s.sceneMode === 'city') {
          if (s.selectFocusId?.startsWith('company:')) {
            s.clearCameraFocus()
            s.setSelectFocusId(null)
            s.setStatus(
              s.cityViewMode === 'campus'
                ? 'CAMPUS · pick a tower'
                : s.cityFocus
                  ? `MAP · ${s.cityFocus} · pick a company`
                  : 'MAP · India hiring · click a city',
            )
            return
          }
          if (s.cityFocus) {
            s.setCityFocus(null)
            s.setStatus(
              s.cityViewMode === 'campus'
                ? 'CAMPUS · nightlife India clusters'
                : 'MAP · India hiring · click a city',
            )
            return
          }
        }
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
      if (s.sceneMode === 'city' && s.cityViewMode === 'map') return
      s.resetView()
    }
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
    <div
      className={`vigil-canvas${mapOn ? ' vigil-canvas--map' : ''}${campusOn ? ' vigil-canvas--campus' : ''}`}
      ref={wrap}
    >
      {mapOn ? (
        <CityMap />
      ) : (
        <Canvas
          dpr={[1, 1.5]}
          camera={{ position: [0, 0.6, 7.2], fov: 45 }}
          shadows
          gl={{
            antialias: true,
            alpha: false,
            powerPreference: 'high-performance',
          }}
          onPointerMissed={() => {
            const st = useVigilStore.getState()
            if (st.sceneMode === 'graph' && st.graphFocusId) {
              st.setGraphFocusId(null)
              st.clearCameraFocus()
              st.setStatus('GRAPH · global view')
              return
            }
            if (
              st.sceneMode === 'city' &&
              st.cityViewMode === 'campus' &&
              st.selectFocusId?.startsWith('company:')
            ) {
              st.clearCameraFocus()
              st.setSelectFocusId(null)
              st.setStatus('CAMPUS · pick a tower')
            }
          }}
        >
          <color attach="background" args={['#050302']} />
          <ambientLight intensity={0.28} />
          <pointLight position={[4, 3, 4]} intensity={0.65} color="#ff5500" />
          <pointLight position={[-3, -2, 2]} intensity={0.3} color="#ffaa00" />
          <SceneBody />
        </Canvas>
      )}
    </div>
  )
}
