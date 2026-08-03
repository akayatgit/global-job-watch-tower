import { stepCampusFocus } from '../scene/campusNav'
import { useVigilStore } from '../store/vigilStore'

/**
 * Large left/right openings steppers for nightlife campus.
 * Also driven by ← / → keys (wired in VigilCanvas).
 */
export function CampusFocusNav() {
  const sceneMode = useVigilStore((s) => s.sceneMode)
  const cityViewMode = useVigilStore((s) => s.cityViewMode)
  const trainingActive = useVigilStore((s) => s.trainingActive)
  const focusedPanel = useVigilStore((s) => s.focusedPanel)

  if (
    sceneMode !== 'city' ||
    cityViewMode !== 'campus' ||
    trainingActive ||
    focusedPanel
  ) {
    return null
  }

  return (
    <div className="campus-focus-nav" aria-label="Building focus">
      <button
        type="button"
        className="campus-focus-nav-btn"
        title="Previous building · lower openings (←)"
        aria-label="Previous building"
        onClick={() => stepCampusFocus('lower')}
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
          <path
            d="M15 5L8 12l7 7"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <button
        type="button"
        className="campus-focus-nav-btn"
        title="Next building · higher openings (→)"
        aria-label="Next building"
        onClick={() => stepCampusFocus('higher')}
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden>
          <path
            d="M9 5l7 7-7 7"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
    </div>
  )
}
