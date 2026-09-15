import { useEffect, useMemo, useState } from 'react'
import type { CanonicalTask } from '../api/client'
import { useStore } from '../stores/useStore'
import { generationPrompt } from '../features/activity/taskPresentation'
import { groupActivityTasks, isLiveStatus } from '../features/activity/lineage'
import { hideTerminalHistory, useActivityTasks } from '../features/activity/useActivityTasks'
import { useActivityPanel } from '../features/activity/useActivityPanel'
import { readHiddenHistory, writeHiddenHistory } from '../features/activity/activityHistory'
import { ActivityDetailsPanel } from '../features/activity/ActivityDetailsPanel'
import { ActivityCompactBar } from '../features/activity/ActivityCompactBar'

export function ActivityFooter() {
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const { tasks, tasksRef, busyIds, controlFailures, runControl } = useActivityTasks(activeWorkspace)
  const [historyWorkspace, setHistoryWorkspace] = useState(activeWorkspace)
  const [hiddenHistoryIds, setHiddenHistoryIds] = useState(() => readHiddenHistory(activeWorkspace))
  if (historyWorkspace !== activeWorkspace) {
    setHistoryWorkspace(activeWorkspace)
    setHiddenHistoryIds(readHiddenHistory(activeWorkspace))
  }
  const [clock, setClock] = useState(() => Date.now())
  const visibleTasks = useMemo(
    () => tasks.filter(task => !hiddenHistoryIds.has(task.id) || isLiveStatus(task.status)),
    [hiddenHistoryIds, tasks],
  )
  const groups = useMemo(
    () => groupActivityTasks(visibleTasks, { workspace: activeWorkspace }),
    [activeWorkspace, visibleTasks],
  )
  const liveGroups = groups.filter(group => (
    group.readingState === 'prepared' || group.readingState === 'admitted' || group.readingState === 'running'
  ))
  const panel = useActivityPanel(groups, activeWorkspace)
  const primaryGroup = liveGroups[0] || groups[0] || null
  const primary = primaryGroup?.primary as CanonicalTask | undefined

  useEffect(() => {
    if (!liveGroups.length) return
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [liveGroups.length])

  const copyId = (task: CanonicalTask) => {
    void navigator.clipboard?.writeText(task.id)
  }
  const copyPrompt = (task: CanonicalTask) => {
    const prompt = generationPrompt(task)
    if (prompt) void navigator.clipboard?.writeText(prompt)
  }
  const clearHistory = () => {
    const next = hideTerminalHistory(tasksRef.current, hiddenHistoryIds)
    setHiddenHistoryIds(next)
    writeHiddenHistory(activeWorkspace, next)
    if (!liveGroups.length) panel.closePanel()
  }

  return (
    <footer className="relative h-10 shrink-0 border-t border-border bg-bg-secondary px-3 sm:px-4 flex items-center gap-3 text-[10px] z-40">
      <ActivityDetailsPanel
        open={panel.detailsOpen}
        groups={groups}
        liveCount={liveGroups.length}
        historicalCount={groups.length - liveGroups.length}
        clock={clock}
        selectedGroupId={panel.selectedGroupId}
        expandedGroupIds={panel.expandedGroupIds}
        inspectedAttemptByGroup={panel.inspectedAttemptByGroup}
        busyIds={busyIds}
        controlFailures={controlFailures}
        panelNode={panel.panelRef}
        onClose={panel.closePanel}
        onClearHistory={clearHistory}
        onSelect={panel.setSelectedGroupId}
        onToggleExpand={panel.toggleExpanded}
        onInspectPrevious={panel.inspectPrevious}
        onControl={(task, action) => runControl(task, action, panel.openPanel)}
        onCopyId={copyId}
        onCopyPrompt={copyPrompt}
      />
      <ActivityCompactBar
        detailsOpen={panel.detailsOpen}
        liveCount={liveGroups.length}
        clock={clock}
        primary={primary}
        primaryGroup={primaryGroup}
        busyIds={busyIds}
        toggleRef={panel.toggleRef}
        onToggle={panel.togglePanel}
        onCopyPrompt={copyPrompt}
        onControl={(task, action) => runControl(task, action, panel.openPanel)}
      />
    </footer>
  )
}
