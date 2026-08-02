import { useRef, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { PINNABLE_PANELS, useVigilStore, type PanelId } from '../store/vigilStore'

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
  const focusedPanel = useVigilStore((s) => s.focusedPanel)
  const hoverTarget = useVigilStore((s) => s.hoverTarget)
  const closePanel = useVigilStore((s) => s.closePanel)
  const focusPanel = useVigilStore((s) => s.focusPanel)
  const movePanel = useVigilStore((s) => s.movePanel)
  const togglePin = useVigilStore((s) => s.togglePin)
  const dragRef = useRef<{ dx: number; dy: number } | null>(null)

  if (!panel.open) return null

  const pinnable = PINNABLE_PANELS.includes(id)
  // Pinned dashboard widgets stay sharp + usable while you work another window
  const layerDimmed = Boolean(focusedPanel && !focused && !panel.pinned)
  const handHot =
    hoverTarget === `panel:${id}` ||
    hoverTarget === `body:${id}` ||
    Boolean(hoverTarget?.includes(`close-${id}`)) ||
    Boolean(hoverTarget?.includes(`pin-${id}`))

  const onHeaderDown = (e: ReactMouseEvent) => {
    focusPanel(id)
    if (vigilMode) return
    if ((e.target as HTMLElement).closest('button')) return
    e.preventDefault()
    // panel.x/y are the center of the window
    dragRef.current = {
      dx: e.clientX - (panel.x / 100) * window.innerWidth,
      dy: e.clientY - (panel.y / 100) * window.innerHeight,
    }
    const onMove = (ev: globalThis.MouseEvent) => {
      if (!dragRef.current) return
      const x = ((ev.clientX - dragRef.current.dx) / window.innerWidth) * 100
      const y = ((ev.clientY - dragRef.current.dy) / window.innerHeight) * 100
      movePanel(id, x, y)
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
      className={`float-panel ${focused ? 'focused' : ''} ${grabbed ? 'grabbed' : ''} ${layerDimmed ? 'layer-dimmed' : ''} ${handHot ? 'hand-hot' : ''} ${panel.pinned ? 'pinned' : ''}`}
      data-panel-id={id}
      style={{
        left: `${panel.x}%`,
        top: `${panel.y}%`,
        zIndex: panel.z,
        transform: `translate(-50%, -50%) scale(${panel.scale})`,
        transformOrigin: 'center center',
      }}
      onMouseDown={() => focusPanel(id)}
    >
      <div
        className="panel-head"
        data-gesture-action={`focus-${id}`}
        onMouseDown={onHeaderDown}
        style={{ cursor: vigilMode ? 'default' : 'grab' }}
      >
        <h2>
          {panel.title}
          {panel.pinned ? <span className="pin-badge">Pinned</span> : null}
        </h2>
        <div className="ops">
          {pinnable && (
            <button
              type="button"
              className={panel.pinned ? 'pin-btn active' : 'pin-btn'}
              data-gesture-action={`pin-${id}`}
              title={
                id === 'tower'
                  ? 'Tower Insights stays pinned on the right'
                  : panel.pinned
                    ? 'Unpin from dashboard'
                    : 'Pin to dashboard'
              }
              onClick={() => togglePin(id)}
            >
              {id === 'tower' ? 'Pinned' : panel.pinned ? 'Unpin' : 'Pin'}
            </button>
          )}
          <button
            type="button"
            data-gesture-action={`close-${id}`}
            onClick={() => closePanel(id)}
            title={
              id === 'tower' && panel.pinned
                ? 'Tower stays pinned — snaps back to the right'
                : 'Close'
            }
          >
            Close
          </button>
        </div>
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}
