import { forwardRef } from 'react'

export const WebcamPip = forwardRef<HTMLVideoElement>(function WebcamPip(_, ref) {
  return (
    <div className="webcam-pip">
      <span className="label">HAND LINK</span>
      <video ref={ref} muted playsInline />
    </div>
  )
})
