import { Eraser } from 'lucide-react'
import { createPortal } from 'react-dom'
import type { RefObject } from 'react'
import type { CanonicalTask } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { ActivityExecutionDetail, type TaskControlAction, type TaskControlFailure } from './executionDetail'
import type { ActivityGroup } from './lineage'
import { openActivityArtifact, openActivityProject } from './openTargets'

interface ActivityDetailsPanelProps {
  open: boolean
  groups: ActivityGroup[]
  liveCount: number
  historicalCount: number
  clock: number
  selectedGroupId: string | null
  expandedGroupIds: Set<string>
  inspectedAttemptByGroup: Record<string, string>
  busyIds: Set<string>
  controlFailures: Record<string, TaskControlFailure>
  panelNode: RefObject<HTMLDivElement | null>
  onClose: () => void
  onClearHistory: () => void
  onSelect: (groupId: string) => void
  onToggleExpand: (groupId: string) => void
  onInspectPrevious: (group: ActivityGroup) => void
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
  onCopyId: (task: CanonicalTask) => void
  onCopyPrompt: (task: CanonicalTask) => void
}

export function ActivityDetailsPanel({
  open,
  groups,
  liveCount,
  historicalCount,
  clock,
  selectedGroupId,
  expandedGroupIds,
  inspectedAttemptByGroup,
  busyIds,
  controlFailures,
  panelNode,
  onClose,
  onClearHistory,
  onSelect,
  onToggleExpand,
  onInspectPrevious,
  onControl,
  onCopyId,
  onCopyPrompt,
}: ActivityDetailsPanelProps) {
  const { t: tCommon } = useUiTranslation('common')
  const { t: tActivity } = useUiTranslation('activity')
  if (!open) return null
  if (!groups.length) return null
  return createPortal(
    <div
      ref={panelNode}
      id="activity-details"
      data-testid="activity-details"
      role="dialog"
      aria-modal="false"
      aria-label={tActivity('panelTitle')}
      tabIndex={-1}
      className="fixed bottom-12 left-3 right-3 z-[110] text-[10px] max-h-[min(70dvh,calc(100dvh-4.5rem))] overflow-y-auto rounded-lg border border-border bg-bg-secondary p-2 shadow-2xl sm:right-auto sm:w-[min(48rem,calc(100vw-1.5rem))] sm:max-h-[min(24rem,calc(100dvh-4rem))]"
    >
      <div className="mb-1.5 flex items-center justify-between px-1">
        <span className="font-semibold text-text-primary">{tActivity('panelTitle')}</span>
        <div className="flex items-center gap-2">
          {historicalCount > 0 ? (
            <button
              type="button"
              onClick={onClearHistory}
              className="flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted hover:text-text-primary"
              title={tActivity('clearHistoryTitle')}
              aria-label={tActivity('clearHistoryAria')}
            >
              <Eraser size={10} /> {tActivity('clearHistory')}
            </button>
          ) : null}
          <span className="text-text-muted">{tActivity('activeDurable', { count: liveCount })}</span>
          <button type="button" onClick={onClose} aria-label={tCommon('actions.close')} className="rounded border border-border px-2 py-1">{tCommon('actions.close')}</button>
        </div>
      </div>
      <div className="space-y-1.5">
        {groups.map(group => (
          <ActivityExecutionDetail
            key={group.id}
            group={group}
            clock={clock}
            selected={selectedGroupId === group.id}
            expanded={expandedGroupIds.has(group.id)}
            inspectedAttemptId={inspectedAttemptByGroup[group.id]}
            busyIds={busyIds}
            controlFailures={controlFailures}
            onSelect={() => onSelect(group.id)}
            onToggleExpand={() => onToggleExpand(group.id)}
            onInspectPrevious={() => onInspectPrevious(group)}
            onControl={onControl}
            onCopyId={onCopyId}
            onCopyPrompt={onCopyPrompt}
            onOpenArtifact={name => { openActivityArtifact(name) }}
            onOpenProject={() => { if (group.project) openActivityProject(group.project) }}
          />
        ))}
      </div>
    </div>,
    document.body,
  )
}
