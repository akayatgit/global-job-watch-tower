import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Billboard, Html, Line } from '@react-three/drei'
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

const EDGE_LABEL: Record<string, string> = {
  contains: 'in',
  places: 'at',
  employs: 'hires',
  role_in: 'role',
  hires_in: 'hires in',
  company_in: 'in sector',
  company_at: 'in city',
  hiring: 'hiring',
}

/** Soft distance fade radius around focused node */
const FADE_RADIUS = 3.6

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
      const spread = 0.7 + Math.min(n, 12) * 0.05
      const r = spread * (0.5 + (i % 5) * 0.12)
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

function GraphCard({
  node,
  position,
  interactive,
  showLabel,
  fade,
  focused,
  spinY,
}: {
  node: GraphNode
  position: THREE.Vector3
  interactive: boolean
  showLabel: boolean
  /** 0..1 visual weight from distance-to-focus */
  fade: number
  focused: boolean
  spinY: MutableRefObject<number>
}) {
  const [hot, setHot] = useState(false)
  const glow = useRef<THREE.Mesh>(null)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  const cardW = 0.72
  const cardH = 0.28

  useFrame((state) => {
    if (!glow.current) return
    glow.current.visible = focused
    if (!focused) return
    const pulse = 0.35 + Math.sin(state.clock.elapsedTime * 3.4) * 0.25
    const s = 1.6 + Math.sin(state.clock.elapsedTime * 2.6) * 0.2
    glow.current.scale.setScalar(s)
    const mat = glow.current.material as THREE.MeshBasicMaterial
    mat.opacity = pulse
  })

  const onEnter = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive || fade < 0.12) return
    e.stopPropagation()
    setHot(true)
    useVigilStore.setState({
      statusLine: focused
        ? `FOCUSED · click again to open · ${node.label}`
        : `${node.kind.toUpperCase()} · ${node.label} · ${node.weight}`,
    })
  }
  const onLeave = () => setHot(false)

  const onCardClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive || fade < 0.12) return
    e.stopPropagation()
    const st = useVigilStore.getState()
    if (st.selectFocusId !== node.id) {
      st.setGraphFocusId(node.id)
      st.setSceneSpin(false)
      // World position accounts for graph group spin
      const world = position.clone()
      world.applyAxisAngle(new THREE.Vector3(0, 1, 0), spinY.current)
      st.requestCameraFocus({
        id: node.id,
        x: world.x,
        y: world.y,
        z: world.z,
        distance: 1.7,
      })
      st.setStatus(`FOCUS · ${node.label} · click again to open`)
      return
    }
    openInsight(node)
  }

  const opacity = focused || hot ? 1 : Math.max(0.08, fade * 0.95)

  return (
    <group position={position}>
      <mesh
        onPointerOver={onEnter}
        onPointerOut={onLeave}
        onClick={onCardClick}
      >
        <sphereGeometry args={[0.28, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Focus glow ring */}
      <mesh ref={glow} visible={false}>
        <ringGeometry args={[0.14, 0.22, 40]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={0.5}
          side={THREE.DoubleSide}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
      {focused && (
        <pointLight color={color} intensity={1.2} distance={2.0} />
      )}

      <mesh>
        <sphereGeometry args={[focused ? 0.13 : 0.08, 20, 20]} />
        <meshBasicMaterial color={color} transparent opacity={opacity} />
      </mesh>

      {showLabel && fade > 0.22 && (
        <Billboard follow>
          <mesh
            position={[0, 0.22, 0]}
            onPointerOver={onEnter}
            onPointerOut={onLeave}
            onClick={onCardClick}
          >
            <planeGeometry args={[cardW, cardH]} />
            <meshBasicMaterial
              color={focused || hot ? '#2a1408' : '#140a04'}
              transparent
              opacity={opacity * 0.95}
              depthWrite={false}
            />
          </mesh>
          <mesh position={[0, 0.22, -0.001]}>
            <planeGeometry args={[cardW + 0.03, cardH + 0.03]} />
            <meshBasicMaterial
              color={color}
              transparent
              opacity={
                focused || hot ? 0.9 : Math.max(0.08, fade * 0.55)
              }
              depthWrite={false}
            />
          </mesh>
          {/* Focus bloom plate */}
          {focused && (
            <mesh position={[0, 0.22, -0.02]}>
              <planeGeometry args={[cardW + 0.2, cardH + 0.16]} />
              <meshBasicMaterial
                color={color}
                transparent
                opacity={0.28}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </mesh>
          )}
          <Html
            position={[0, 0.22, 0.01]}
            center
            distanceFactor={6.5}
            style={{ pointerEvents: 'none', opacity }}
            zIndexRange={[40, 0]}
          >
            <div
              className={`vigil-tag vigil-tag-card vigil-tag-${node.kind}${hot || focused ? ' hot' : ''}`}
              aria-hidden
            >
              <span className="vigil-tag-name">{node.label}</span>
              <span className="vigil-tag-meta">{node.weight}</span>
            </div>
          </Html>
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

  const focusPos = graphFocusId ? positions.get(graphFocusId) : null

  const fadeOf = (id: string, p: THREE.Vector3) => {
    if (!focusPos) return 1
    if (id === graphFocusId) return 1
    const d = p.distanceTo(focusPos)
    // Soft falloff by distance — nearby stay bright, far fade down
    return THREE.MathUtils.clamp(1 - d / FADE_RADIUS, 0.06, 1)
  }

  const edgeLines = useMemo(() => {
    if (!model) return [] as {
      key: string
      points: [number, number, number][]
      mid: THREE.Vector3
      label: string
      weight: number
      opacity: number
    }[]
    const out: {
      key: string
      points: [number, number, number][]
      mid: THREE.Vector3
      label: string
      weight: number
      opacity: number
    }[] = []
    const sorted = [...model.edges]
      .filter((e) => e.source !== 'core' && e.target !== 'core')
      .sort((a, b) => b.weight - a.weight)
    for (const e of sorted) {
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
      const fa = fadeOf(e.source, a)
      const fb = fadeOf(e.target, b)
      const opacity = Math.min(fa, fb) * 0.4
      if (opacity < 0.04) continue
      const mid = a.clone().lerp(b, 0.5)
      mid.y += 0.1
      out.push({
        key: `${e.source}->${e.target}`,
        points: [
          [a.x, a.y, a.z],
          [mid.x, mid.y, mid.z],
          [b.x, b.y, b.z],
        ],
        mid,
        label: EDGE_LABEL[e.relation || ''] || e.relation || 'link',
        weight: e.weight,
        opacity,
      })
      if (out.length >= 90) break
    }
    return out
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model, positions, graphFocusId, focusPos])

  const labelNodeIds = useMemo(() => {
    if (!graphFocusId || !focusPos) {
      const top = [...dataNodes].sort((a, b) => b.weight - a.weight).slice(0, 22)
      return new Set(top.map((n) => n.id))
    }
    // Show labels for focus + reasonably near nodes
    const near = dataNodes.filter((n) => {
      const p = positions.get(n.id)
      if (!p) return false
      return fadeOf(n.id, p) > 0.35
    })
    return new Set(near.map((n) => n.id))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataNodes, graphFocusId, focusPos, positions])

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
      {edgeLines.map((e) => (
        <group key={e.key}>
          <Line
            points={e.points}
            color="#ff5500"
            transparent
            opacity={e.opacity}
            lineWidth={1.35}
            depthWrite={false}
          />
          {e.weight >= 10 && e.opacity > 0.18 && (
            <Html
              position={e.mid}
              center
              distanceFactor={10}
              style={{ pointerEvents: 'none', opacity: e.opacity / 0.4 }}
              zIndexRange={[10, 0]}
            >
              <div className="vigil-tag vigil-tag-edge" aria-hidden>
                {e.label} · {e.weight}
              </div>
            </Html>
          )}
        </group>
      ))}
      {dataNodes.map((n) => {
        const p = positions.get(n.id)
        if (!p) return null
        const fade = fadeOf(n.id, p)
        return (
          <GraphCard
            key={n.id}
            node={n}
            position={p}
            interactive={interactive}
            showLabel={labelNodeIds.has(n.id)}
            fade={fade}
            focused={graphFocusId === n.id}
            spinY={spinAngle}
          />
        )
      })}
    </group>
  )
}
