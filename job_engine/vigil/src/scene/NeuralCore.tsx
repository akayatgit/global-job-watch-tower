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
  city: '#2dd4bf', // teal — not blue, so purple numbers stay readable
  company: '#fbbf24',
  role: '#fb923c',
}

/** Wider clusters so focus hover doesn’t steal neighbors */
const CLUSTER: Record<string, THREE.Vector3> = {
  sector: new THREE.Vector3(-3.2, 0.6, 0.3),
  role: new THREE.Vector3(0.4, 2.8, -0.6),
  city: new THREE.Vector3(3.4, 0.35, 0.7),
  company: new THREE.Vector3(0.2, -3.0, 0.4),
}

const TIER_FOCUS = 1
const TIER_NEAR = 0.2
const TIER_FAR = 0.1

const R_MIN = 0.055
const R_MAX = 0.16

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
      const a = (i / Math.max(n, 1)) * Math.PI * 2 + kind.length * 0.25
      // Extra air between nodes for clean presenting
      const spread = 1.35 + Math.min(n, 14) * 0.1
      const r = spread * (0.65 + (i % 5) * 0.18)
      pos.set(
        node.id,
        new THREE.Vector3(
          center.x + Math.cos(a) * r,
          center.y + Math.sin(a * 1.25) * r * 0.58,
          center.z + Math.sin(a) * r * 0.8,
        ),
      )
    })
  }
  return pos
}

/** Max weight per kind — sphere size is relative within category */
function maxWeightByKind(nodes: GraphNode[]) {
  const m = new Map<string, number>()
  for (const n of nodes) {
    m.set(n.kind, Math.max(m.get(n.kind) || 1, n.weight || 1))
  }
  return m
}

function radiusFor(node: GraphNode, maxByKind: Map<string, number>) {
  const max = maxByKind.get(node.kind) || 1
  const t = Math.sqrt(THREE.MathUtils.clamp(node.weight / max, 0.05, 1))
  return THREE.MathUtils.lerp(R_MIN, R_MAX, t)
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

/**
 * Always-on label: small white name + neon purple number.
 * Emphasized (hot/focused) = larger / brighter — still no card plate.
 */
function makeLabelTex(
  name: string,
  weight: number,
  emphasized: boolean,
) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 128
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 512, 128)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const label = name.length > 18 ? `${name.slice(0, 16)}…` : name

  // Soft dark halo for legibility only (not a box)
  ctx.shadowColor = 'rgba(0,0,0,0.9)'
  ctx.shadowBlur = emphasized ? 14 : 8
  ctx.fillStyle = emphasized ? '#ffffff' : 'rgba(255,255,255,0.92)'
  ctx.font = emphasized
    ? '800 40px Orbitron, sans-serif'
    : '700 28px Orbitron, sans-serif'
  ctx.fillText(label, 256, emphasized ? 42 : 44)

  // Neon purple gradient number — readable on teal/orange/gold nodes
  const g = ctx.createLinearGradient(200, 70, 312, 110)
  g.addColorStop(0, '#e9d5ff')
  g.addColorStop(0.45, '#d946ef')
  g.addColorStop(1, '#a855f7')
  ctx.shadowColor = emphasized
    ? 'rgba(217, 70, 239, 0.95)'
    : 'rgba(168, 85, 247, 0.65)'
  ctx.shadowBlur = emphasized ? 18 : 10
  ctx.fillStyle = g
  ctx.font = emphasized
    ? '800 36px Rajdhani, sans-serif'
    : '800 26px Rajdhani, sans-serif'
  ctx.fillText(String(weight), 256, emphasized ? 92 : 88)

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
  radius,
  anyFocused,
  spinY,
}: {
  node: GraphNode
  position: THREE.Vector3
  interactive: boolean
  tier: number
  focused: boolean
  radius: number
  /** True when some node in the graph is focused — shrink others’ hitboxes */
  anyFocused: boolean
  spinY: MutableRefObject<number>
}) {
  const [hot, setHot] = useState(false)
  const body = useRef<THREE.Mesh>(null)
  const aura = useRef<THREE.Mesh>(null)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  const emphasized = focused || hot
  const seed = useMemo(
    () => (node.id.length * 12.9898) % 6.28,
    [node.id],
  )

  const labelTex = useMemo(
    () => makeLabelTex(node.label, node.weight, emphasized),
    [node.label, node.weight, emphasized],
  )

  // Base visual radius; pick target tighter when something else is focused
  const pickR = focused
    ? radius * 2.4
    : anyFocused
      ? radius * 1.15
      : radius * 2.0

  useFrame((state) => {
    const t = state.clock.elapsedTime
    // Easy breath — scale + emissive glow, no rings
    const breath = 1 + Math.sin(t * 1.35 + seed) * (focused ? 0.08 : hot ? 0.1 : 0.045)
    const glowBoost = hot ? 0.55 : focused ? 0.4 : 0.12
    const glowPulse = glowBoost + Math.sin(t * 1.6 + seed) * (hot || focused ? 0.18 : 0.05)

    if (body.current) {
      const mat = body.current.material as THREE.MeshStandardMaterial
      const base = hot ? 1 : focused ? 1 : tier
      mat.opacity = base
      mat.emissiveIntensity = Math.max(0.05, glowPulse) * (base > 0.5 ? 1 : 0.5)
      const present = focused ? 1.12 : hot ? 1.18 : 1
      body.current.scale.setScalar(breath * present)
    }
    if (aura.current) {
      // Soft spherical bloom (not a ring)
      const show = hot || focused
      aura.current.visible = show
      if (show) {
        const a = 0.18 + Math.sin(t * 1.8 + seed) * 0.08
        aura.current.scale.setScalar(breath * (hot ? 2.1 : 1.85))
        ;(aura.current.material as THREE.MeshBasicMaterial).opacity = a
      }
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

  const labelOpacity = hot || focused ? 1 : Math.max(0.35, tier)
  const labelH = emphasized ? 0.32 : 0.22
  const labelW = emphasized ? 1.15 : 0.85
  const labelY = radius * 1.15 + (emphasized ? 0.22 : 0.16)

  return (
    <group position={position}>
      <mesh
        onPointerOver={onEnter}
        onPointerOut={onLeave}
        onClick={onCardClick}
      >
        <sphereGeometry args={[pickR, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {(focused || hot) && (
        <pointLight
          color={color}
          intensity={focused ? 1.35 : 1.05}
          distance={2.2}
          decay={2}
        />
      )}

      {/* Soft sphere aura — breath glow, not a ring */}
      <mesh ref={aura} visible={false}>
        <sphereGeometry args={[radius * 1.05, 20, 20]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.2}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      <mesh ref={body}>
        <sphereGeometry args={[radius, 28, 28]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={0.35}
          roughness={0.32}
          metalness={0.4}
          transparent
          opacity={hot || focused ? 1 : tier}
          depthWrite={(hot || focused ? 1 : tier) > 0.5}
        />
      </mesh>

      {/* Always-on small white + purple number label */}
      <Billboard follow>
        <mesh position={[0, labelY, 0]} renderOrder={10}>
          <planeGeometry args={[labelW, labelH]} />
          <meshBasicMaterial
            map={labelTex}
            transparent
            opacity={labelOpacity}
            depthWrite={false}
            toneMapped={false}
          />
        </mesh>
      </Billboard>
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
  const maxByKind = useMemo(() => maxWeightByKind(dataNodes), [dataNodes])
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
      if (graphFocusId) {
        const touches =
          e.source === graphFocusId ||
          e.target === graphFocusId ||
          nearSet?.has(e.source) ||
          nearSet?.has(e.target)
        if (!touches) continue
      }
      const opacity = graphFocusId ? Math.min(ta, tb) * 0.85 : 0.28
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

  const anyFocused = Boolean(graphFocusId)

  return (
    <group ref={group}>
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
            radius={radiusFor(n, maxByKind)}
            anyFocused={anyFocused}
            spinY={spinAngle}
          />
        )
      })}
    </group>
  )
}
