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
import { wasDragClick } from './pointerGuard'

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

/** Dramatic but capped size vs graph-wide max jobs */
const R_MIN = 0.02
const R_MAX = 0.42

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

function globalMaxWeight(nodes: GraphNode[]) {
  let m = 1
  for (const n of nodes) m = Math.max(m, n.weight || 1)
  return m
}

/**
 * Size vs graph max — small nodes stay small, big ones clearly dominate.
 * e.g. 2545 vs 77 ≈ 7× radius difference (not “almost same”).
 */
function radiusFor(node: GraphNode, globalMax: number) {
  const ratio = THREE.MathUtils.clamp(node.weight / Math.max(globalMax, 1), 0, 1)
  // Stretch low end so mid/small stay modest; top end fills R_MAX
  const stretched =
    ratio < 0.08
      ? THREE.MathUtils.mapLinear(ratio, 0, 0.08, 0, 0.22)
      : THREE.MathUtils.mapLinear(ratio, 0.08, 1, 0.22, 1)
  const t = Math.sqrt(stretched)
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

/**
 * Hierarchy climb (one hop): company → role first, then role → sector.
 * Accenture + Data Scientist openings ⇒ climb Accenture → Data Scientist → Tech·AI.
 */
const PARENT_SCORE: Record<string, number> = {
  hiring: 500, // role → company  (company’s first parent = role)
  role_in: 200, // sector → role
  company_at: 80, // city → company (fallback if no role link)
  company_in: 60, // sector → company (after role)
  hires_in: 90, // sector → city
}

function findParentId(nodeId: string, edges: GraphEdge[]): string | null {
  let best: { id: string; score: number } | null = null
  for (const e of edges) {
    if (e.source === 'core' || e.target === 'core') continue
    // Parent is source when we are the child target
    if (e.target === nodeId) {
      const score = (PARENT_SCORE[e.relation || ''] || 15) * Math.max(1, e.weight)
      if (!best || score > best.score) best = { id: e.source, score }
    }
  }
  return best?.id ?? null
}

function colorOfKind(kind: string) {
  return new THREE.Color(KIND_COLOR[kind] || '#ff5500')
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
 * Always-on label: big white name + subtle yellow number (no heavy glow).
 */
function makeLabelTex(
  name: string,
  weight: number,
  emphasized: boolean,
) {
  const c = document.createElement('canvas')
  c.width = 1024
  c.height = 256
  const ctx = c.getContext('2d')!
  ctx.clearRect(0, 0, 1024, 256)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  const label = name.length > 24 ? `${name.slice(0, 22)}…` : name

  // Tiny soft shadow for legibility only — no bloom wash
  ctx.shadowColor = 'rgba(0,0,0,0.85)'
  ctx.shadowBlur = 4
  ctx.fillStyle = '#ffffff'
  ctx.font = emphasized
    ? '800 86px Orbitron, sans-serif'
    : '800 72px Orbitron, sans-serif'
  ctx.fillText(label, 512, emphasized ? 88 : 92)

  ctx.shadowBlur = 3
  ctx.shadowColor = 'rgba(0,0,0,0.7)'
  ctx.fillStyle = emphasized ? '#ffe08a' : '#ffd060'
  ctx.font = emphasized
    ? '800 72px Rajdhani, sans-serif'
    : '800 60px Rajdhani, sans-serif'
  ctx.fillText(String(weight), 512, emphasized ? 188 : 186)

  const tex = new THREE.CanvasTexture(c)
  tex.colorSpace = THREE.SRGBColorSpace
  tex.anisotropy = 8
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
  edges,
  positions,
  nodeById,
}: {
  node: GraphNode
  position: THREE.Vector3
  interactive: boolean
  tier: number
  focused: boolean
  radius: number
  anyFocused: boolean
  spinY: MutableRefObject<number>
  edges: GraphEdge[]
  positions: Map<string, THREE.Vector3>
  nodeById: Map<string, GraphNode>
}) {
  const [hot, setHot] = useState(false)
  const body = useRef<THREE.Mesh>(null)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  // Focused stays emphasized even when cursor leaves
  const emphasized = focused || hot
  const seed = useMemo(
    () => (node.id.length * 12.9898) % 6.28,
    [node.id],
  )
  const rightDown = useRef<{ x: number; y: number } | null>(null)

  const labelTex = useMemo(
    () => makeLabelTex(node.label, node.weight, emphasized),
    [node.label, node.weight, emphasized],
  )

  const pickR = focused
    ? radius * 2.2
    : anyFocused
      ? radius * 1.1
      : radius * 1.85

  const toWorld = (local: THREE.Vector3) => {
    const world = local.clone()
    world.applyAxisAngle(new THREE.Vector3(0, 1, 0), spinY.current)
    return world
  }

  const followParentPath = () => {
    const st = useVigilStore.getState()
    const parentId = findParentId(node.id, edges)
    if (!parentId) {
      st.setStatus(`NO PARENT · ${node.label}`)
      return
    }
    const parentLocal = positions.get(parentId)
    const parentNode = nodeById.get(parentId)
    if (!parentLocal) {
      st.setStatus(`NO PARENT · ${node.label}`)
      return
    }
    const a = toWorld(position)
    const b = toWorld(parentLocal)
    const mid = a.clone().lerp(b, 0.5)
    mid.y += 0.35 // arc slightly above the edge
    st.setSceneSpin(false)
    st.requestCameraPath({
      waypoints: [
        { x: a.x, y: a.y, z: a.z },
        { x: mid.x, y: mid.y, z: mid.z },
        { x: b.x, y: b.y, z: b.z },
      ],
      distance: 1.65,
      endFocusId: parentId,
    })
    st.setStatus(
      `FOLLOW · ${node.label} → ${parentNode?.label || 'parent'}`,
    )
  }

  const teleportTo = () => {
    const st = useVigilStore.getState()
    const w = toWorld(position)
    st.setSceneSpin(false)
    st.teleportCamera({
      x: w.x,
      y: w.y,
      z: w.z,
      distance: 1.7,
    })
    st.setStatus(`TELEPORT · ${node.label}`)
  }

  useFrame((state) => {
    const t = state.clock.elapsedTime
    // Focused keeps a lively breath even without hover
    const breathAmp = focused ? 0.06 : hot ? 0.07 : 0.03
    const breath = 1 + Math.sin(t * 1.2 + seed) * breathAmp
    const glowBoost = focused ? 0.55 : hot ? 0.42 : 0.1
    const glowPulse =
      glowBoost + Math.sin(t * 1.4 + seed) * (focused || hot ? 0.12 : 0.03)

    if (body.current) {
      const mat = body.current.material as THREE.MeshStandardMaterial
      const base = focused || hot ? 1 : tier
      mat.opacity = base
      mat.emissiveIntensity =
        Math.max(0.06, glowPulse) * (focused || hot ? 1.15 : 0.45)
      const present = focused ? 1.1 : hot ? 1.12 : 1
      body.current.scale.setScalar(breath * present)
    }
  })

  const onEnter = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    setHot(true)
    useVigilStore.setState({
      statusLine: focused
        ? `FOCUSED · ${node.label} · click again to open · right-click → parent`
        : `PICK · ${node.label} · ${node.weight}`,
    })
  }
  const onLeave = () => {
    setHot(false)
    rightDown.current = null
  }

  const onCardClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive) return
    if (e.button !== 0) return
    e.stopPropagation()
    if (wasDragClick()) return
    const st = useVigilStore.getState()
    if (st.selectFocusId !== node.id) {
      st.setGraphFocusId(node.id)
      st.setSceneSpin(false)
      const w = toWorld(position)
      st.requestCameraFocus({
        id: node.id,
        x: w.x,
        y: w.y,
        z: w.z,
        distance: 1.55,
      })
      st.setStatus(`FOCUS · ${node.label} · others dimmed · click again to open`)
      return
    }
    openInsight(node)
  }

  const onRightDown = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive || e.button !== 2) return
    e.stopPropagation()
    rightDown.current = { x: e.clientX, y: e.clientY }
  }

  const onRightUp = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive || e.button !== 2) return
    e.stopPropagation()
    const d = rightDown.current
    rightDown.current = null
    if (!d) return
    const moved = Math.hypot(e.clientX - d.x, e.clientY - d.y)
    if (moved >= 8) return
    // In focus → ease along edge to parent; otherwise teleport here
    if (focused || useVigilStore.getState().graphFocusId === node.id) {
      followParentPath()
    } else {
      teleportTo()
    }
  }

  const labelOpacity = !anyFocused
    ? 0.95
    : focused || hot
      ? 1
      : Math.max(0.22, tier * 0.85)
  const labelH = emphasized ? 0.62 : 0.52
  const labelW = emphasized ? 2.45 : 2.15
  const labelY = radius * 1.25 + (emphasized ? 0.4 : 0.34)

  return (
    <group position={position}>
      <mesh
        onPointerOver={onEnter}
        onPointerOut={onLeave}
        onClick={onCardClick}
        onPointerDown={onRightDown}
        onPointerUp={onRightUp}
        onContextMenu={(e) => {
          e.stopPropagation()
          ;(e.nativeEvent as MouseEvent).preventDefault()
        }}
      >
        <sphereGeometry args={[pickR, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Stay lit while focused — even when cursor leaves */}
      {focused && (
        <pointLight color={color} intensity={0.85} distance={1.6} decay={2} />
      )}
      {hot && !focused && (
        <pointLight color={color} intensity={0.55} distance={1.2} decay={2} />
      )}

      <mesh ref={body}>
        <sphereGeometry args={[radius, 28, 28]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={focused ? 0.55 : 0.28}
          roughness={0.38}
          metalness={0.35}
          transparent
          opacity={focused || hot ? 1 : tier}
          depthWrite={(focused || hot ? 1 : tier) > 0.5}
        />
      </mesh>

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
  const globalMax = useMemo(() => globalMaxWeight(dataNodes), [dataNodes])
  const nodeById = useMemo(() => {
    const m = new Map<string, GraphNode>()
    for (const n of dataNodes) m.set(n.id, n)
    return m
  }, [dataNodes])
  const allEdges = useMemo(() => model?.edges || [], [model])
  const adj = useMemo(() => buildAdj(allEdges), [allEdges])

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
      colors: THREE.Color[]
      opacity: number
      highlight: boolean
    }[]
    const out: {
      key: string
      points: [number, number, number][]
      colors: THREE.Color[]
      opacity: number
      highlight: boolean
    }[] = []
    const sorted = [...model.edges]
      .filter((e) => e.source !== 'core' && e.target !== 'core')
      .sort((a, b) => b.weight - a.weight)

    for (const e of sorted) {
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
      const na = nodeById.get(e.source)
      const nb = nodeById.get(e.target)
      if (!na || !nb) continue
      const ta = tierOf(e.source)
      const tb = tierOf(e.target)
      const touchesFocus =
        Boolean(graphFocusId) &&
        (e.source === graphFocusId || e.target === graphFocusId)
      if (graphFocusId) {
        const touches =
          touchesFocus ||
          nearSet?.has(e.source) ||
          nearSet?.has(e.target)
        if (!touches) continue
      }
      const opacity = graphFocusId
        ? touchesFocus
          ? 0.95
          : Math.min(ta, tb) * 0.75
        : 0.42
      if (opacity < 0.05) continue
      const c0 = colorOfKind(na.kind)
      const c1 = colorOfKind(nb.kind)
      const cMid = c0.clone().lerp(c1, 0.5)
      // Midpoint lifts slightly so the gradient reads along the arc
      const mid = a.clone().lerp(b, 0.5)
      mid.y += 0.08
      out.push({
        key: `${e.source}->${e.target}`,
        points: [
          [a.x, a.y, a.z],
          [mid.x, mid.y, mid.z],
          [b.x, b.y, b.z],
        ],
        colors: [c0, cMid, c1],
        opacity,
        highlight: touchesFocus,
      })
      if (out.length >= (graphFocusId ? 40 : 70)) break
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, positions, graphFocusId, nearSet, nodeById])

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
          vertexColors={e.colors}
          transparent
          opacity={e.opacity}
          lineWidth={e.highlight ? 2.2 : graphFocusId ? 1.5 : 1.25}
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
            radius={radiusFor(n, globalMax)}
            anyFocused={anyFocused}
            spinY={spinAngle}
            edges={allEdges}
            positions={positions}
            nodeById={nodeById}
          />
        )
      })}
    </group>
  )
}
