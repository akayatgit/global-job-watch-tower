import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Html, Line } from '@react-three/drei'
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

function nodeRadius(n: GraphNode, maxW: number) {
  const t = Math.sqrt(n.weight / Math.max(maxW, 1))
  return 0.05 + t * 0.1
}

function activateNode(n: GraphNode) {
  const st = useVigilStore.getState()
  st.triggerBurst()
  if (n.kind === 'sector' && n.sector_id) {
    st.setSectorFilter(n.sector_id)
    st.openPanel('tower')
    st.setStatus(`GRAPH · ${n.label}`)
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

function GraphNodeMesh({
  node,
  position,
  maxW,
  interactive,
  showLabel,
}: {
  node: GraphNode
  position: THREE.Vector3
  maxW: number
  interactive: boolean
  showLabel: boolean
}) {
  const mesh = useRef<THREE.Mesh>(null)
  const [hot, setHot] = useState(false)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  const r = nodeRadius(node, maxW)

  useFrame(() => {
    if (!mesh.current) return
    const s = hot ? 1.28 : 1
    mesh.current.scale.setScalar(
      THREE.MathUtils.lerp(mesh.current.scale.x, s, 0.2),
    )
  })

  return (
    <group position={position}>
      <mesh
        ref={mesh}
        onPointerOver={(e: ThreeEvent<PointerEvent>) => {
          if (!interactive) return
          e.stopPropagation()
          setHot(true)
          document.body.style.cursor = 'pointer'
          useVigilStore.setState({
            statusLine: `${node.kind.toUpperCase()} · ${node.label} · ${node.weight}`,
          })
        }}
        onPointerOut={() => {
          setHot(false)
          document.body.style.cursor = 'default'
        }}
        onClick={(e: ThreeEvent<MouseEvent>) => {
          if (!interactive) return
          e.stopPropagation()
          activateNode(node)
        }}
      >
        <sphereGeometry args={[r, 20, 20]} />
        <meshBasicMaterial color={color} transparent opacity={hot ? 1 : 0.92} />
      </mesh>
      {showLabel && (
        <Html
          center
          distanceFactor={8}
          style={{ pointerEvents: 'none' }}
          zIndexRange={[20, 0]}
        >
          <div className={`vigil-tag vigil-tag-${node.kind}${hot ? ' hot' : ''}`}>
            <span className="vigil-tag-name">{node.label}</span>
            <span className="vigil-tag-meta">{node.weight}</span>
          </div>
        </Html>
      )}
    </group>
  )
}

export function NeuralCore() {
  const [model, setModel] = useState<WorldModel | null>(null)
  const group = useRef<THREE.Group>(null)
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const interactive = sceneMode === 'graph' && !focusedPanel && !trainingActive

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

  const dataNodes = useMemo(
    () => (model?.nodes || []).filter((n) => n.kind !== 'core'),
    [model],
  )
  const positions = useMemo(() => layoutNodes(dataNodes), [dataNodes])
  const maxW = model?.stats?.max_weight || 1

  const edgeLines = useMemo(() => {
    if (!model) return [] as {
      key: string
      points: [number, number, number][]
      mid: THREE.Vector3
      label: string
      weight: number
    }[]
    const out: {
      key: string
      points: [number, number, number][]
      mid: THREE.Vector3
      label: string
      weight: number
    }[] = []
    const sorted = [...model.edges]
      .filter((e) => e.source !== 'core' && !e.target.startsWith('core'))
      .sort((a, b) => b.weight - a.weight)
    for (const e of sorted) {
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
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
      })
      if (out.length >= 70) break
    }
    return out
  }, [model, positions])

  // Label strongest nodes + top edge labels only (readable, not spam)
  const labelNodeIds = useMemo(() => {
    const top = [...dataNodes].sort((a, b) => b.weight - a.weight).slice(0, 22)
    return new Set(top.map((n) => n.id))
  }, [dataNodes])

  if (sceneMode !== 'graph' || !model || dataNodes.length === 0) return null

  return (
    <group ref={group}>
      {edgeLines.map((e) => (
        <group key={e.key}>
          <Line
            points={e.points}
            color="#ff5500"
            transparent
            opacity={0.3}
            lineWidth={1.2}
            depthWrite={false}
          />
          {e.weight >= 8 && (
            <Html
              position={e.mid}
              center
              distanceFactor={10}
              style={{ pointerEvents: 'none' }}
              zIndexRange={[10, 0]}
            >
              <div className="vigil-tag vigil-tag-edge">
                {e.label} · {e.weight}
              </div>
            </Html>
          )}
        </group>
      ))}
      {dataNodes.map((n) => {
        const p = positions.get(n.id)
        if (!p) return null
        return (
          <GraphNodeMesh
            key={n.id}
            node={n}
            position={p}
            maxW={maxW}
            interactive={interactive}
            showLabel={labelNodeIds.has(n.id)}
          />
        )
      })}
    </group>
  )
}
