import { ORBIT_NODES, useVigilStore, type PanelId } from '../store/vigilStore'
import { sendUltron } from '../lib/ultronWs'
import { ModuleIcon } from './ModuleIcons'

/** Left module rail — separate from the floating widget canvas; hide/show anytime. */
export function ModuleDock() {
  const openPanel = useVigilStore((s) => s.openPanel)
  const focused = useVigilStore((s) => s.focusedPanel)
  const panels = useVigilStore((s) => s.panels)
  const railOpen = useVigilStore((s) => s.railOpen)
  const setRailOpen = useVigilStore((s) => s.setRailOpen)
  const togglePin = useVigilStore((s) => s.togglePin)

  const launch = (id: PanelId) => {
    openPanel(id)
    sendUltron({ type: 'ultron.command', command: 'open_panel', panel: id })
  }

  return (
    <aside
      className={`module-rail interactive ${railOpen ? 'open' : 'collapsed'}`}
      aria-label="Module rail"
    >
      <div className="rail-head">
        {railOpen ? <span className="rail-title">Modules</span> : null}
        <button
          type="button"
          className="rail-toggle"
          data-gesture-action="rail-toggle"
          title={railOpen ? 'Hide module rail' : 'Show module rail'}
          aria-expanded={railOpen}
          onClick={() => setRailOpen(!railOpen)}
        >
          {railOpen ? '⟨' : '⟩'}
        </button>
      </div>

      <nav className="rail-nav">
        {ORBIT_NODES.map((node) => {
          const open = panels[node.id]?.open
          const pinned = panels[node.id]?.pinned
          const active = node.id === focused || open
          return (
            <div
              key={node.id}
              className={`rail-row ${active ? 'active' : ''} ${pinned ? 'pinned' : ''}`}
            >
              <button
                type="button"
                className={`rail-chip ${railOpen ? '' : 'glass-tile'}`.trim()}
                data-gesture-action={`dock-${node.id}`}
                title={pinned ? `${node.label} · pinned on canvas` : `Open ${node.label}`}
                aria-label={node.label}
                onClick={() => launch(node.id)}
              >
                <span className="rail-chip-icon" aria-hidden>
                  <ModuleIcon id={node.id} />
                </span>
                {railOpen ? (
                  <span className="rail-chip-label">{node.label}</span>
                ) : null}
                {railOpen && pinned ? (
                  <span className="rail-pin-dot" aria-hidden>·</span>
                ) : null}
                {!railOpen && pinned ? (
                  <span className="rail-pin-spark" aria-hidden />
                ) : null}
              </button>
              {railOpen ? (
                <button
                  type="button"
                  className={`rail-pin-btn ${pinned ? 'active' : ''}`}
                  data-gesture-action={`rail-pin-${node.id}`}
                  title={pinned ? `Unpin ${node.label}` : `Pin ${node.label} on canvas`}
                  onClick={() => togglePin(node.id)}
                >
                  {pinned ? 'Unpin' : 'Pin'}
                </button>
              ) : null}
            </div>
          )
        })}
      </nav>
    </aside>
  )
}
