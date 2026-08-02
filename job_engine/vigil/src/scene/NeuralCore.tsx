import { useEffect, useMemo, useRef, useState } from 'react'
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

/** Focus + depth-1 + depth-2 neighbors */
function neighborhood(
  focusId: string,
  adj: Map<string, Set<string>>,
): Set<string> {
  const out = new Set<string>([focusId])
  const d1 = adj.get(focusId) || new Set()
  for (const n of d1) out.add(n)
  for (const n of d1) {
    for (const m of adj.get(n) || []) out.add(m)
  }
  return out
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
  dimmed,
  focused,
}: {
  node: GraphNode
  position: THREE.Vector3
  interactive: boolean
  showLabel: boolean
  dimmed: boolean
  focused: boolean
}) {
  const [hot, setHot] = useState(false)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  const cardW = 0.72
  const cardH = 0.28

  const onEnter = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive || dimmed) return
    e.stopPropagation()
    setHot(true)
    document.body.style.cursor = 'pointer'
    useVigilStore.setState({
      statusLine: focused
        ? `FOCUSED · click again to open · ${node.label}`
        : `${node.kind.toUpperCase()} · ${node.label} · ${node.weight}`,
    })
  }
  const onLeave = () => {
    setHot(false)
    document.body.style.cursor = 'default'
  }
  const onCardClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive || dimmed) return
    e.stopPropagation()
    const st = useVigilStore.getState()
    // First click = local focus; second click on same card = open panel
    if (st.graphFocusId !== node.id) {
      st.setGraphFocusId(node.id)
      st.setSceneSpin(false)
      st.setStatus(`LOCAL · ${node.label} (depth 2) · click card again to open`)
      return
    }
    openInsight(node)
  }

  const opacity = dimmed ? 0.12 : hot || focused ? 1 : 0.92

  return (
    <group position={position}>
      {/* Fat invisible pick sphere — never rely on text */}
      <mesh
        onPointerOver={onEnter}
        onPointerOut={onLeave}
        onClick={onCardClick}
      >
        <sphereGeometry args={[0.28, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>

      {/* Visible node */}
      <mesh>
        <sphereGeometry args={[focused ? 0.12 : 0.08, 20, 20]} />
        <meshBasicMaterial color={color} transparent opacity={opacity} />
      </mesh>

      {/* Clickable CARD plate (UX: big target) + non-interactive label */}
      {showLabel && (
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
              opacity={dimmed ? 0.08 : 0.92}
              depthWrite={false}
            />
          </mesh>
          {/* Card rim */}
          <mesh position={[0, 0.22, -0.001]}>
            <planeGeometry args={[cardW + 0.03, cardH + 0.03]} />
            <meshBasicMaterial
              color={color}
              transparent
              opacity={dimmed ? 0.05 : hot || focused ? 0.85 : 0.45}
              depthWrite={false}
            />
          </mesh>
          <Html
            position={[0, 0.22, 0.01]}
            center
            distanceFactor={6.5}
            style={{ pointerEvents: 'none' }}
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

  // Clear focus when leaving graph mode
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
  const adj = useMemo(
    () => buildAdj(model?.edges || []),
    [model],
  )
  const localSet = useMemo(() => {
    if (!graphFocusId) return null
    return neighborhood(graphFocusId, adj)
  }, [graphFocusId, adj])

  const edgeLines = useMemo(() => {
    if (!model) return [] as {
      key: string
      points: [number, number, number][]
      mid: THREE.Vector3
      label: string
      weight: number
      dimmed: boolean
    }[]
    const out: {
      key: string
      points: [number, number, number][]
      mid: THREE.Vector3
      label: string
      weight: number
      dimmed: boolean
    }[] = []
    const sorted = [...model.edges]
      .filter((e) => e.source !== 'core' && e.target !== 'core')
      .sort((a, b) => b.weight - a.weight)
    for (const e of sorted) {
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
      const dimmed = Boolean(
        localSet && (!localSet.has(e.source) || !localSet.has(e.target)),
      )
      if (localSet && dimmed) continue // hide edges outside neighborhood
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
        dimmed: false,
      })
      if (out.length >= 80) break
    }
    return out
  }, [model, positions, localSet])

  const labelNodeIds = useMemo(() => {
    if (localSet) return localSet
    const top = [...dataNodes].sort((a, b) => b.weight - a.weight).slice(0, 22)
    return new Set(top.map((n) => n.id))
  }, [dataNodes, localSet])

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
            opacity={0.35}
            lineWidth={1.35}
            depthWrite={false}
          />
          {e.weight >= 10 && (
            <Html
              position={e.mid}
              center
              distanceFactor={10}
              style={{ pointerEvents: 'none' }}
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
        const dimmed = Boolean(localSet && !localSet.has(n.id))
        if (dimmed) return null // hide outside neighborhood — clean Obsidian local graph
        return (
          <GraphCard
            key={n.id}
            node={n}
            position={p}
            interactive={interactive}
            showLabel={labelNodeIds.has(n.id)}
            dimmed={false}
            focused={graphFocusId === n.id}
          />
        )
      })}
    </group>
  )
}
