import type { MontageShotBoard } from '../../api/montages'
import type { OutputFile } from '../../types'

const clock = (seconds: number) => {
  const whole = Math.max(0, seconds)
  const minutes = Math.floor(whole / 60)
  return `${minutes}:${(whole - minutes * 60).toFixed(1).padStart(4, '0')}`
}

/** "0:05.5–0:12.0" slot of a shot on the montage timeline. */
export function formatSlot(start: number, end: number): string {
  return `${clock(start)}–${clock(end)}`
}

export function hasPendingTakes(board: MontageShotBoard): boolean {
  return board.shots.some(shot => shot.takes.some(take => take.status !== 'completed' && take.status !== 'failed'))
}

export function shortPrompt(prompt: string, limit = 160): string {
  const text = prompt.replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text
}

/** The saved Video 2D scene a shot came from, as the file the editor opens (a production writes one per shot). */
export function sceneOutput(workspace: string, name: string): OutputFile {
  return {
    name, url: `/api/v1/file/${encodeURIComponent(name)}?workspace=${encodeURIComponent(workspace)}`,
    type: 'scene', mode: null, favorite: false, size: 0, created_at: 0,
  }
}
