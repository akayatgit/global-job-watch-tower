import { useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { useVigilStore } from '../store/vigilStore'

/**
 * Labor-market singularity — GPU particle swarm.
 * Safe to fly through: dims + shrinks points when camera is inside.
 */
const COUNT = 16000

const vertexShader = /* glsl */ `
uniform float uTime;
uniform float uBurst;
uniform float uScale;
uniform float uCamDist;
attribute float aIndex;
varying vec3 vColor;
varying float vAlpha;

void main() {
  float count = ${COUNT}.0;
  float i = aIndex;
  float t = i / max(count - 1.0, 1.0);
  float golden = 2.399963229728653;
  float breathe = 1.0 + 0.1 * sin(uTime * 0.65);
  float radius = pow(t, 0.55) * 1.35 * breathe * uScale;
  float theta = i * golden + uTime * 0.14;
  float phi = acos(clamp(1.0 - 2.0 * ((i + 0.5) / count), -1.0, 1.0));
  float swirl = uTime * 0.32 + radius * 2.0;
  float px = radius * sin(phi) * cos(theta + swirl);
  float py = radius * cos(phi) * 0.9 + 0.06 * sin(uTime * 1.0 + i * 0.007);
  float pz = radius * sin(phi) * sin(theta + swirl);
  float fold = 0.12 * sin(uTime * 1.1 + radius * 3.0);
  float warp = 0.08 * sin(theta * 2.0 - uTime * 0.85);
  px = px * (1.0 + fold) + warp * pz;
  pz = pz * (1.0 + fold) - warp * px * 0.45;
  float kick = 1.0 + uBurst * (1.0 - t) * 0.35;
  vec3 pos = vec3(px, py, pz) * kick;

  vColor = mix(vec3(1.0, 0.28, 0.02), vec3(1.0, 0.62, 0.12), t);
  vColor = mix(vColor, vec3(1.0, 0.85, 0.45), pow(1.0 - t, 6.0) * 0.28);

  // Inside the orb: thin the fog so structure stays readable
  float inside = smoothstep(3.2, 0.6, uCamDist);
  vColor *= mix(1.0, 0.35, inside);
  vAlpha = mix(0.75, 0.22, inside) * (0.5 + 0.5 * (1.0 - t));

  vec4 mvPosition = modelViewMatrix * vec4(pos, 1.0);
  float dist = max(-mvPosition.z, 0.35);
  float psz = (1.2 + 2.0 * (1.0 - t)) * (70.0 / dist);
  // Cap harder when deep inside
  float maxSz = mix(7.0, 2.8, inside);
  gl_PointSize = clamp(psz, 0.6, maxSz);
  gl_Position = projectionMatrix * mvPosition;
}
`

const fragmentShader = /* glsl */ `
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = length(c);
  float alpha = smoothstep(0.5, 0.14, d) * vAlpha;
  if (alpha < 0.025) discard;
  gl_FragColor = vec4(vColor, alpha);
}
`

export function EnergyCore() {
  const points = useRef<THREE.Points>(null)
  const mat = useRef<THREE.ShaderMaterial>(null)
  const { camera } = useThree()
  const coreScale = useVigilStore((s) => s.coreScale)
  const coreBurst = useVigilStore((s) => s.coreBurst)
  const sceneMode = useVigilStore((s) => s.sceneMode)

  const { positions, aIndex } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3)
    const aIndex = new Float32Array(COUNT)
    for (let i = 0; i < COUNT; i++) aIndex[i] = i
    return { positions, aIndex }
  }, [])

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uBurst: { value: 0 },
      uScale: { value: 1 },
      uCamDist: { value: 8 },
    }),
    [],
  )

  useFrame((state) => {
    if (!mat.current) return
    mat.current.uniforms.uTime.value = state.clock.elapsedTime
    const burstAge = (performance.now() - coreBurst) / 1000
    mat.current.uniforms.uBurst.value =
      burstAge >= 0 && burstAge < 0.7 ? (0.7 - burstAge) / 0.7 : 0
    const modeScale =
      sceneMode === 'core' ? 1 : sceneMode === 'graph' ? 0.28 : 0.18
    mat.current.uniforms.uScale.value = coreScale * modeScale
    mat.current.uniforms.uCamDist.value = camera.position.length()
    if (points.current) {
      points.current.rotation.y = state.clock.elapsedTime * 0.035
    }
  })

  if (sceneMode === 'city') return null

  return (
    <points ref={points} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-aIndex" args={[aIndex, 1]} />
      </bufferGeometry>
      <shaderMaterial
        ref={mat}
        uniforms={uniforms}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  )
}
