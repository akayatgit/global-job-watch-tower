import type { PanelId } from '../store/vigilStore'

/** Compact SVG marks for collapsed rail — glass tile hosts the glow. */
export function ModuleIcon({ id }: { id: PanelId | string }) {
  const common = {
    viewBox: '0 0 24 24',
    width: 18,
    height: 18,
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.75,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true as const,
  }
  switch (id) {
    case 'tower':
      return (
        <svg {...common}>
          <path d="M12 3v3M8 21h8M9 9h6v12H9z" />
          <path d="M9 13h6M9 17h6" />
          <circle cx="12" cy="5.5" r="1.2" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'jobs':
      return (
        <svg {...common}>
          <rect x="3" y="7" width="18" height="13" rx="2" />
          <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          <path d="M3 12h18" />
        </svg>
      )
    case 'signals':
      return (
        <svg {...common}>
          <path d="M4 14c2-4 4-6 8-6s6 2 8 6" />
          <path d="M7 17c1.5-2.5 3-3.5 5-3.5s3.5 1 5 3.5" />
          <circle cx="12" cy="19" r="1.2" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'cities':
      return (
        <svg {...common}>
          <path d="M12 21s-7-5.2-7-11a7 7 0 1 1 14 0c0 5.8-7 11-7 11z" />
          <circle cx="12" cy="10" r="2.2" />
        </svg>
      )
    case 'filter_mix':
      return (
        <svg {...common}>
          <path d="M4 6h16M7 12h10M10 18h4" />
          <circle cx="9" cy="6" r="1.6" fill="currentColor" stroke="none" />
          <circle cx="15" cy="12" r="1.6" fill="currentColor" stroke="none" />
        </svg>
      )
    case 'searches':
      return (
        <svg {...common}>
          <circle cx="11" cy="11" r="6.5" />
          <path d="M16 16l4.5 4.5" />
        </svg>
      )
    case 'activity':
      return (
        <svg {...common}>
          <path d="M4 14h3l2-6 3 10 2-4h6" />
        </svg>
      )
    case 'live':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" />
          <path d="M7.5 7.5a6.5 6.5 0 0 0 0 9M16.5 7.5a6.5 6.5 0 0 1 0 9" />
          <path d="M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14" />
        </svg>
      )
    case 'health':
      return (
        <svg {...common}>
          <path d="M12 21s-7-4.4-7-10a4.5 4.5 0 0 1 7-3.7A4.5 4.5 0 0 1 19 11c0 5.6-7 10-7 10z" />
        </svg>
      )
    case 'ask':
      return (
        <svg {...common}>
          <path d="M5 18v-9a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v5a4 4 0 0 1-4 4H9l-4 3z" />
          <path d="M10 10h.01M14 10h.01M10 13.5c.8.7 3.2.7 4 0" />
        </svg>
      )
    case 'watchlist':
      return (
        <svg {...common}>
          <path d="M12 4l2.2 4.5 5 .7-3.6 3.5.9 5L12 15.5 7.5 17.7l.9-5L4.8 9.2l5-.7z" />
        </svg>
      )
    default:
      return (
        <svg {...common}>
          <rect x="5" y="5" width="14" height="14" rx="2" />
        </svg>
      )
  }
}

export function IconBrowser({ hidden }: { hidden: boolean }) {
  const common = {
    viewBox: '0 0 24 24',
    width: 18,
    height: 18,
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true as const,
  }
  if (hidden) {
    return (
      <svg {...common}>
        <path d="M3 3l18 18" />
        <path d="M10.6 10.7a2 2 0 0 0 2.7 2.7" />
        <path d="M9.4 5.3A10.8 10.8 0 0 1 12 5c5.5 0 9.5 4.5 10.5 7-.4 1-1.2 2.3-2.4 3.5M6.1 6.1C4.2 7.5 2.8 9.3 2 12c1 2.5 5 7 10 7 1.4 0 2.7-.3 3.9-.8" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

export function IconTrain() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M8 11c0-3 1.5-5 4-5s4 2 4 5v5H8v-5z" />
      <path d="M8 16l-3 3M16 16l3 3" />
      <path d="M10 8.5h4" />
      <circle cx="10" cy="12" r="0.8" fill="currentColor" stroke="none" />
      <circle cx="14" cy="12" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function IconVigil({ on }: { on: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {on ? (
        <>
          <path d="M8 13v-2a4 4 0 0 1 8 0v2" />
          <path d="M7 13h10v5a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-5z" />
          <path d="M12 16v1" />
        </>
      ) : (
        <>
          <path d="M8 11V9a4 4 0 0 1 7.5-2" />
          <path d="M16 11v2M7 13h10v5a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-5z" />
          <path d="M3 3l18 18" />
        </>
      )}
    </svg>
  )
}
