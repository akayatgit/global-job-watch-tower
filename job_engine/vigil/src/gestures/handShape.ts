/** MediaPipe hand-landmark helpers for VIGIL gestures. */

export function pinchDistance(
  lms: { x: number; y: number; z: number }[],
): number {
  const thumb = lms[4]
  const index = lms[8]
  return Math.hypot(thumb.x - index.x, thumb.y - index.y)
}

/** Five digits curled toward palm — fist / close-all-fingers. */
export function isFist(lms: { x: number; y: number; z: number }[]): boolean {
  const wrist = lms[0]
  const tips = [8, 12, 16, 20] as const
  const mcps = [5, 9, 13, 17] as const
  let curled = 0
  for (let i = 0; i < 4; i++) {
    const tip = lms[tips[i]]
    const mcp = lms[mcps[i]]
    const tipDist = Math.hypot(tip.x - wrist.x, tip.y - wrist.y)
    const mcpDist = Math.hypot(mcp.x - wrist.x, mcp.y - wrist.y)
    // Tip nearer wrist than a slightly extended MCP → finger curled
    if (tipDist < mcpDist * 1.2) curled++
  }
  const thumbTip = lms[4]
  const thumbIp = lms[3]
  const thumbMcp = lms[2]
  const thumbTipDist = Math.hypot(thumbTip.x - wrist.x, thumbTip.y - wrist.y)
  const thumbMcpDist = Math.hypot(thumbMcp.x - wrist.x, thumbMcp.y - wrist.y)
  const thumbFolded =
    thumbTipDist < thumbMcpDist * 1.35 ||
    Math.hypot(thumbTip.x - thumbIp.x, thumbTip.y - thumbIp.y) < 0.06
  return curled >= 4 && thumbFolded
}
