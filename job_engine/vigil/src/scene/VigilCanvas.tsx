import { Canvas } from '@react-three/fiber'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { EnergyCore } from './EnergyCore'
import { NeuralCore } from './NeuralCore'
import { Starfield } from './Starfield'
import { OrbitNodes } from './OrbitNodes'
import { CameraRig } from './CameraRig'
import { useVigilStore } from '../store/vigilStore'

function SceneBody() {
  const vigilMode = useVigilStore((s) => s.vigilMode)
  return (
    <>
      <Starfield />
      {/* Inner glow = world-model heart; NeuralCore = living data graph */}
      <group scale={0.72}>
        <EnergyCore />
      </group>
      <NeuralCore />
      {/* Orbit dots only in VIGIL Mode — desktop uses bottom module chips */}
      {vigilMode && <OrbitNodes />}
      <CameraRig />
      <EffectComposer multisampling={0}>
        <Bloom
          intensity={1.2}
          luminanceThreshold={0.2}
          luminanceSmoothing={0.7}
          mipmapBlur
        />
      </EffectComposer>
    </>
  )
}

export function VigilCanvas() {
  return (
    <div className="vigil-canvas">
      <Canvas
        dpr={[1, 1.75]}
        camera={{ position: [0, 0, 7.4], fov: 45 }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
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
