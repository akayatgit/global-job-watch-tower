import { useEffect, useMemo, useRef, useState } from 'react'
import { useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import * as THREE from 'three'
import { api } from '../lib/api'
import { useVigilStore } from '../store/vigilStore'

type GraphNode = {
  id: string
  kind: 'core' | 'sector' | 'city' | 'company' | 'role' | string
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
  relation: string
}

type WorldModel = {
  days: number
  window_label?: string
  stats: { jobs: number; nodes: number; edges: number; max_weight: number }
  nodes: GraphNode[]
  edges: GraphEdge[]
  hint?: string
}

const SHELL_R: Record<string, number> = {
  core: 0,
  sector: 1.55,
  role: 2.15,
  city: 2.7,
  company: 3.35,
}

const KIND_COLOR: Record<string, string> = {
  core: '#ffffff',
  sector: '#ff5500',
  city: '#00e5ff',
  company: '#ffaa00',
  role: '#ff7700',
}

function layoutNodes(nodes: GraphNode[]) {
  const byKind = new Map<string, GraphNode[]>()
  for (const n of nodes) {
    const list = byKind.get(n.kind) || []
    list.push(n)
    byKind.set(n.kind, list)
  }
  const pos = new Map<string, THREE.Vector3>()
  for (const [kind, list] of byKind) {
    const r = SHELL_R[kind] ?? 2.4
    if (kind === 'core' || r === 0) {
      pos.set(list[0].id, new THREE.Vector3(0, 0, 0))
      continue
    }
    const sorted = [...list].sort((a, b) => b.weight - a.weight)
    sorted.forEach((n, i) => {
      const t = (i / Math.max(sorted.length, 1)) * Math.PI * 2
      const wobble = (i % 3) * 0.12 - 0.12
      pos.set(
        n.id,
        new THREE.Vector3(
          Math.cos(t) * r,
          Math.sin(t * 1.7) * 0.35 + wobble,
          Math.sin(t) * r * 0.92,
        ),
      )
    })
  }
  return pos
}

function nodeRadius(n: GraphNode, maxW: number) {
  if (n.kind === 'core') return 0.22
  const t = Math.sqrt(n.weight / Math.max(maxW, 1))
  return 0.055 + t * 0.11
}

function activateNode(n: GraphNode) {
  const st = useVigilStore.getState()
  st.triggerBurst()
  if (n.kind === 'core') {
    st.openPanel('tower')
    st.setStatus('WORLD MODEL · TOWER INSIGHTS')
    return
  }
  if (n.kind === 'sector' && n.sector_id) {
    st.setSectorFilter(n.sector_id)
    st.openPanel('tower')
    st.setStatus(`SECTOR · ${n.label}`)
    return
  }
  if (n.kind === 'city' && n.city_id) {
    st.setCityFilter(n.city_id)
    st.openPanel('cities')
    st.setStatus(`CITY · ${n.label}`)
    return
  }
  if (n.kind === 'company' && n.company_id != null) {
    st.openCompanyJobs(n.company_id, n.label, 7)
    return
  }
  if (n.kind === 'role' && n.search_id != null) {
    st.openRoleHire(n.search_id, n.label, 7)
    return
  }
  st.openPanel('tower')
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
    const target = hot ? 1.35 : 1
    mesh.current.scale.lerp(new THREE.Vector3(target, target, target), 0.18)
  })

  const onOver = (e: ThreeEvent<PointerEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    setHot(true)
    document.body.style.cursor = 'pointer'
    useVigilStore.setState({
      statusLine: `${node.kind.toUpperCase()} · ${node.label} · ${node.weight}`,
    })
  }
  const onOut = () => {
    setHot(false)
    document.body.style.cursor = 'default'
  }
  const onClick = (e: ThreeEvent<MouseEvent>) => {
    if (!interactive) return
    e.stopPropagation()
    activateNode(node)
  }

  return (
    <group position={position}>
      <mesh
        ref={mesh}
        onPointerOver={onOver}
        onPointerOut={onOut}
        onClick={onClick}
      >
        <sphereGeometry args={[r, 16, 16]} />
        <meshBasicMaterial
          color={color}
          transparent
          opacity={hot ? 1 : node.kind === 'core' ? 0.95 : 0.88}
        />
      </mesh>
      {node.kind !== 'core' && (
        <mesh>
          <sphereGeometry args={[r * 1.55, 12, 12]} />
          <meshBasicMaterial
            color={color}
            transparent
            opacity={hot ? 0.22 : 0.08}
            depthWrite={false}
          />
        </mesh>
      )}
    </group>
  )
}

function EdgeLines({
  edges,
  positions,
  maxW,
}: {
  edges: GraphEdge[]
  positions: Map<string, THREE.Vector3>
  maxW: number
}) {
  const geom = useMemo(() => {
    const pts: number[] = []
    const cols: number[] = []
    const cA = new THREE.Color('#ff5500')
    const cB = new THREE.Color('#00e5ff')
    for (const e of edges) {
      const a = positions.get(e.source)
      const b = positions.get(e.target)
      if (!a || !b) continue
      pts.push(a.x, a.y, a.z, b.x, b.y, b.z)
      const t = Math.min(1, e.weight / Math.max(maxW * 0.25, 1))
      const c = cA.clone().lerp(cB, t * 0.65)
      cols.push(c.r, c.g, c.b, c.r, c.g, c.b)
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
    g.setAttribute('color', new THREE.Float32BufferAttribute(cols, 3))
    return g
  }, [edges, positions, maxW])

  return (
    <lineSegments geometry={geom}>
      <lineBasicMaterial
        vertexColors
        transparent
        opacity={0.28}
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </lineSegments>
  )
}

export function NeuralCore() {
  const [model, setModel] = useState<WorldModel | null>(null)
  const group = useRef<THREE.Group>(null)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const interactive = !focusedPanel && !trainingActive

  useEffect(() => {
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
  }, [])

  const positions = useMemo(
    () => layoutNodes(model?.nodes || []),
    [model],
  )
  const maxW = model?.stats?.max_weight || 1

  useFrame((state) => {
    if (group.current) {
      group.current.rotation.y = state.clock.elapsedTime * 0.045
    }
  })

  if (!model || model.nodes.length === 0) return null

  const satellites = model.nodes.filter((n) => n.kind !== 'core')

  return (
    <group ref={group}>
      <EdgeLines edges={model.edges} positions={positions} maxW={maxW} />
      {satellites.map((n) => {
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
      {/* Core stays the EnergyCore mesh; invisible hit target for click */}
      <mesh
        onClick={(e) => {
          if (!interactive) return
          e.stopPropagation()
          const core = model.nodes.find((n) => n.kind === 'core')
          if (core) activateNode(core)
        }}
        onPointerOver={() => {
          if (!interactive) return
          document.body.style.cursor = 'pointer'
          useVigilStore.setState({
            statusLine: `WORLD MODEL · ${model.stats.jobs} jobs · ${model.window_label || '7d'}`,
          })
        }}
        onPointerOut={() => {
          document.body.style.cursor = 'default'
        }}
      >
        <sphereGeometry args={[0.42, 16, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} />
      </mesh>
    </group>
  )
}
