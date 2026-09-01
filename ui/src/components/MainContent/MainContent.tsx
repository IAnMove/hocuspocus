import { lazy, Suspense, useRef, useCallback, useState, useEffect, useLayoutEffect, useMemo, type JSX } from 'react'
import { Film, Play, Square, FolderOpen, Plus, Check, Loader2, X, BookMarked, Upload, Trash2, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { TabFilter } from './TabFilter'
import { ThumbnailGallery } from './ThumbnailGallery'
import { MediaFeedItem } from './MediaFeedItem'
import { useStore } from '../../stores/useStore'
import { jobFitsGalleryFilter } from '../../lib/galleryListQuery'
import type { GenerationJob } from '../../types'
import { stageSceneForEditor } from '../../lib/sceneOutput'
import {
  clearVideoEditorReplacementTarget,
  readVideoEditorReplacementTarget,
} from '../../features/video-editor/replacementHandoff'
import {
  clearDirectorClipReplacementTarget,
  readDirectorClipReplacementTarget,
} from '../../features/stories/directorClipHandoff'

const SceneAnimatorPanel = lazy(() => import('../Sidebar/SceneAnimatorPanel')
  .then(module => ({ default: module.SceneAnimatorPanel })))
const RigAnimatePanel = lazy(() => import('../Sidebar/RigAnimatePanel')
  .then(module => ({ default: module.RigAnimatePanel })))
const ComicEditorPanel = lazy(() => import('../../features/comics/ComicEditorPanel')
  .then(module => ({ default: module.ComicEditorPanel })))
const VideoEditorPanel = lazy(() => import('../../features/video-editor/VideoEditorPanel')
  .then(module => ({ default: module.VideoEditorPanel })))
const StoryLabPanel = lazy(() => import('../../features/stories/StoryLabPanel')
  .then(module => ({ default: module.StoryLabPanel })))
const SeriesLabPanel = lazy(() => import('../../features/series/SeriesLabPanel')
  .then(module => ({ default: module.SeriesLabPanel })))
const StyleSheetPanel = lazy(() => import('../../features/styles/StyleSheetPanel')
  .then(module => ({ default: module.StyleSheetPanel })))
const WorkspacesPanel = lazy(() => import('../../features/workspaces/WorkspacesPanel')
  .then(module => ({ default: module.WorkspacesPanel })))
const CharacterCreatorPanel = lazy(() => import('../../features/characters/CharacterCreatorPanel')
  .then(module => ({ default: module.CharacterCreatorPanel })))
const AuditDevPanel = lazy(() => import('../../features/auditdev/AuditDevPanel')
  .then(module => ({ default: module.AuditDevPanel })))
const AssetsPanel = lazy(() => import('../../features/assets/AssetsPanel')
  .then(module => ({ default: module.AssetsPanel })))

function PanelLoadingFallback() {
  return (
    <div className="flex flex-1 items-center justify-center text-text-muted">
      <Loader2 size={22} className="animate-spin text-accent-blue" />
      <span className="ml-2 text-xs">Opening workspace…</span>
    </div>
  )
}

function WorkspaceSelector() {
  const workspaces = useStore(s => s.workspaces)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const browsingUploads = useStore(s => s.browsingUploads)
  const switchWorkspace = useStore(s => s.switchWorkspace)
  const createWorkspace = useStore(s => s.createWorkspace)
  const deleteWorkspace = useStore(s => s.deleteWorkspace)
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const handleDelete = async (name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (confirmDelete !== name) {
      setConfirmDelete(name)
      setTimeout(() => setConfirmDelete(c => (c === name ? null : c)), 4000)
      return
    }
    setConfirmDelete(null)
    setDeleting(name)
    setDeleteError(null)
    try {
      await deleteWorkspace(name)
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err))
      setTimeout(() => setDeleteError(null), 6000)
    } finally {
      setDeleting(null)
    }
  }

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
        setCreating(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleCreate = async () => {
    const name = newName.trim().replace(/\s+/g, '-')
    if (!name) return
    try {
      await createWorkspace(name)
      setNewName('')
      setCreating(false)
      setOpen(false)
    } catch {
      // error logged in store
    }
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover transition-colors border border-border"
        title="Switch workspace"
      >
        <FolderOpen size={12} />
        <span className="max-w-[120px] truncate">{browsingUploads ? 'Uploads' : activeWorkspace}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 w-56 bg-bg-secondary border border-border rounded-lg shadow-lg z-50 overflow-hidden">
          <div className="px-2 py-1.5 border-b border-border">
            <span className="text-[10px] text-text-muted uppercase tracking-wider">Workspaces</span>
          </div>
          <div className="max-h-[200px] overflow-y-auto">
            {workspaces.map(ws => (
              <div key={ws.name} className="flex items-center group hover:bg-bg-hover transition-colors">
                <button
                  onClick={() => { switchWorkspace(ws.name); setOpen(false) }}
                  className={`flex-1 min-w-0 text-left px-3 py-2 text-xs flex items-center justify-between ${
                    ws.name === activeWorkspace && !browsingUploads ? 'text-accent-blue' : 'text-text-secondary'
                  }`}
                >
                  <span className="truncate">{ws.name}</span>
                  {ws.name === activeWorkspace && !browsingUploads && <Check size={12} className="shrink-0" />}
                </button>
                {/* default IS the outputs folder itself — not deletable */}
                {ws.name !== 'default' && (
                  <button
                    onClick={e => handleDelete(ws.name, e)}
                    disabled={deleting === ws.name}
                    className={`px-2 py-2 shrink-0 transition-colors ${
                      confirmDelete === ws.name
                        ? 'text-red-400 bg-red-500/15'
                        : deleting === ws.name
                          ? 'text-text-muted cursor-wait'
                          : 'text-text-muted opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-red-400'
                    }`}
                    title={confirmDelete === ws.name
                      ? `Click again to permanently delete "${ws.name}" and its ${ws.file_count ?? 0} files`
                      : `Delete workspace (${ws.file_count ?? 0} files)`}
                  >
                    {deleting === ws.name ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  </button>
                )}
              </div>
            ))}
          </div>
          {deleteError && (
            <div className="px-3 py-1.5 text-[10px] text-red-400 border-t border-border leading-snug">{deleteError}</div>
          )}
          {/* Virtual Uploads view — browse user-uploaded media (read-only;
              generations keep saving to the real active workspace). */}
          <div className="border-t border-border">
            <button
              onClick={() => { switchWorkspace('__uploads__'); setOpen(false) }}
              className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between hover:bg-bg-hover transition-colors ${
                browsingUploads ? 'text-accent-blue' : 'text-text-secondary'
              }`}
              title="Browse media you've uploaded — reuse as inputs"
            >
              <span className="flex items-center gap-1.5"><Upload size={12} /> Uploads</span>
              {browsingUploads && <Check size={12} />}
            </button>
          </div>
          <div className="border-t border-border p-2">
            {creating ? (
              <div className="flex gap-1.5">
                <input
                  type="text"
                  value={newName}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleCreate()}
                  placeholder="workspace-name"
                  className="flex-1 bg-bg-tertiary border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
                  autoFocus
                />
                <button
                  onClick={handleCreate}
                  disabled={!newName.trim()}
                  className="px-2 py-1 text-xs bg-accent-blue text-white rounded hover:bg-accent-blue-hover disabled:opacity-50"
                >
                  Create
                </button>
              </div>
            ) : (
              <button
                onClick={() => setCreating(true)}
                className="w-full text-left px-1 py-1 text-xs text-accent-blue hover:text-accent-blue-hover flex items-center gap-1"
              >
                <Plus size={12} /> New Workspace
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// How many items to render beyond the viewport in each direction
const OVERSCAN = 5
// Info bar height + border/padding
const INFO_BAR_HEIGHT = 48
// aspect-video = 56.25% of width (16:9)
const ASPECT_RATIO = 0.5625
// Gap between items (tailwind space-y-3 = 12px)
const GAP = 12

function stripTimeSuffix(msg: string): string {
  return msg.replace(/\s*\|\s*\d+:\d+.*$/, '').trim()
}

function JobPlaceholder({ job, onStop, onDismiss }: { job: GenerationJob; onStop: () => void; onDismiss: () => void }) {
  const hasSteps = job.totalSteps > 0
  const progressPct = hasSteps ? (job.step / job.totalSteps) * 100 : job.progress * 100
  const phase = stripTimeSuffix(job.phase || job.message)
  const isFailed = job.status === 'failed' || job.status === 'cancelled'
  const errorText = job.error || job.message || (job.status === 'cancelled' ? 'Cancelled' : 'Generation failed')
  const completedPanelTimings = (job.taskTimings ?? [])
    .filter(item => typeof item.total_seconds === 'number')
    .slice(-4)
  const [showH3Prompts, setShowH3Prompts] = useState(false)
  const h3WindowMatch = (job.phase || job.message || '').match(/Sliding Window\s+(\d+)\/(\d+)/i)
  const activeH3Window = h3WindowMatch ? Number(h3WindowMatch[1]) : 1
  const activeH3PlanWindow = job.h3WindowPlan?.windows.find(
    window => window.index === activeH3Window,
  ) || job.h3WindowPlan?.windows[0]

  useEffect(() => {
    const reset = window.setTimeout(() => setShowH3Prompts(false), 0)
    return () => window.clearTimeout(reset)
  }, [job.h3WindowPlan?.signature])

  return (
    <div className={`rounded-xl border overflow-hidden ${
      isFailed ? 'border-red-500/30 bg-bg-tertiary' : 'border-accent-blue/30 bg-bg-tertiary'
    }`}>
      <div className="w-full aspect-video flex items-center justify-center relative">
        {/* Dismiss button (top-right, failed only) */}
        {isFailed && (
          <button
            onClick={onDismiss}
            className="absolute top-2 right-2 p-1.5 rounded-full bg-bg-active text-text-secondary hover:bg-red-600 hover:text-white transition-colors z-10"
            title="Dismiss"
          >
            <X size={14} />
          </button>
        )}
        <div className="flex flex-col items-center gap-3 text-text-muted w-full max-w-md px-4">
          <Film size={40} className={isFailed ? 'text-red-400' : 'animate-pulse'} />

          <div className="text-center w-full">
            <p className={`text-sm font-medium ${isFailed ? 'text-red-400' : 'text-text-secondary'}`}>
              {isFailed ? (job.status === 'cancelled' ? 'Cancelled' : 'Generation Failed') : job.status === 'queued' ? 'Queued...' : 'Generating...'}
            </p>
            {!isFailed && phase && (
              <p className="text-xs mt-1 truncate">{phase}</p>
            )}
            {hasSteps && !isFailed && (
              <p className="text-[10px] text-text-muted mt-0.5">
                Step {job.step}/{job.totalSteps}
              </p>
            )}
            {!isFailed && completedPanelTimings.length > 0 && (
              <div className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-0.5 text-[10px] text-text-muted">
                {completedPanelTimings.map(item => (
                  <span key={`${item.panel_no}-${item.status}`}>
                    Viñeta {item.panel_no}: {item.total_seconds!.toFixed(1)}s
                  </span>
                ))}
              </div>
            )}
            {isFailed && (
              <p className="text-[11px] text-text-secondary mt-2 max-h-24 overflow-y-auto px-2 leading-relaxed whitespace-pre-wrap break-words">
                {errorText}
              </p>
            )}
          </div>

          {/* Progress bar — hidden when failed */}
          {!isFailed && (
            <div className="w-full bg-bg-active rounded-full h-1.5 overflow-hidden">
              {progressPct > 0 ? (
                <div
                  className="h-full bg-accent-green rounded-full transition-all duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              ) : (
                <div className="h-full bg-accent-green/60 rounded-full animate-pulse w-full" />
              )}
            </div>
          )}
        </div>
      </div>

      {job.h3WindowPlan && activeH3PlanWindow && (
        <div className="border-t border-border bg-bg-secondary/60 px-3 py-2">
          <div className="flex items-center justify-between gap-2 text-[10px] text-text-muted">
            <span className="font-medium text-text-secondary">
              Exact H3 prompt · Window {activeH3PlanWindow.index}/{job.h3WindowPlan.window_count}
            </span>
            <button
              type="button"
              onClick={() => setShowH3Prompts(open => !open)}
              className="flex items-center gap-1 text-accent-blue hover:text-accent-blue/80"
            >
              {showH3Prompts ? 'Hide all' : 'View all'}
              {showH3Prompts ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
            </button>
          </div>
          <p className="mt-1 text-[10px] leading-relaxed text-text-muted line-clamp-3 whitespace-pre-wrap break-words">
            {activeH3PlanWindow.prompt}
          </p>
          {showH3Prompts && (
            <div className="mt-2 max-h-80 overflow-y-auto space-y-2 border-t border-border pt-2">
              {job.h3WindowPlan.windows.map(window => (
                <div
                  key={`${window.index}-${window.start_frame}`}
                  className={`rounded-md border p-2 ${
                    window.index === activeH3Window
                      ? 'border-accent-blue/70 bg-accent-blue/5'
                      : 'border-border bg-bg-tertiary/60'
                  }`}
                >
                  <div className="mb-1 flex items-center justify-between text-[9px] text-text-muted">
                    <span>
                      Window {window.index}: {window.title || `Beat ${window.index}`}
                      {window.index === activeH3Window ? ' · Generating now' : ''}
                    </span>
                    <span>{window.start_seconds.toFixed(1)}–{window.end_seconds.toFixed(1)}s</span>
                  </div>
                  <pre className="whitespace-pre-wrap break-words font-sans text-[10px] leading-relaxed text-text-secondary">
                    {window.prompt}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Bottom bar */}
      <div className="px-3 py-2 min-h-[40px] flex items-center justify-between">
        <div className="text-[11px] text-text-muted truncate flex-1">
          {isFailed ? 'Click × to dismiss — the tile stays so you can see what failed' : phase || 'Preparing...'}
        </div>
        {!isFailed && (
          <button
            onClick={onStop}
            className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 transition-colors shrink-0 ml-2"
          >
            <Square size={11} />
            Stop
          </button>
        )}
      </div>
    </div>
  )
}

function PipelinePlaceholder() {
  const pipelineStatus = useStore(s => s.pipelineStatus)
  const pipelineId = useStore(s => s.pipelineId)
  const stopPipeline = useStore(s => s.stopPipeline)

  if (!pipelineId || !pipelineStatus) return null
  if (pipelineStatus.status === 'completed' || pipelineStatus.status === 'failed' || pipelineStatus.status === 'cancelled') return null

  const phase = pipelineStatus.phase || 'planning'
  const progress = pipelineStatus.progress
  const message = progress?.message || phase

  const hasSteps = (progress?.total_steps ?? 0) > 0
  const progressPct = hasSteps
    ? ((progress?.step ?? 0) / progress!.total_steps) * 100
    : progress && progress.total > 0
      ? (progress.current / progress.total) * 100
      : 0
  const phaseLabel = stripTimeSuffix(message)

  return (
    <div className="rounded-xl overflow-hidden border border-accent-blue/30 bg-bg-tertiary">
      <div className="w-full aspect-video flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-text-muted w-full max-w-xs px-4">
          <Film size={40} className="animate-pulse" />

          <div className="text-center w-full">
            <p className="text-sm font-medium text-text-secondary">
              {pipelineStatus?.status === 'paused' ? 'Paused — Review' : 'Director'}
            </p>
            <p className="text-xs mt-1 truncate">{phaseLabel}</p>
            {hasSteps && (
              <p className="text-[10px] text-text-muted mt-0.5">
                Step {progress!.step}/{progress!.total_steps}
              </p>
            )}
          </div>

          {/* Progress bar */}
          <div className="w-full bg-bg-active rounded-full h-1.5 overflow-hidden">
            {progressPct > 0 ? (
              <div
                className="h-full bg-accent-green rounded-full transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            ) : (
              <div className="h-full bg-accent-green/60 rounded-full animate-pulse w-full" />
            )}
          </div>
        </div>
      </div>

      {/* Bottom bar with stop button */}
      <div className="px-3 py-2 min-h-[40px] flex items-center justify-between">
        <div className="text-[11px] text-text-muted truncate flex-1">
          {phaseLabel || 'Preparing...'}
        </div>
        <button
          onClick={() => stopPipeline()}
          className="flex items-center gap-1 text-xs text-red-400 hover:text-red-300 transition-colors shrink-0 ml-2"
        >
          <Square size={11} />
          Stop
        </button>
      </div>
    </div>
  )
}

export function MainContent() {
  const outputs = useStore(s => s.filteredOutputs())
  const outputsTotal = useStore(s => s.outputsTotal)
  const outputsLoading = useStore(s => s.outputsLoading)
  const jobs = useStore(s => s.jobs)
  const generationMode = useStore(s => s.generationMode)
  const stopGeneration = useStore(s => s.stopGeneration)
  const dismissJob = useStore(s => s.dismissJob)
  const setSelectedOutput = useStore(s => s.setSelectedOutput)
  const selectedOutput = useStore(s => s.selectedOutput)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const mediaFilter = useStore(s => s.mediaFilter)
  const developerMode = useStore(s => s.developerMode)
  const setGalleryFeedAtTop = useStore(s => s.setGalleryFeedAtTop)
  const visibleJobs = jobs.filter(job => jobFitsGalleryFilter(job, mediaFilter))

  useEffect(() => {
    if (mediaFilter === 'auditdev' && !developerMode) setMediaFilter('all')
  }, [developerMode, mediaFilter, setMediaFilter])

  const feedRef = useRef<HTMLDivElement>(null)
  const activeIndex = selectedOutput
  const isUserScrolling = useRef(false)
  const scrollTargetIndex = useRef<number | null>(null)

  // Virtualization state
  const [scrollTop, setScrollTop] = useState(0)
  const [containerHeight, setContainerHeight] = useState(800)
  const [containerWidth, setContainerWidth] = useState(800)
  const measuredHeights = useRef<Map<string, number>>(new Map())
  const jobsAnchorRef = useRef<HTMLDivElement>(null)
  const [placeholderTotalHeight, setPlaceholderTotalHeight] = useState(0)
  const prevPlaceholderHeight = useRef(0)
  const prevOutputNames = useRef<string[]>([])

  // Dynamic estimated item height based on actual container width
  const estimatedItemHeight = Math.round(containerWidth * ASPECT_RATIO) + INFO_BAR_HEIGHT

  // Measure container on mount and resize; clear stale heights on width change
  useEffect(() => {
    const el = feedRef.current
    if (!el) return
    let prevWidth = 0
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0].contentRect
      setContainerHeight(rect.height)
      const newWidth = rect.width
      setContainerWidth(newWidth)
      if (prevWidth && Math.abs(newWidth - prevWidth) > 2) {
        measuredHeights.current.clear()
      }
      prevWidth = newWidth
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useLayoutEffect(() => {
    const el = jobsAnchorRef.current
    if (!el) {
      setPlaceholderTotalHeight(0)
      return
    }
    const update = () => setPlaceholderTotalHeight(el.offsetHeight)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [visibleJobs.length])

  useLayoutEffect(() => {
    const el = feedRef.current
    const previous = prevPlaceholderHeight.current
    prevPlaceholderHeight.current = placeholderTotalHeight
    if (!el || previous === 0) return
    const delta = placeholderTotalHeight - previous
    if (delta === 0 || el.scrollTop <= 24) return
    el.scrollTop += delta
    setScrollTop(el.scrollTop)
  }, [placeholderTotalHeight])

  const getItemHeight = useCallback((index: number) => {
    const name = outputs[index]?.name
    if (name) {
      const measured = measuredHeights.current.get(name)
      if (measured) return measured
    }
    return estimatedItemHeight
  }, [estimatedItemHeight, outputs])

  const { startIndex, endIndex, totalHeight, itemOffsets } = useMemo(() => {
    const count = outputs.length
    const offsets: number[] = new Array(count)
    let cumulative = placeholderTotalHeight

    for (let i = 0; i < count; i++) {
      offsets[i] = cumulative
      cumulative += getItemHeight(i) + GAP
    }
    const total = cumulative - (count > 0 ? GAP : 0)

    let lo = 0, hi = count - 1
    const viewStart = scrollTop - OVERSCAN * estimatedItemHeight
    while (lo < hi) {
      const mid = (lo + hi) >>> 1
      if (offsets[mid] + getItemHeight(mid) < viewStart) lo = mid + 1
      else hi = mid
    }
    const start = Math.max(0, lo)

    const viewEnd = scrollTop + containerHeight + OVERSCAN * estimatedItemHeight
    let end = start
    while (end < count && offsets[end] < viewEnd) end++

    return {
      startIndex: start,
      endIndex: Math.min(end, count),
      totalHeight: Math.max(total, placeholderTotalHeight),
      itemOffsets: offsets,
    }
  }, [outputs.length, scrollTop, containerHeight, getItemHeight, placeholderTotalHeight, estimatedItemHeight])

  const [, setMeasureEpoch] = useState(0)
  const handleItemMeasured = useCallback((index: number, height: number) => {
    const name = outputs[index]?.name
    if (!name) return
    const prev = measuredHeights.current.get(name)
    if (prev !== height) {
      measuredHeights.current.set(name, height)
      setMeasureEpoch(e => e + 1)
    }
  }, [outputs])

  const handleItemVisible = useCallback((index: number) => {
    if (scrollTargetIndex.current !== null) return
    if (isUserScrolling.current) {
      setSelectedOutput(index)
    }
  }, [setSelectedOutput])

  const handleThumbnailClick = useCallback((index: number) => {
    const file = outputs[index]
    if (file?.type === 'scene') {
      void stageSceneForEditor(file)
        .then(() => setMediaFilter('scene3d'))
        .catch(error => console.error('Failed to open scene:', error))
      return
    }
    setSelectedOutput(index)
    scrollTargetIndex.current = index
    isUserScrolling.current = false
    const feedEl = feedRef.current
    if (!feedEl) return

    // ── Why this is two phases ──
    // The virtualizer only renders items inside [startIndex, endIndex].
    // Items outside that window have NEVER been measured — their height
    // is an estimate. Summing the estimates to compute an offset for a
    // distant target accumulates error linearly with distance: a click
    // 200 items away can land hundreds of px off.
    //
    // The previous implementation did a single smooth scrollTo to the
    // estimated offset. As items entered the viewport mid-animation,
    // they got measured and the total height shifted under the
    // animation, so the smooth scroll landed on the wrong item. The
    // 800ms guard then expired and the IntersectionObserver picked up
    // a wrong-active item → thumbnail strip auto-scrolled away from
    // what the user clicked → infinite oscillation.
    //
    // The fix:
    //   Phase 1: INSTANT jump to the estimated offset. This is allowed
    //            to be slightly wrong; its only job is to bring the
    //            target item into the virtualizer's render window so
    //            it actually mounts in the DOM.
    //   Phase 2: requestAnimationFrame wait until the DOM contains an
    //            element with `data-feed-index="${index}"`, then call
    //            scrollIntoView on it for pixel-precise alignment.
    //            By the time the element exists, its height has been
    //            measured, so this final align is accurate.
    //   Guard:   scrollTargetIndex.current is held until phase 2
    //            finishes (not a fixed timeout). handleItemVisible
    //            ignores intersection events while this is non-null,
    //            so no wrong-active leak through.
    //   Re-entrancy: a stale align loop checks scrollTargetIndex
    //            against its captured target on every frame and bails
    //            if a newer click overrode it.

    const estimatedOffset = placeholderTotalHeight +
      Array.from({ length: index }, (_, i) => getItemHeight(i) + GAP).reduce((a, b) => a + b, 0)
    feedEl.scrollTo({ top: estimatedOffset, behavior: 'auto' })

    const targetIndexAtStart = index
    let attempts = 0
    const MAX_ATTEMPTS = 30 // ~500ms at 60fps
    const align = () => {
      // Newer click overrode our target — bail.
      if (scrollTargetIndex.current !== targetIndexAtStart) return
      attempts++
      const targetEl = feedEl.querySelector(`[data-feed-index="${index}"]`) as HTMLElement | null
      if (targetEl) {
        targetEl.scrollIntoView({ behavior: 'auto', block: 'start' })
        // One more frame so any post-mount measurement settles
        // before we release the guard.
        requestAnimationFrame(() => {
          if (scrollTargetIndex.current === targetIndexAtStart) {
            scrollTargetIndex.current = null
          }
        })
      } else if (attempts < MAX_ATTEMPTS) {
        requestAnimationFrame(align)
      } else {
        // Item didn't mount within the budget — release the guard so
        // the user isn't stuck. Rare; happens if outputs.length changed
        // mid-flight or the index is out of range.
        if (scrollTargetIndex.current === targetIndexAtStart) {
          scrollTargetIndex.current = null
        }
      }
    }
    requestAnimationFrame(align)
  }, [getItemHeight, outputs, placeholderTotalHeight, setMediaFilter, setSelectedOutput])

  // Infinite scroll: load more when near the bottom
  const loadingMore = useRef(false)
  const handleFeedScroll = useCallback(() => {
    const el = feedRef.current
    if (!el) return
    setScrollTop(el.scrollTop)
    setGalleryFeedAtTop(el.scrollTop <= 24)
    if (scrollTargetIndex.current === null) {
      isUserScrolling.current = true
    }
    // Trigger load-more when within 2 screens of the bottom
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    if (distanceToBottom < el.clientHeight * 2 && !loadingMore.current) {
      const store = useStore.getState()
      if (store.outputs.length < store.outputsTotal) {
        loadingMore.current = true
        store.loadMoreOutputs().finally(() => { loadingMore.current = false })
      }
    }
  }, [setGalleryFeedAtTop])

  useLayoutEffect(() => {
    const el = feedRef.current
    const previous = prevOutputNames.current
    const names = outputs.map(file => file.name)
    prevOutputNames.current = names
    if (!el || previous.length === 0) return
    let prepended = 0
    for (const name of names) {
      if (previous.includes(name)) break
      prepended += 1
    }
    if (prepended === 0 || el.scrollTop <= 24) return
    let extra = 0
    for (let index = 0; index < prepended; index += 1) extra += getItemHeight(index) + GAP
    el.scrollTop += extra
    setScrollTop(el.scrollTop)
  }, [outputs, getItemHeight])

  const visibleItems = useMemo(() => {
    const items: JSX.Element[] = []
    for (let i = startIndex; i < endIndex; i++) {
      const file = outputs[i]
      if (!file) continue
      items.push(
        <MediaFeedItem
          key={file.name}
          file={file}
          index={i}
          isActive={activeIndex === i}
          onVisible={handleItemVisible}
          onMeasured={handleItemMeasured}
          style={{
            position: 'absolute',
            top: itemOffsets[i],
            left: 0,
            right: 0,
          }}
        />
      )
    }
    return items
  }, [startIndex, endIndex, outputs, activeIndex, handleItemVisible, handleItemMeasured, itemOffsets])
  const [replacementTarget, setReplacementTarget] = useState(readVideoEditorReplacementTarget)
  const [directorReplacementTarget, setDirectorReplacementTarget] = useState(readDirectorClipReplacementTarget)

  useEffect(() => {
    setReplacementTarget(mediaFilter !== 'videoeditor' ? readVideoEditorReplacementTarget() : null)
    setDirectorReplacementTarget(mediaFilter !== 'stories' ? readDirectorClipReplacementTarget() : null)
  }, [mediaFilter])

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="px-2 md:px-6 py-2 md:py-3 border-b border-border flex items-center justify-between gap-2">
        <TabFilter />
        <div className="flex items-center gap-2 shrink-0">
          <div className="text-[10px] md:text-xs text-text-muted hidden md:block">
            {mediaFilter === 'scene3d' ? '3D Video editor'
              : mediaFilter === 'assets' ? 'Assets'
              : mediaFilter === 'animate3d' ? 'Rig & Animate'
              : mediaFilter === 'comics' ? 'Comic Studio'
              : mediaFilter === 'stories' ? 'Story Lab'
              : mediaFilter === 'series' ? 'Series Lab'
              : mediaFilter === 'workspaces' ? 'Workspaces'
              : mediaFilter === 'characters' ? 'Character Creator'
              : mediaFilter === 'styles' ? 'Hoja de estilos'
              : mediaFilter === 'videoeditor' ? 'Video Editor'
              : mediaFilter === 'auditdev' && developerMode ? 'Auditoría interna'
              : outputsTotal > outputs.length
              ? `${outputs.length} / ${outputsTotal} items`
              : `${outputs.length} ${outputs.length === 1 ? 'item' : 'items'}`}
          </div>
          {mediaFilter !== 'styles' && mediaFilter !== 'assets' && <WorkspaceSelector />}
        </div>
      </div>

      {/* Content area: feed + thumbnails */}
      <div className="flex-1 flex flex-row gap-0 overflow-hidden relative">
        <Suspense fallback={<PanelLoadingFallback />}>
        {mediaFilter === 'assets' ? (
          <AssetsPanel />
        ) : mediaFilter === 'scene3d' ? (
          <div className="flex-1 overflow-y-auto p-4 md:p-8">
            <div className="max-w-[1600px] mx-auto">
              <SceneAnimatorPanel />
            </div>
          </div>
        ) : mediaFilter === 'animate3d' ? (
          <div className="flex-1 overflow-y-auto p-4 md:p-8">
            <div className="max-w-2xl mx-auto">
              <RigAnimatePanel />
            </div>
          </div>
        ) : mediaFilter === 'stories' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <StoryLabPanel />
            </div>
          </div>
        ) : mediaFilter === 'series' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <SeriesLabPanel />
            </div>
          </div>
        ) : mediaFilter === 'workspaces' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <WorkspacesPanel />
            </div>
          </div>
        ) : mediaFilter === 'characters' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <CharacterCreatorPanel />
            </div>
          </div>
        ) : mediaFilter === 'styles' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <StyleSheetPanel />
            </div>
          </div>
        ) : mediaFilter === 'comics' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <ComicEditorPanel />
            </div>
          </div>
        ) : mediaFilter === 'videoeditor' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <VideoEditorPanel />
            </div>
          </div>
        ) : mediaFilter === 'auditdev' && developerMode ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <AuditDevPanel />
            </div>
          </div>
        ) : <>
        {/* Scrollable media feed */}
        <div
          ref={feedRef}
          className="flex-1 overflow-y-auto p-3 md:p-4"
          onScroll={handleFeedScroll}
        >
          {/* Pipeline + Job placeholders at top (not virtualized — small count) */}
          <div ref={jobsAnchorRef} className="space-y-3 mb-3">
            {replacementTarget && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
                <Film size={14} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  Rehaciendo la posición {replacementTarget.clipIndex + 1} del montaje: <strong>{replacementTarget.originalName}</strong>.
                  Genera un vídeo nuevo y después pulsa “Usar en posición {replacementTarget.clipIndex + 1}”.
                </span>
                <button
                  type="button"
                  onClick={() => {
                    clearVideoEditorReplacementTarget()
                    setReplacementTarget(null)
                  }}
                  className="rounded border border-emerald-400/30 px-2 py-1 text-[10px] text-emerald-200 hover:bg-emerald-500/20"
                >
                  Cancelar reemplazo
                </button>
              </div>
            )}
            {directorReplacementTarget && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-2 text-xs text-violet-100">
                <RefreshCw size={14} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  Rehaciendo el clip {directorReplacementTarget.clipIndex + 1} de Montaje.
                  Ajusta sus datos, genera una o varias versiones y pulsa “Usar en Montaje · clip {directorReplacementTarget.clipIndex + 1}” en la que quieras conservar.
                </span>
                <button
                  type="button"
                  onClick={() => {
                    clearDirectorClipReplacementTarget()
                    setDirectorReplacementTarget(null)
                  }}
                  className="rounded border border-violet-400/30 px-2 py-1 text-[10px] text-violet-100 hover:bg-violet-500/20"
                >
                  Cancelar reemplazo
                </button>
              </div>
            )}
            <PipelinePlaceholder />
            {visibleJobs.map((j, i) => (
              <JobPlaceholder
                key={j.id || `pending-${i}`}
                job={j}
                onStop={() => stopGeneration(j.id)}
                onDismiss={() => dismissJob(j.id)}
              />
            ))}
          </div>

          {/* Position container for virtualized output items */}
          <div className="relative" style={{ height: totalHeight - placeholderTotalHeight }}>
            {visibleItems.map(item => {
              // Adjust top positions to be relative to this container (subtract placeholder height)
              const adjustedStyle = {
                ...item.props.style,
                top: (item.props.style?.top as number) - placeholderTotalHeight,
              }
              return { ...item, props: { ...item.props, style: adjustedStyle } }
            })}
          </div>

          {/* Loading state */}
          {outputsLoading && outputs.length === 0 && (
            <div className="flex items-center justify-center min-h-[300px]">
              <div className="flex flex-col items-center gap-3 text-text-muted">
                <Loader2 size={24} className="animate-spin text-accent-blue" />
                <p className="text-sm">Indexing workspace...</p>
              </div>
            </div>
          )}

          {/* Empty state — first-run quick start. Teaches the three steps
              to a first generation and sets the one expectation that most
              surprises new users: the first run of each model downloads
              its weights (tens of GB) before anything appears. */}
          {!outputsLoading && outputs.length === 0 && visibleJobs.length === 0 && (() => {
            const noun = mediaFilter === 'images' ? 'images'
              : mediaFilter === 'audio' ? 'audio'
              : mediaFilter === 'model3d' ? '3D models'
              : mediaFilter === 'scenes' ? 'compositor scenes'
              : mediaFilter === 'trailers' ? 'trailers'
              : mediaFilter === 'videoclips' ? 'music videos'
              : mediaFilter === 'series_episodes' ? 'chapters'
              : generationMode === 'image' ? 'images'
              : generationMode === 'audio' ? 'audio'
              : generationMode === 'model3d' ? '3D assets' : 'videos'
            const example = mediaFilter === 'model3d'
              ? 'Open Character Creator or the 3D sidebar and generate a Hunyuan3D asset.'
              : mediaFilter === 'scenes'
              ? 'Save a scene from the 3D Video compositor.'
              : mediaFilter === 'trailers'
              ? 'Assemble a trailer in Story Lab so it is tagged as a trailer mix.'
              : generationMode === 'image'
              ? 'a neon city street at night, cinematic'
              : generationMode === 'audio'
              ? 'a dreamy synthwave track about the ocean'
              : 'a golden retriever surfing a big wave, slow motion'
            return (
              <div className="flex items-center justify-center min-h-[300px] px-6">
                <div className="flex flex-col items-center gap-4 text-center max-w-sm">
                  <div className="w-16 h-16 rounded-2xl bg-bg-active flex items-center justify-center text-text-muted">
                    <Play size={24} />
                  </div>
                  <p className="text-sm text-text-secondary">Your generated {noun} will appear here.</p>
                  <ol className="text-xs text-text-muted space-y-1.5 text-left">
                    <li><span className="text-accent-blue font-medium">1.</span> Pick a model in the sidebar (a good default is already selected).</li>
                    <li><span className="text-accent-blue font-medium">2.</span> Type a prompt — e.g. <span className="text-text-secondary italic">“{example}”</span></li>
                    <li><span className="text-accent-blue font-medium">3.</span> Hit Generate.</li>
                  </ol>
                  <p className="text-[11px] text-text-muted leading-snug">
                    Heads up: the first time you use a model, its weights download
                    once (often tens of GB) before generation starts — later runs
                    are fast. Progress shows at the bottom-right.
                  </p>
                  <button
                    onClick={() => useStore.getState().setRecipesOpen(true)}
                    className="mt-1 flex items-center gap-1.5 px-3 py-1.5 text-xs bg-accent-blue/10 border border-accent-blue/30 rounded-lg text-accent-blue hover:bg-accent-blue/20 transition-colors"
                  >
                    <BookMarked size={13} /> Browse recipes
                  </button>
                </div>
              </div>
            )
          })()}
        </div>

        {/* Thumbnail sidebar */}
        <ThumbnailGallery
          activeIndex={activeIndex}
          onThumbnailClick={handleThumbnailClick}
        />
        </>}
        </Suspense>
      </div>
    </main>
  )
}
