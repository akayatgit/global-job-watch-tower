import { useVigilStore } from '../store/vigilStore'

export function FingerOverlay() {
  const index = useVigilStore((s) => s.smoothIndex)
  const thumb = useVigilStore((s) => s.smoothThumb)
  const press = useVigilStore((s) => s.pressProgress)
  const magnet = useVigilStore((s) => s.magnet)
  const hands = useVigilStore((s) => s.hands)
  const pinch = Boolean((hands.right || hands.left)?.pinch)

  const ix = index.x * 100
  const iy = index.y * 100
  const tx = thumb.x * 100
  const ty = thumb.y * 100

  return (
    <div className="finger-layer">
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        {magnet && (
          <line
            x1={ix}
            y1={iy}
            x2={magnet.x * 100}
            y2={magnet.y * 100}
            stroke="rgba(255,170,0,0.45)"
            strokeWidth="0.15"
            strokeDasharray="0.8 0.6"
          />
        )}
        <line
          x1={ix}
          y1={iy}
          x2={tx}
          y2={ty}
          stroke={pinch ? '#ffffff' : 'rgba(255,85,0,0.55)'}
          strokeWidth={pinch ? 0.28 : 0.12}
        />
        {/* Thumb */}
        <circle cx={tx} cy={ty} r="0.9" fill="none" stroke="#cc1100" strokeWidth="0.2" />
        <circle cx={tx} cy={ty} r="0.25" fill="#cc1100" />
        {/* Index */}
        <circle
          cx={ix}
          cy={iy}
          r="1.4"
          fill="none"
          stroke="#ffaa00"
          strokeWidth="0.22"
          opacity="0.95"
        />
        <circle cx={ix} cy={iy} r="0.3" fill="#ffffff" />
        <line x1={ix - 2} y1={iy} x2={ix - 1.1} y2={iy} stroke="#ffaa00" strokeWidth="0.15" />
        <line x1={ix + 1.1} y1={iy} x2={ix + 2} y2={iy} stroke="#ffaa00" strokeWidth="0.15" />
        <line x1={ix} y1={iy - 2} x2={ix} y2={iy - 1.1} stroke="#ffaa00" strokeWidth="0.15" />
        <line x1={ix} y1={iy + 1.1} x2={ix} y2={iy + 2} stroke="#ffaa00" strokeWidth="0.15" />
        {/* Press progress */}
        {press > 0 && (
          <circle
            cx={ix}
            cy={iy}
            r={1.8 + press * 1.2}
            fill="none"
            stroke="#ffffff"
            strokeWidth="0.25"
            strokeDasharray={`${press * 12} 12`}
            opacity={0.9}
          />
        )}
      </svg>
    </div>
  )
}
