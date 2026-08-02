import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { Line } from '@react-three/drei'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

/**
 * Obsidian-style knowledge graph mode — separate from the particle singularity.
 * Lessons applied: color by kind (groups), smaller nodes, no dual halos,
 * progressive clusters, edges as soft single strokes (not angled hairlines).
 */

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

/** Cluster centers — Obsidian neighborhoods, not rings around the core */
const CLUSTER: Record<string, THREE.Vector3> = {
  sector: new THREE.Vector3(-1.8, 0.4, 0.2),
  role: new THREE.Vector3(0.2, 1.6, -0.4),
  city: new THREE.Vector3(1.9, 0.2, 0.5),
  company: new THREE.Vector3(0.1, -1.7, 0.3),
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
    const center = CLUSTER[kind] || new THREE.Vector3(0, 0, 0)
    const sorted = [...list].sort((a, b) => b.weight - a.weight)
    const n = sorted.length
    sorted.forEach((node, i) => {
      const a = (i / Math.max(n, 1)) * Math.PI * 2 + kind.length * 0.2
      const spread = 0.55 + Math.min(n, 12) * 0.04
      const r = spread * (0.45 + (i % 5) * 0.12)
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
  return 0.045 + t * 0.09
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
}: {
  node: GraphNode
  position: THREE.Vector3
  maxW: number
  interactive: boolean
}) {
  const mesh = useRef<THREE.Mesh>(null)
  const [hot, setHot] = useState(false)
  const color = KIND_COLOR[node.kind] || '#ff5500'
  const r = nodeRadius(node, maxW)

  useFrame(() => {
    if (!mesh.current) return
    const s = hot ? 1.25 : 1
    mesh.current.scale.setScalar(
      THREE.MathUtils.lerp(mesh.current.scale.x, s, 0.2),
    )
  })

  return (
    <mesh
      ref={mesh}
      position={position}
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
    if (!model) return [] as { key: string; points: [number, number, number][] }[]
    const out: { key: string; points: [number, number, number][] }[] = []
    for (const e of model.edges) {
      if (e.source === 'core' || e.target.startsWith('core')) continue
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
      // Midpoint lift for a gentle curve feel (3-point polyline)
      const mid = a.clone().lerp(b, 0.5)
      mid.y += 0.12
      out.push({
        key: `${e.source}->${e.target}`,
        points: [
          [a.x, a.y, a.z],
          [mid.x, mid.y, mid.z],
          [b.x, b.y, b.z],
        ],
      })
      if (out.length >= 80) break
    }
    return out
  }, [model, positions])

  useFrame((state) => {
    if (group.current && sceneMode === 'graph') {
      group.current.rotation.y = state.clock.elapsedTime * 0.03
    }
  })

  if (sceneMode !== 'graph' || !model || dataNodes.length === 0) return null

  return (
    <group ref={group} position={[0, 0, 0]}>
      {edgeLines.map((e) => (
        <Line
          key={e.key}
          points={e.points}
          color="#ff5500"
          transparent
          opacity={0.32}
          lineWidth={1.25}
          depthWrite={false}
        />
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
          />
        )
      })}
    </group>
  )
}
