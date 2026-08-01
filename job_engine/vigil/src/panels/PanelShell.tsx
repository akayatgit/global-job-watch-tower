import type { ReactNode } from 'react'
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
  const closePanel = useVigilStore((s) => s.closePanel)
  const focusPanel = useVigilStore((s) => s.focusPanel)

  if (!panel.open) return null

  return (
    <div
      className={`float-panel ${focused ? 'focused' : ''} ${grabbed ? 'grabbed' : ''}`}
      data-panel-id={id}
      style={{
        left: `${panel.x}%`,
        top: `${panel.y}%`,
        zIndex: 20 + panel.z,
        transform: `scale(${panel.scale})`,
      }}
      onMouseDown={() => focusPanel(id)}
    >
      <div className="panel-head" data-gesture-action={`focus-${id}`}>
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
