import { useRef, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { useVigilStore, type PanelId } from '../store/vigilStore'

export function PanelShell({
  id,
  children,
}: {
  id: PanelId
  children: ReactNode
}) {
  const panel = useVigilStore((s) => s.panels[id])
  const focused = useVigilStore((s) => s.focusedPanel === id)
  const grabbed = useVigilStore((s) => s.grabTarget === id)
  const vigilMode = useVigilStore((s) => s.vigilMode)
  const closePanel = useVigilStore((s) => s.closePanel)
  const focusPanel = useVigilStore((s) => s.focusPanel)
  const movePanel = useVigilStore((s) => s.movePanel)
  const dragRef = useRef<{ dx: number; dy: number } | null>(null)

  if (!panel.open) return null

  const onHeaderDown = (e: ReactMouseEvent) => {
    focusPanel(id)
    if (vigilMode) return
    if ((e.target as HTMLElement).closest('button')) return
    e.preventDefault()
    dragRef.current = {
      dx: e.clientX - (panel.x / 100) * window.innerWidth,
      dy: e.clientY - (panel.y / 100) * window.innerHeight,
    }
    const onMove = (ev: globalThis.MouseEvent) => {
      if (!dragRef.current) return
      const x = ((ev.clientX - dragRef.current.dx) / window.innerWidth) * 100
      const y = ((ev.clientY - dragRef.current.dy) / window.innerHeight) * 100
      movePanel(id, Math.max(1, Math.min(70, x)), Math.max(8, Math.min(70, y)))
    }
    const onUp = () => {
      dragRef.current = null
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
  }

  return (
    <div
      className={`float-panel ${focused ? 'focused' : ''} ${grabbed ? 'grabbed' : ''}`}
      data-panel-id={id}
      style={{
        left: `${panel.x}%`,
        top: `${panel.y}%`,
        zIndex: 20 + panel.z,
        transform: `scale(${panel.scale})`,
        transformOrigin: 'top left',
      }}
      onMouseDown={() => focusPanel(id)}
    >
      <div
        className="panel-head"
        data-gesture-action={`focus-${id}`}
        onMouseDown={onHeaderDown}
        style={{ cursor: vigilMode ? 'default' : 'grab' }}
      >
        <h2>{panel.title}</h2>
        <div className="ops">
          <button
            type="button"
            data-gesture-action={`close-${id}`}
            onClick={() => closePanel(id)}
          >
            Close
          </button>
        </div>
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}
