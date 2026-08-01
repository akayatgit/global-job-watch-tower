import { Canvas } from '@react-three/fiber'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import { EnergyCore } from './EnergyCore'
import { Starfield } from './Starfield'
import { OrbitNodes } from './OrbitNodes'
import { CameraRig } from './CameraRig'

export function VigilCanvas() {
  return (
    <div className="vigil-canvas">
      <Canvas
        dpr={[1, 1.75]}
        camera={{ position: [0, 0, 6.2], fov: 45 }}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
      >
        <color attach="background" args={['#050302']} />
        <ambientLight intensity={0.35} />
        <pointLight position={[4, 3, 4]} intensity={1.2} color="#ff5500" />
        <pointLight position={[-3, -2, 2]} intensity={0.6} color="#ffaa00" />
        <Starfield />
        <EnergyCore />
        <OrbitNodes />
        <CameraRig />
        <EffectComposer multisampling={0}>
          <Bloom
            intensity={1.35}
            luminanceThreshold={0.18}
            luminanceSmoothing={0.7}
            mipmapBlur
          />
        </EffectComposer>
      </Canvas>
    </div>
  )
}
