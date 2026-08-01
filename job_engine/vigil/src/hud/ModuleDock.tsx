import { ORBIT_NODES, useVigilStore, type PanelId } from '../store/vigilStore'
import { sendUltron } from '../lib/ultronWs'

/** Clickable module launcher — primary nav in desktop mode; still available in VIGIL mode. */
export function ModuleDock() {
  const openPanel = useVigilStore((s) => s.openPanel)
  const focused = useVigilStore((s) => s.focusedPanel)
  const panels = useVigilStore((s) => s.panels)

  const launch = (id: PanelId | 'remote') => {
    if (id === 'remote') {
      openPanel('jobs')
      useVigilStore.getState().setStatus('REMOTE TRENDS → JOBS')
      sendUltron({ type: 'ultron.command', command: 'open_panel', panel: 'jobs' })
      return
    }
    openPanel(id)
    sendUltron({ type: 'ultron.command', command: 'open_panel', panel: id })
  }

  return (
    <div className="module-dock interactive">
      {ORBIT_NODES.map((node) => {
        const open = node.id !== 'remote' && panels[node.id as PanelId]?.open
        const active = node.id === focused || open
        return (
          <button
            key={node.id}
            type="button"
            className={`dock-chip ${active ? 'active' : ''}`}
            data-gesture-action={`dock-${node.id}`}
            onClick={() => launch(node.id)}
          >
            {node.label}
          </button>
        )
      })}
    </div>
  )
}
