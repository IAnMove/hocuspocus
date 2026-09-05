import type { CSSProperties } from 'react'

export type AgentVisualState = 'idle' | 'listening' | 'thinking' | 'acting' | 'success' | 'error'

interface AgentAvatarProps {
  state?: AgentVisualState
  size?: number
}

export function AgentAvatar({ state = 'idle', size = 32 }: AgentAvatarProps) {
  return (
    <span
      className="hp-agent-avatar"
      data-state={state}
      style={{ '--hp-agent-size': `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      <span className="hp-agent-halo" />
      <img src="/hocuspocus-icon.png" alt="" draggable={false} />
      <span className="hp-agent-mote hp-agent-mote-a" />
      <span className="hp-agent-mote hp-agent-mote-b" />
      <span className="hp-agent-mote hp-agent-mote-c" />
    </span>
  )
}
