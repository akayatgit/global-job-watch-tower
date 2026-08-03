import { TowerPanel } from './TowerPanel'
import { SignalsPanel } from './SignalsPanel'
import { WatchlistPanel } from './WatchlistPanel'
import { SearchesPanel } from './SearchesPanel'
import { ActivityPanel } from './ActivityPanel'
import { JobsPanel } from './JobsPanel'
import { LivePanel } from './LivePanel'
import { HealthPanel } from './HealthPanel'
import { RoleHirePanel } from './RoleHirePanel'
import { RankListPanel } from './RankListPanel'
import { AskPanel } from './AskPanel'
import { FilterMixPanel } from './FilterMixPanel'
import { CitiesPanel } from './CitiesPanel'
import { DirectorTracePanel } from './DirectorTracePanel'

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
      <AskPanel />
      <FilterMixPanel />
      <CitiesPanel />
      <DirectorTracePanel />
      <RoleHirePanel />
      <RankListPanel />
    </div>
  )
}
