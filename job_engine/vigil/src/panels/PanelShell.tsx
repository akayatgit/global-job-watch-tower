import { useRef, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { IconClose, IconPin } from '../hud/ModuleIcons'
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
  const resizePanel = useVigilStore((s) => s.resizePanel)
  const togglePin = useVigilStore((s) => s.togglePin)
  const dragRef = useRef<{ dx: number; dy: number } | null>(null)
  const resizeRef = useRef<{
    startX: number
    startY: number
    startW: number
    startH: number
    stageW: number
    stageH: number
  } | null>(null)

  if (!panel.open) return null

  const pinnable = PINNABLE_PANELS.includes(id)
  // Pinned dashboard widgets stay sharp + usable while you work another window
  const layerDimmed = Boolean(focusedPanel && !focused && !panel.pinned)
  const handHot =
    hoverTarget === `panel:${id}` ||
    hoverTarget === `body:${id}` ||
    Boolean(hoverTarget?.includes(`close-${id}`)) ||
    Boolean(hoverTarget?.includes(`pin-${id}`))

  const stageEl = () =>
    document.querySelector('.vigil-stage') as HTMLElement | null

  const onHeaderDown = (e: ReactMouseEvent) => {
    focusPanel(id)
    if (vigilMode) return
    if ((e.target as HTMLElement).closest('button')) return
    e.preventDefault()
    const stage = stageEl()
    const sw = stage?.clientWidth || window.innerWidth
    const sh = stage?.clientHeight || window.innerHeight
    const stageLeft = stage?.getBoundingClientRect().left ?? 0
    const stageTop = stage?.getBoundingClientRect().top ?? 0
    // panel.x/y are the center of the window within the stage
    dragRef.current = {
      dx: e.clientX - stageLeft - (panel.x / 100) * sw,
      dy: e.clientY - stageTop - (panel.y / 100) * sh,
    }
    const onMove = (ev: globalThis.MouseEvent) => {
      if (!dragRef.current) return
      const st = stageEl()
      const w = st?.clientWidth || window.innerWidth
      const h = st?.clientHeight || window.innerHeight
      const left = st?.getBoundingClientRect().left ?? 0
      const top = st?.getBoundingClientRect().top ?? 0
      const x = ((ev.clientX - left - dragRef.current.dx) / w) * 100
      const y = ((ev.clientY - top - dragRef.current.dy) / h) * 100
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

  const onResizeDown = (e: ReactMouseEvent) => {
    focusPanel(id)
    if (vigilMode) return
    e.preventDefault()
    e.stopPropagation()
    const stage = stageEl()
    resizeRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startW: panel.w,
      startH: panel.h,
      stageW: stage?.clientWidth || window.innerWidth,
      stageH: stage?.clientHeight || window.innerHeight,
    }
    const onMove = (ev: globalThis.MouseEvent) => {
      const r = resizeRef.current
      if (!r) return
      const dw = ((ev.clientX - r.startX) / r.stageW) * 100
      const dh = ((ev.clientY - r.startY) / r.stageH) * 100
      resizePanel(id, r.startW + dw, r.startH + dh, { anchor: 'se' })
    }
    const onUp = () => {
      resizeRef.current = null
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
        width: `${panel.w}%`,
        height: `${panel.h}%`,
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
          {panel.pinned ? (
            <span className="pin-badge" title="Pinned on dashboard" aria-label="Pinned">
              <IconPin filled size={11} />
            </span>
          ) : null}
        </h2>
        <div className="ops">
          {pinnable && (
            <button
              type="button"
              className={`icon-ops-btn pin-btn ${panel.pinned ? 'active' : ''}`}
              data-gesture-action={`pin-${id}`}
              aria-label={panel.pinned ? 'Unpin from dashboard' : 'Pin to dashboard'}
              title={panel.pinned ? 'Unpin from dashboard' : 'Pin to dashboard'}
              onClick={() => togglePin(id)}
            >
              <IconPin filled={panel.pinned} />
            </button>
          )}
          <button
            type="button"
            className="icon-ops-btn close-btn"
            data-gesture-action={`close-${id}`}
            aria-label="Close"
            title="Close"
            onClick={() => closePanel(id)}
          >
            <IconClose />
          </button>
        </div>
      </div>
      <div className="panel-body" data-panel-body={id}>
        {children}
      </div>
      {!vigilMode ? (
        <button
          type="button"
          className="panel-resize-handle"
          aria-label="Resize window"
          title="Drag to resize"
          onMouseDown={onResizeDown}
        />
      ) : null}
    </div>
  )
}
