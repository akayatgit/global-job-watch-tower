import { TowerPanel } from './TowerPanel'
import { SignalsPanel } from './SignalsPanel'
import { WatchlistPanel } from './WatchlistPanel'
import { SearchesPanel } from './SearchesPanel'
import { ActivityPanel } from './ActivityPanel'
import { JobsPanel } from './JobsPanel'
import { LivePanel } from './LivePanel'
import { HealthPanel } from './HealthPanel'
import { RoleHirePanel } from './RoleHirePanel'

export function PanelHost() {
  return (
    <div className="panel-layer">
      <TowerPanel />
      <SignalsPanel />
      <WatchlistPanel />
      <SearchesPanel />
      <ActivityPanel />
      <JobsPanel />
      <LivePanel />
      <HealthPanel />
      <RoleHirePanel />
    </div>
  )
}
