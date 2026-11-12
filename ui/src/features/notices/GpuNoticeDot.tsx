import { useSyncExternalStore } from 'react'
import { preflightText } from '../../components/preflightCopy'
import {
  preflightRevision,
  subscribePreflight,
  visiblePreflightChecks,
} from './preflightNotices'

/** The CUDA warning stays in the footer even when the tray is closed. It cannot be dismissed. */
export function GpuNoticeDot() {
  const revision = useSyncExternalStore(subscribePreflight, preflightRevision, preflightRevision)
  void revision
  const cuda = visiblePreflightChecks().find(check => check.id === 'cuda')
  if (!cuda) return null
  const text = preflightText(cuda)
  return (
    <span
      data-testid="gpu-notice-dot"
      title={text}
      aria-label={text}
      role="img"
      className="inline-block h-2 w-2 shrink-0 rounded-full bg-red-500"
    />
  )
}
