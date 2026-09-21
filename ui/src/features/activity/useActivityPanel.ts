import { useCallback, useEffect, useRef, useState } from 'react'
import { listenForAgentActivityDetails, type ActivityDetailsRequest } from '../../lib/uiBus'
import { findActivityGroup, type ActivityGroup } from './lineage'

function afterPaint(callback: () => void): void {
  if (typeof window.requestAnimationFrame === 'function') window.requestAnimationFrame(callback)
  else queueMicrotask(callback)
}

export function useActivityPanel(groups: ActivityGroup[], workspace: string) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null)
  const [expandedGroupIds, setExpandedGroupIds] = useState<Set<string>>(() => new Set())
  const [inspectedAttemptByGroup, setInspectedAttemptByGroup] = useState<Record<string, string>>({})
  const [focusNonce, setFocusNonce] = useState(0)
  const [chromeWorkspace, setChromeWorkspace] = useState(workspace)
  const pendingFocusRef = useRef<ActivityDetailsRequest | null>(null)
  const restoreFocusRef = useRef<HTMLElement | null>(null)
  const toggleRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const detailsOpenRef = useRef(detailsOpen)
  if (chromeWorkspace !== workspace) {
    setChromeWorkspace(workspace)
    setSelectedGroupId(null)
    setExpandedGroupIds(new Set())
    setInspectedAttemptByGroup({})
  }

  const closePanel = useCallback(() => {
    detailsOpenRef.current = false
    setDetailsOpen(false)
    const restore = restoreFocusRef.current || toggleRef.current
    restoreFocusRef.current = null
    afterPaint(() => restore?.focus())
  }, [])

  const openPanel = useCallback(() => {
    if (!detailsOpenRef.current) {
      restoreFocusRef.current = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : toggleRef.current
    }
    detailsOpenRef.current = true
    setDetailsOpen(true)
  }, [])

  const togglePanel = useCallback(() => {
    if (detailsOpenRef.current) closePanel()
    else openPanel()
  }, [closePanel, openPanel])

  useEffect(() => listenForAgentActivityDetails(request => {
    openPanel()
    if (!request?.taskId && !request?.intentId && !request?.receiptId) return
    pendingFocusRef.current = request
    setFocusNonce(value => value + 1)
  }), [openPanel])

  useEffect(() => {
    const pending = pendingFocusRef.current
    if (!pending) return
    if (!groups.length) return
    const match = findActivityGroup(groups, pending)
    if (!match) return
    setSelectedGroupId(match.id)
    setExpandedGroupIds(current => new Set(current).add(match.id))
    if (pending.inspectPreviousAttempt && match.previousAttempt) {
      setInspectedAttemptByGroup(current => ({ ...current, [match.id]: match.previousAttempt!.id }))
    }
    pendingFocusRef.current = null
    afterPaint(() => {
      const node = panelRef.current?.querySelector(`[data-group-id="${match.id}"]`)
      if (node instanceof HTMLElement) node.focus()
    })
  }, [focusNonce, groups])

  useEffect(() => {
    if (!detailsOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (event.defaultPrevented) return
      event.preventDefault()
      event.stopPropagation()
      closePanel()
    }
    document.addEventListener('keydown', onKey, true)
    window.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [closePanel, detailsOpen])

  const toggleExpanded = (groupId: string) => {
    setExpandedGroupIds(current => {
      const next = new Set(current)
      if (next.has(groupId)) next.delete(groupId)
      else next.add(groupId)
      return next
    })
  }

  const inspectPrevious = (group: ActivityGroup) => {
    if (!group.previousAttempt) return
    setSelectedGroupId(group.id)
    setExpandedGroupIds(current => new Set(current).add(group.id))
    setInspectedAttemptByGroup(current => ({ ...current, [group.id]: group.previousAttempt!.id }))
  }

  return {
    detailsOpen,
    selectedGroupId,
    expandedGroupIds,
    inspectedAttemptByGroup,
    toggleRef,
    panelRef,
    closePanel,
    openPanel,
    togglePanel,
    setSelectedGroupId,
    toggleExpanded,
    inspectPrevious,
  }
}
