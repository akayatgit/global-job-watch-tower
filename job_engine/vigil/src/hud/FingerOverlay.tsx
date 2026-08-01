import { useVigilStore } from '../store/vigilStore'

function HandGuides({
  index,
  thumb,
  pinch,
  color,
  thumbColor,
  label,
}: {
  index: { x: number; y: number }
  thumb: { x: number; y: number }
  pinch: boolean
  color: string
  thumbColor: string
  label: string
}) {
  const ix = index.x * 100
  const iy = index.y * 100
  const tx = thumb.x * 100
  const ty = thumb.y * 100
  return (
    <g>
      <line
        x1={ix}
        y1={iy}
        x2={tx}
        y2={ty}
        stroke={pinch ? '#ffffff' : color}
        strokeWidth={pinch ? 0.28 : 0.12}
        opacity={0.9}
      />
      <circle cx={tx} cy={ty} r="0.85" fill="none" stroke={thumbColor} strokeWidth="0.2" />
      <circle cx={tx} cy={ty} r="0.22" fill={thumbColor} />
      <circle cx={ix} cy={iy} r="1.35" fill="none" stroke={color} strokeWidth="0.22" />
      <circle cx={ix} cy={iy} r="0.28" fill="#ffffff" />
      <line x1={ix - 1.9} y1={iy} x2={ix - 1.05} y2={iy} stroke={color} strokeWidth="0.14" />
      <line x1={ix + 1.05} y1={iy} x2={ix + 1.9} y2={iy} stroke={color} strokeWidth="0.14" />
      <line x1={ix} y1={iy - 1.9} x2={ix} y2={iy - 1.05} stroke={color} strokeWidth="0.14" />
      <line x1={ix} y1={iy + 1.05} x2={ix} y2={iy + 1.9} stroke={color} strokeWidth="0.14" />
      <text
        x={ix + 2.2}
        y={iy - 1.6}
        fill={color}
        fontSize="1.6"
        fontFamily="Orbitron, sans-serif"
        opacity="0.85"
      >
        {label}
      </text>
    </g>
  )
}

export function FingerOverlay() {
  const index = useVigilStore((s) => s.smoothIndex)
  const thumb = useVigilStore((s) => s.smoothThumb)
  const leftIndex = useVigilStore((s) => s.smoothLeftIndex)
  const leftThumb = useVigilStore((s) => s.smoothLeftThumb)
  const leftVisible = useVigilStore((s) => s.leftHandVisible)
  const press = useVigilStore((s) => s.pressProgress)
  const magnet = useVigilStore((s) => s.magnet)
  const hands = useVigilStore((s) => s.hands)
  const mode = useVigilStore((s) => s.gestureMode)
  const rightPinch = Boolean(hands.right?.pinch)
  const leftPinch = Boolean(hands.left?.pinch)

  const ix = index.x * 100
  const iy = index.y * 100

  const fist = Boolean(hands.right?.fist || hands.left?.fist)
  const anyHand = Boolean(hands.right || hands.left)

  return (
    <div className={`finger-layer ${anyHand ? 'hand-live' : ''}`}>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none">
        {/* Soft spotlight under the primary fingertip */}
        {anyHand && (
          <circle
            cx={ix}
            cy={iy}
            r="6.5"
            fill={fist ? 'rgba(239,68,68,0.18)' : 'rgba(255,170,0,0.14)'}
          />
        )}
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
        {/* Both hands: L cyan + R amber. Left-only: one big cyan L (primary cursor). */}
        {hands.right && leftVisible && hands.left && (
          <HandGuides
            index={leftIndex}
            thumb={leftThumb}
            pinch={leftPinch}
            color="#22d3ee"
            thumbColor="#0891b2"
            label="L"
          />
        )}
        {hands.right && (
          <HandGuides
            index={index}
            thumb={thumb}
            pinch={rightPinch || fist}
            color={fist ? '#ef4444' : '#ffaa00'}
            thumbColor={fist ? '#991b1b' : '#cc1100'}
            label={fist ? 'FIST' : 'R'}
          />
        )}
        {!hands.right && hands.left && (
          <HandGuides
            index={index}
            thumb={thumb}
            pinch={leftPinch || fist}
            color={fist ? '#ef4444' : '#22d3ee'}
            thumbColor={fist ? '#991b1b' : '#0891b2'}
            label={fist ? 'FIST' : 'L'}
          />
        )}
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
        {hands.twoHandPinch && hands.left?.centroid && hands.right?.centroid && (
          <line
            x1={hands.left.centroid.x * 100}
            y1={hands.left.centroid.y * 100}
            x2={hands.right.centroid.x * 100}
            y2={hands.right.centroid.y * 100}
            stroke="#a78bfa"
            strokeWidth="0.35"
            strokeDasharray="1 0.5"
          />
        )}
      </svg>
      {mode !== 'none' && (
        <div className="gesture-mode-badge">{mode.replace('_', ' ').toUpperCase()}</div>
      )}
    </div>
  )
}
