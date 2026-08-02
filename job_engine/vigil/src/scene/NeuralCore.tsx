import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard, Line } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

type GraphNode = {
  id: string
  kind: string
  label: string
  weight: number
  sector_id?: string
  city_id?: string
  company_id?: number
  search_id?: number
}

type GraphEdge = {
  source: string
  target: string
  weight: number
  relation?: string
}

type WorldModel = {
  window_label?: string
  stats: { jobs: number; nodes: number; edges: number; max_weight: number }
  nodes: GraphNode[]
  edges: GraphEdge[]
}

const KIND_COLOR: Record<string, string> = {
  sector: '#ff5500',
  city: '#38bdf8',
  company: '#fbbf24',
  role: '#fb923c',
}

const CLUSTER: Record<string, THREE.Vector3> = {
  sector: new THREE.Vector3(-2.2, 0.5, 0.2),
  role: new THREE.Vector3(0.3, 2.0, -0.5),
  city: new THREE.Vector3(2.3, 0.25, 0.6),
  company: new THREE.Vector3(0.15, -2.1, 0.35),
}

/** Focused = 1 · immediate neighbors = 0.2 · everything else = 0.1 */
const TIER_FOCUS = 1
const TIER_NEAR = 0.2
const TIER_FAR = 0.1

function layoutNodes(nodes: GraphNode[]) {
  const byKind = new Map<string, GraphNode[]>()
  for (const n of nodes) {
    if (n.kind === 'core') continue
    const list = byKind.get(n.kind) || []
    list.push(n)
    byKind.set(n.kind, list)
  }
  const pos = new Map<string, THREE.Vector3>()
  for (const [kind, list] of byKind) {
    const center = CLUSTER[kind] || new THREE.Vector3()
    const sorted = [...list].sort((a, b) => b.weight - a.weight)
    const n = sorted.length
    sorted.forEach((node, i) => {
      const a = (i / Math.max(n, 1)) * Math.PI * 2 + kind.length * 0.2
      const spread = 0.85 + Math.min(n, 12) * 0.06
      const r = spread * (0.55 + (i % 5) * 0.14)
      pos.set(
        node.id,
        new THREE.Vector3(
          center.x + Math.cos(a) * r,
          center.y + Math.sin(a * 1.3) * r * 0.55,
          center.z + Math.sin(a) * r * 0.75,
        ),
      )
    })
  }
  return pos
}

function buildAdj(edges: GraphEdge[]) {
  const adj = new Map<string, Set<string>>()
  const add = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set())
    adj.get(a)!.add(b)
  }
  for (const e of edges) {
    if (e.source === 'core' || e.target === 'core') continue
    add(e.source, e.target)
    add(e.target, e.source)
  }
  return adj
}

function openInsight(n: GraphNode) {
  const st = useVigilStore.getState()
  st.triggerBurst()
  if (n.kind === 'sector' && n.sector_id) {
    st.setSectorFilter(n.sector_id)
    st.openPanel('tower')
    st.setStatus(`OPEN · ${n.label}`)
    return
  }
  if (n.kind === 'city' && n.city_id) {
    st.setCityFilter(n.city_id)
    st.setSceneMode('city')
    st.setCityFocus(n.city_id)
    st.setStatus(`CITY · ${n.label}`)
    return
  }
  if (n.kind === 'company' && n.company_id != null) {
    st.openCompanyJobs(n.company_id, n.label, 7)
    return
  }
  if (n.kind === 'role' && n.search_id != null) {
    st.openRoleHire(n.search_id, n.label, 7)
  }
}

/** Clean label sprite — no plate, no stroke box */
function makeLabelTex(name: string, weight: number, color: string, hot: boolean) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 512, 128)
  // Soft readable glow only — no background rectangle
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const label = name.length > 20 ? `${name.slice(0, 18)}…` : name
  ctx.font = '800 44px Orbitron, sans-serif'
  ctx.shadowColor = hot ? color : 'rgba(0,0,0,0.85)'
  ctx.shadowBlur = hot ? 22 : 10
  ctx.fillStyle = '#ffffff'
  ctx.fillText(label, 256, 48)
  ctx.shadowBlur = hot ? 16 : 8
  ctx.shadowColor = color
  ctx.fillStyle = color
  ctx.font = '800 32px Rajdhani, sans-serif'
  ctx.fillText(String(weight), 256, 92)
  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 4
  return tex
}

function GraphCard({
  node,
  position,
  interactive,
  tier,
  focused,
  spinY,
}: {
  node: GraphNode
  position: THREE.Vector3
  interactive: boolean
  /** 1 | 0.2 | 0.1 */
  tier: number
  focused: boolean
  spinY: MutableRefObject<number>
}) {
  const [hot, setHot] = useState(false)
  const hoverGlow = useRef<THREE.Mesh>(null)
  const focusGlow = useRef<THREE.Mesh>(null)
  const body = useRef<THREE.Mesh>(null)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  const showLabel = focused || hot

  const labelTex = useMemo(
    () => (showLabel ? makeLabelTex(node.label, node.weight, color, hot || focused) : null),
    [showLabel, node.label, node.weight, color, hot, focused],
  )

  useFrame((state) => {
    const t = state.clock.elapsedTime
    if (hoverGlow.current) {
      hoverGlow.current.visible = hot && !focused
      if (hot && !focused) {
        const pulse = 0.45 + Math.sin(t * 5.5) * 0.25
        hoverGlow.current.scale.setScalar(1.4 + Math.sin(t * 4.2) * 0.2)
        ;(hoverGlow.current.material as THREE.MeshBasicMaterial).opacity = pulse
      }
    }
    if (focusGlow.current) {
      focusGlow.current.visible = focused
      if (focused) {
        const pulse = 0.4 + Math.sin(t * 2.8) * 0.2
        focusGlow.current.scale.setScalar(1.8 + Math.sin(t * 2.2) * 0.15)
        ;(focusGlow.current.material as THREE.MeshBasicMaterial).opacity = pulse
      }
    }
    if (body.current) {
      const mat = body.current.material as THREE.MeshStandardMaterial
      const base = hot ? 1 : focused ? 1 : tier
      mat.opacity = base
      mat.emissiveIntensity = hot ? 1.4 : focused ? 1.1 : tier > 0.5 ? 0.35 : 0.08
      body.current.scale.setScalar(focused ? 1.35 : hot ? 1.25 : 1)
    }
  })

  const onEnter = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    setHot(true)
    useVigilStore.setState({
      statusLine: focused
        ? `FOCUSED · ${node.label} · click again to open`
        : `PICK · ${node.label} · ${node.weight}`,
    })
  }
  const onLeave = () => setHot(false)

  const onCardClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    const st = useVigilStore.getState()
    if (st.selectFocusId !== node.id) {
      st.setGraphFocusId(node.id)
      st.setSceneSpin(false)
      const world = position.clone()
      world.applyAxisAngle(new THREE.Vector3(0, 1, 0), spinY.current)
      st.requestCameraFocus({
        id: node.id,
        x: world.x,
        y: world.y,
        z: world.z,
        distance: 1.55,
      })
      st.setStatus(`FOCUS · ${node.label} · others dimmed · click again to open`)
      return
    }
    openInsight(node)
  }

  // Dimmed nodes still catch hover for "pick me", but stay visually quiet until hot
  const restOpacity = hot ? 1 : focused ? TIER_FOCUS : tier

  return (
    <group position={position}>
      {/* Fat pick target */}
      <mesh
        onPointerOver={onEnter}
        onPointerOut={onLeave}
        onClick={onCardClick}
      >
        <sphereGeometry args={[0.32, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Pick-me hover aura */}
      <mesh ref={hoverGlow} visible={false}>
        <ringGeometry args={[0.16, 0.28, 48]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.5}
          side={THREE.DoubleSide}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      {/* Focus aura */}
      <mesh ref={focusGlow} visible={false}>
        <ringGeometry args={[0.18, 0.34, 48]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.45}
          side={THREE.DoubleSide}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      {(focused || hot) && (
        <pointLight
          color={color}
          intensity={focused ? 1.6 : 1.1}
          distance={2.4}
          decay={2}
        />
      )}

      {/* Lit body — respects scene light / silhouette */}
      <mesh ref={body}>
        <sphereGeometry args={[0.09, 24, 24]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.35}
          roughness={0.35}
          metalness={0.45}
          transparent
          opacity={restOpacity}
          depthWrite={restOpacity > 0.5}
        />
      </mesh>

      {/* Label only for focused or hovered — no plate, no stroke box */}
      {showLabel && labelTex && (
        <Billboard follow>
          <mesh position={[0, 0.28, 0]} renderOrder={10}>
            <planeGeometry args={[1.1, 0.28]} />
            <meshBasicMaterial
              map={labelTex}
              transparent
              depthWrite={false}
              toneMapped={false}
            />
          </mesh>
        </Billboard>
      )}
    </group>
  )
}

export function NeuralCore() {
  const [model, setModel] = useState<WorldModel | null>(null)
  const group = useRef<THREE.Group>(null)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const sceneSpin = useVigilStore((s) => s.sceneSpin)
  const graphFocusId = useVigilStore((s) => s.graphFocusId)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const interactive = sceneMode === 'graph' && !focusedPanel && !trainingActive
  const spinAngle = useRef(0)

  useEffect(() => {
    if (sceneMode !== 'graph') return
    let alive = true
    const pull = () => {
      api
        .worldModel(7)
        .then((d) => {
          if (alive && d?.nodes) setModel(d as WorldModel)
        })
        .catch(() => {})
    }
    pull()
    const id = window.setInterval(pull, 45000)
    return () => {
      alive = false
      window.clearInterval(id)
    }
  }, [sceneMode])

  useEffect(() => {
    if (sceneMode !== 'graph') {
      useVigilStore.getState().setGraphFocusId(null)
    }
  }, [sceneMode])

  const dataNodes = useMemo(
    () => (model?.nodes || []).filter((n) => n.kind !== 'core'),
    [model],
  )
  const positions = useMemo(() => layoutNodes(dataNodes), [dataNodes])
  const adj = useMemo(() => buildAdj(model?.edges || []), [model])

  const nearSet = useMemo(() => {
    if (!graphFocusId) return null
    return adj.get(graphFocusId) || new Set<string>()
  }, [graphFocusId, adj])

  const tierOf = (id: string) => {
    if (!graphFocusId) return TIER_FOCUS
    if (id === graphFocusId) return TIER_FOCUS
    if (nearSet?.has(id)) return TIER_NEAR
    return TIER_FAR
  }

  const edgeLines = useMemo(() => {
    if (!model) return [] as {
      key: string
      points: [number, number, number][]
      opacity: number
    }[]
    const out: {
      key: string
      points: [number, number, number][]
      opacity: number
    }[] = []
    const sorted = [...model.edges]
      .filter((e) => e.source !== 'core' && e.target !== 'core')
      .sort((a, b) => b.weight - a.weight)

    for (const e of sorted) {
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
      const ta = tierOf(e.source)
      const tb = tierOf(e.target)
      // Only keep edges touching the focus neighborhood when focused
      if (graphFocusId) {
        const touches =
          e.source === graphFocusId ||
          e.target === graphFocusId ||
          nearSet?.has(e.source) ||
          nearSet?.has(e.target)
        if (!touches) continue
      }
      const opacity = graphFocusId
        ? Math.min(ta, tb) * 0.85
        : 0.28
      if (opacity < 0.05) continue
      out.push({
        key: `${e.source}->${e.target}`,
        points: [
          [a.x, a.y, a.z],
          [b.x, b.y, b.z],
        ],
        opacity,
      })
      if (out.length >= (graphFocusId ? 40 : 70)) break
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, positions, graphFocusId, nearSet])

  useFrame((_, dt) => {
    if (!group.current) return
    if (sceneSpin && !graphFocusId) {
      spinAngle.current += dt * 0.03
    }
    group.current.rotation.y = spinAngle.current
  })

  if (sceneMode !== 'graph' || !model || dataNodes.length === 0) return null

  return (
    <group ref={group}>
      {/* Key light + fill so spheres cast silhouette / receive shading */}
      <directionalLight
        position={[4, 6, 3]}
        intensity={graphFocusId ? 1.1 : 0.65}
        color="#ffe0c0"
      />
      <directionalLight
        position={[-5, 2, -4]}
        intensity={graphFocusId ? 0.25 : 0.35}
        color="#6090ff"
      />
      <ambientLight intensity={graphFocusId ? 0.12 : 0.22} />

      {edgeLines.map((e) => (
        <Line
          key={e.key}
          points={e.points}
          color="#ff5500"
          transparent
          opacity={e.opacity}
          lineWidth={graphFocusId ? 1.6 : 1.2}
          depthWrite={false}
        />
      ))}

      {dataNodes.map((n) => {
        const p = positions.get(n.id)
        if (!p) return null
        return (
          <GraphCard
            key={n.id}
            node={n}
            position={p}
            interactive={interactive}
            tier={tierOf(n.id)}
            focused={graphFocusId === n.id}
            spinY={spinAngle}
          />
        )
      })}
    </group>
  )
}
