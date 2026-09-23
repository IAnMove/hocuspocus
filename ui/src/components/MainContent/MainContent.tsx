import { lazy, Suspense, useRef, useCallback, useState, useEffect, useLayoutEffect, useMemo, type JSX } from 'react'
import { Film, Play, Square, Loader2, X, BookMarked, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { TabFilter } from './TabFilter'
import { visibleWorkspaceSurface } from '../../lib/navigationCategories'
import { ThumbnailGallery } from './ThumbnailGallery'
import { GalleryToolbar } from './GalleryToolbar'
import { useGallerySelection } from './useGallerySelection'
import { useGalleryKeyboard } from './useGalleryKeyboard'
import { useGridPinch } from './useGridPinch'
import { useLiveMediaFacts } from './useLiveMediaFacts'
import { useDaySections } from './galleryDays'
import { GallerySearchEmpty } from './GallerySearch'
import { galleryPositionKey, readGalleryPosition, writeGalleryPosition } from './galleryPositions'
import type { DetailVideoTime, GalleryDetail } from './GalleryDetailsDialog'
import { GALLERY_GRID_COLUMN_RANGE } from '../../stores/gallerySlice'
import { MediaFeedItem } from './MediaFeedItem'
import { useStore } from '../../stores/useStore'
import { jobFitsGalleryFilter } from '../../lib/galleryListQuery'
import type { GenerationJob } from '../../types'
import { openSceneOutput } from '../../lib/sceneOutput'
import {
  clearVideoEditorReplacementTarget,
  readVideoEditorReplacementTarget,
} from '../../features/video-editor/replacementHandoff'
import {
  clearDirectorClipReplacementTarget,
  readDirectorClipReplacementTarget,
} from '../../features/stories/directorClipHandoff'
import { useUiTranslation } from '../../i18n'
import {
  FEED_CARD_BORDER,
  FEED_INFO_BAR_HEIGHT,
  anchorAt,
  anchorOffset,
  buildGalleryLayout,
  gridColumns,
  neighborIndex,
  visibleBlocks,
  type BlockRange,
  type GalleryAnchor,
  type GalleryLayout,
} from './mediaGalleryLayout'

const GalleryLayouts = lazy(() => import('./GalleryLayouts'))
const GalleryDetailsDialog = lazy(() => import('./GalleryDetailsDialog'))
const DirectGenerationWorkspace = lazy(() => import('../Sidebar/Sidebar').then(module => ({ default: module.DirectGenerationWorkspace })))
const DirectorWorkspace = lazy(() => import('../Sidebar/DirectorChat').then(module => ({ default: module.DirectorChat })))
const SceneAnimatorPanel = lazy(() => import('../Sidebar/SceneAnimatorPanel')
  .then(module => ({ default: module.SceneAnimatorPanel })))
const Scene3DEditorPanel = lazy(() => import('../../features/scene3d/Scene3DEditorPanel')
  .then(module => ({ default: module.Scene3DEditorPanel })))
const CharacterReplacementWorkspace = lazy(() => import('../../features/characterReplacement/CharacterReplacementWorkspace')
  .then(module => ({ default: module.CharacterReplacementWorkspace })))
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
const RunsPanel = lazy(() => import('../../features/workspaces/WorkspacesPanel')
  .then(module => ({ default: module.RunsPanel })))
const CharacterCreatorPanel = lazy(() => import('../../features/characters/CharacterCreatorPanel')
  .then(module => ({ default: module.CharacterCreatorPanel })))
const DeveloperToolsPanel = lazy(() => import('../../features/auditdev/DeveloperToolsPanel')
  .then(module => ({ default: module.DeveloperToolsPanel })))
const AssetsPanel = lazy(() => import('../../features/assets/AssetsPanel')
  .then(module => ({ default: module.AssetsPanel })))
const ProjectsPanel = lazy(() => import('../../features/projects/ProjectsPanel')
  .then(module => ({ default: module.ProjectsPanel })))
const WorkspaceCollectionsPanel = lazy(() => import('../../features/workspaceCollections/WorkspaceCollectionsPanel')
  .then(module => ({ default: module.WorkspaceCollectionsPanel })))

function PanelLoadingFallback() {
  return (
    <div className="flex flex-1 items-center justify-center text-text-muted">
      <Loader2 size={22} className="animate-spin text-accent-blue" />
      <span className="ml-2 text-xs">Opening workspace…</span>
    </div>
  )
}

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
  const { t: tActivity } = useUiTranslation('activity')
  const outputs = useStore(s => s.filteredOutputs())
  const outputsLoading = useStore(s => s.outputsLoading)
  const jobs = useStore(s => s.jobs)
  const generationMode = useStore(s => s.generationMode)
  const stopGeneration = useStore(s => s.stopGeneration)
  const dismissJob = useStore(s => s.dismissJob)
  const setSelectedOutput = useStore(s => s.setSelectedOutput)
  const selectedOutput = useStore(s => s.selectedOutput)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const mediaFilter = useStore(s => s.mediaFilter)
  const sidebarMode = useStore(s => s.sidebarMode)
  const sidebarOpen = useStore(s => s.sidebarOpen)
  const settingsOpen = useStore(s => s.settingsOpen)
  const dashboardOpen = useStore(s => s.dashboardOpen)
  const workspaceSurface = visibleWorkspaceSurface({ mediaFilter, sidebarMode, sidebarOpen, settingsOpen, dashboardOpen })
  const developerMode = useStore(s => s.developerMode)
  const setGalleryFeedAtTop = useStore(s => s.setGalleryFeedAtTop)
  const visibleJobs = jobs.filter(job => jobFitsGalleryFilter(job, mediaFilter))

  useEffect(() => {
    if (mediaFilter === 'auditdev' && !developerMode) setMediaFilter('all')
  }, [developerMode, mediaFilter, setMediaFilter])

  const feedRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const jobsAnchorRef = useRef<HTMLDivElement>(null)
  const activeIndex = selectedOutput
  const isUserScrolling = useRef(false)
  const scrollTargetIndex = useRef<number | null>(null)
  const feedAtTop = useRef(true)

  const galleryView = useStore(s => s.galleryView)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const browsingUploads = useStore(s => s.browsingUploads)
  const galleryGridColumns = useStore(s => s.galleryGridColumns)
  const setGalleryGridColumns = useStore(s => s.setGalleryGridColumns)
  const setMobileHistoryOpen = useStore(s => s.setMobileHistoryOpen)
  const workspaces = useStore(s => s.workspaces)
  const outputsTotal = useStore(s => s.outputsTotal)
  const selection = useGallerySelection(outputs)
  const [detail, setDetail] = useState<GalleryDetail | null>(null)
  const galleryWorkspace = browsingUploads ? '__uploads__' : activeWorkspace
  const positionKey = galleryPositionKey(activeWorkspace, browsingUploads, mediaFilter)

  // Width and a *stable* height of the feed's content box. Phone browsers
  // grow and shrink the dynamic viewport as their toolbars slide away while
  // scrolling; sizing rows from that live height re-flowed every row mid-
  // gesture. Subtracting the toolbar allowance (dynamic minus small viewport)
  // keeps rows fixed until the window really changes size.
  const [viewport, setViewport] = useState({ width: 0, height: 0 })

  // Grid and mosaic cells live in a lazy chunk; fetch it once the feed has
  // settled so the first switch draws immediately instead of blank.
  useEffect(() => {
    const timer = window.setTimeout(() => { void import('./GalleryLayouts') }, 1200)
    return () => window.clearTimeout(timer)
  }, [])

  // Grid and mosaic group outputs under a heading per day, except when
  // favourites come first and dates would interleave.
  const galleryOrder = useStore(s => s.galleryOrder)
  const searchQuery = useStore(s => s.outputSearchQuery)
  const sections = useDaySections(outputs, galleryView, galleryOrder)
  const layout = useMemo(
    () => buildGalleryLayout(galleryView, outputs, viewport.width, viewport.height, { gridColumns: galleryGridColumns, sections }),
    [galleryView, outputs, viewport.width, viewport.height, galleryGridColumns, sections],
  )
  const layoutRef = useRef<GalleryLayout>(layout)
  const outputsRef = useRef(outputs)
  const anchorRef = useRef<GalleryAnchor | null>(null)
  /** A remembered position waiting for its item to be listed. */
  const pendingRestore = useRef<GalleryAnchor | null>(null)
  const [range, setRange] = useState<BlockRange>({ first: 0, last: -1 })

  /** Scroll offset inside the virtual list (below the job placeholders). */
  const listOffset = useCallback(() => {
    const el = feedRef.current
    return el ? el.scrollTop - (listRef.current?.offsetTop ?? 0) : 0
  }, [])

  const syncWindow = useCallback(() => {
    const el = feedRef.current
    if (!el) return
    const current = layoutRef.current
    // Mount rows ahead of a fast fling. Cards are memoized, so rows that stay
    // mounted do not re-render while the reader scrolls.
    const overscan = el.clientHeight * (current.view === 'feed' ? 1.5 : 1)
    const next = visibleBlocks(current, listOffset(), el.clientHeight, overscan)
    setRange(prev => (prev.first === next.first && prev.last === next.last ? prev : next))
  }, [listOffset])

  const markFeedTop = useCallback((atTop: boolean) => {
    if (feedAtTop.current === atTop) return
    feedAtTop.current = atTop
    setGalleryFeedAtTop(atTop)
  }, [setGalleryFeedAtTop])

  /** Return to a remembered item once the list that holds it has loaded. */
  const tryRestore = useCallback(() => {
    const pending = pendingRestore.current
    const el = feedRef.current
    if (!pending || !el) return false
    const target = anchorOffset(layoutRef.current, outputsRef.current, pending, true)
    if (target == null) return false
    pendingRestore.current = null
    anchorRef.current = pending
    el.scrollTop = Math.round(target + (listRef.current?.offsetTop ?? 0))
    markFeedTop(el.scrollTop <= 24)
    syncWindow()
    return true
  }, [markFeedTop, syncWindow])

  useEffect(() => {
    const el = feedRef.current
    if (!el) return
    const probe = document.createElement('div')
    probe.style.cssText = 'position:fixed;top:0;left:0;width:0;height:100svh;visibility:hidden;pointer-events:none'
    document.body.appendChild(probe)
    const measure = () => {
      const style = getComputedStyle(el)
      const width = el.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
      const content = el.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom)
      const small = probe.getBoundingClientRect().height
      const toolbar = small > 0 ? Math.max(0, window.innerHeight - small) : 0
      const height = Math.max(0, content - toolbar)
      setViewport(prev => (Math.abs(prev.width - width) < 1 && Math.abs(prev.height - height) < 1 ? prev : { width, height }))
    }
    measure()
    // A remounted gallery (back from another surface) returns to its item.
    pendingRestore.current ??= anchorRef.current
    const frame = requestAnimationFrame(() => { tryRestore() })
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => {
      cancelAnimationFrame(frame)
      observer.disconnect()
      probe.remove()
    }
  }, [mediaFilter, workspaceSurface, tryRestore])

  // Each list (workspace or uploads × filter) remembers where the reader was;
  // switching lists saves the old position and returns to the new one's.
  const positionKeyRef = useRef(positionKey)
  const clearSelection = selection.clear
  useLayoutEffect(() => {
    if (positionKeyRef.current !== positionKey) {
      writeGalleryPosition(positionKeyRef.current, anchorRef.current)
      positionKeyRef.current = positionKey
    }
    pendingRestore.current = readGalleryPosition(positionKey)
    anchorRef.current = null
    scrollTargetIndex.current = null
    isUserScrolling.current = false
    if (feedRef.current) feedRef.current.scrollTop = 0
    feedAtTop.current = false
    markFeedTop(true)
    clearSelection()
    setDetail(null)
  }, [positionKey, markFeedTop, clearSelection])
  useEffect(() => () => writeGalleryPosition(positionKeyRef.current, anchorRef.current), [])

  // Job placeholders sit above the rows; their height moves every row.
  const [placeholderTotalHeight, setPlaceholderTotalHeight] = useState(0)
  useLayoutEffect(() => {
    const el = jobsAnchorRef.current
    if (!el) return
    const observer = new ResizeObserver(() => setPlaceholderTotalHeight(el.offsetHeight))
    observer.observe(el)
    return () => observer.disconnect()
  }, [mediaFilter, workspaceSurface])

  // Whenever the geometry changes — new outputs above, a finished job's
  // placeholder, another view, a rotated phone — keep the item the reader was
  // looking at in place. At the very top there is no anchor, so new work
  // appears in view instead of being scrolled past.
  useLayoutEffect(() => {
    const previous = layoutRef.current
    layoutRef.current = layout
    outputsRef.current = outputs
    if (tryRestore()) return
    const el = feedRef.current
    const anchor = anchorRef.current
    if (el && anchor) {
      const sameShape = previous.shape === layout.shape
      const target = anchorOffset(layout, outputs, anchor, sameShape)
      if (target != null) {
        const top = Math.round(target + (listRef.current?.offsetTop ?? 0))
        if (Math.abs(el.scrollTop - top) > 1) el.scrollTop = top
        if (!sameShape) anchorRef.current = { name: anchor.name, within: 0 }
      }
    }
    syncWindow()
  }, [layout, outputs, placeholderTotalHeight, syncWindow, tryRestore])

  const handleItemVisible = useCallback((index: number) => {
    if (scrollTargetIndex.current !== null) return
    if (isUserScrolling.current) {
      setSelectedOutput(index)
    }
  }, [setSelectedOutput])

  /** Bring an item's row into view. `start` aligns it to the top (the history
   *  strip, one-up cards); `nearest` scrolls only as far as needed. */
  const revealIndex = useCallback((index: number, align: 'start' | 'nearest') => {
    const feedEl = feedRef.current
    const current = layoutRef.current
    const block = current.blocks[current.blockOf[index]]
    if (!feedEl || !block) return
    const top = block.top + (listRef.current?.offsetTop ?? 0)
    let target = top
    if (align === 'nearest') {
      const bottom = top + block.height - feedEl.clientHeight
      if (feedEl.scrollTop <= top && feedEl.scrollTop >= bottom) return
      target = feedEl.scrollTop > top ? top : bottom
    }
    // Row positions are exact, so one jump lands on the item. The guard keeps
    // the rows scrolled past during the jump from claiming the selection.
    pendingRestore.current = null
    scrollTargetIndex.current = index
    isUserScrolling.current = false
    feedEl.scrollTo({ top: target, behavior: 'auto' })
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (scrollTargetIndex.current === index) scrollTargetIndex.current = null
    }))
  }, [])

  const handleThumbnailClick = useCallback((index: number) => {
    const file = outputs[index]
    if (file?.type === 'scene') {
      void openSceneOutput(file)
        .catch(error => console.error('Failed to open scene:', error))
      return
    }
    setSelectedOutput(index)
    revealIndex(index, 'start')
  }, [outputs, setSelectedOutput, revealIndex])

  const openDetails = useCallback((index: number, video?: DetailVideoTime) => {
    const file = outputs[index]
    if (!file) return
    setSelectedOutput(index)
    setDetail({ name: file.name, origin: file.name, video })
  }, [outputs, setSelectedOutput])

  const navigateDetails = useCallback((index: number) => {
    const file = outputsRef.current[index]
    if (!file) return
    setSelectedOutput(index)
    setDetail(current => (current ? { ...current, name: file.name } : current))
  }, [setSelectedOutput])

  const closeDetails = useCallback(() => {
    const current = detail
    setDetail(null)
    if (!current || current.name === current.origin) return
    // Stepped to another item: leave the gallery on it, with focus on it.
    const index = outputsRef.current.findIndex(file => file.name === current.name)
    if (index < 0) return
    revealIndex(index, layoutRef.current.view === 'feed' ? 'start' : 'nearest')
    requestAnimationFrame(() => requestAnimationFrame(() => {
      feedRef.current?.querySelector<HTMLElement>(`[data-gallery-index="${index}"] button, [data-feed-index="${index}"] [aria-label^="Enlarge"], [data-feed-index="${index}"] [aria-label^="Open video"]`)?.focus()
    }))
  }, [detail, revealIndex])

  // Infinite scroll: load more when near the bottom
  const loadingMore = useRef(false)
  const loadMore = useCallback(() => {
    const store = useStore.getState()
    if (loadingMore.current || store.outputs.length >= store.outputsTotal) return
    loadingMore.current = true
    void store.loadMoreOutputs().finally(() => { loadingMore.current = false })
  }, [])

  useGalleryKeyboard({
    scope: feedRef,
    enabled: !detail,
    onMove: direction => {
      const next = neighborIndex(layoutRef.current, activeIndex, direction)
      setSelectedOutput(next)
      revealIndex(next, layoutRef.current.view === 'feed' ? 'start' : 'nearest')
    },
    onOpen: () => openDetails(activeIndex),
    onEscape: selection.selecting ? selection.clear : undefined,
  })

  // Sizes and colours finished in the background settle into the list.
  useLiveMediaFacts(outputs, galleryWorkspace, viewport.width > 0)


  const phoneGrid = galleryView === 'grid' && viewport.width > 0 && viewport.width < 640
  useGridPinch({
    target: feedRef,
    enabled: phoneGrid,
    columns: gridColumns(viewport.width, galleryGridColumns),
    min: GALLERY_GRID_COLUMN_RANGE[0],
    max: GALLERY_GRID_COLUMN_RANGE[1],
    onChange: setGalleryGridColumns,
  })

  const handleFeedScroll = useCallback(() => {
    const el = feedRef.current
    if (!el) return
    const offset = listOffset()
    anchorRef.current = el.scrollTop <= 24 ? null : anchorAt(layoutRef.current, outputsRef.current, offset)
    markFeedTop(el.scrollTop <= 24)
    syncWindow()
    if (scrollTargetIndex.current === null) {
      isUserScrolling.current = true
    }
    // Trigger load-more when within 2 screens of the bottom
    if (el.scrollHeight - el.scrollTop - el.clientHeight < el.clientHeight * 2) loadMore()
  }, [listOffset, markFeedTop, syncWindow, loadMore])

  /** The reader took over: forget a position still waiting to be restored. */
  const cancelRestore = useCallback(() => { pendingRestore.current = null }, [])

  const feedCards = useMemo(() => {
    if (layout.view !== 'feed') return null
    const items: JSX.Element[] = []
    for (let row = range.first; row <= range.last; row++) {
      const block = layout.blocks[row]
      const cell = block?.cells[0]
      const file = cell && outputs[cell.index]
      if (!file) continue
      items.push(
        <MediaFeedItem
          key={file.name}
          file={file}
          index={cell.index}
          isActive={activeIndex === cell.index}
          onVisible={handleItemVisible}
          onOpenDetails={openDetails}
          top={block.top}
          height={block.height}
          mediaHeight={block.height - FEED_INFO_BAR_HEIGHT - FEED_CARD_BORDER}
        />
      )
    }
    return items
  }, [layout, range, outputs, activeIndex, handleItemVisible, openDetails])
  const [replacementTarget, setReplacementTarget] = useState(readVideoEditorReplacementTarget)
  const [directorReplacementTarget, setDirectorReplacementTarget] = useState(readDirectorClipReplacementTarget)
  // Re-read the pending replacement handoffs whenever the filter changes.
  const [handoffFilter, setHandoffFilter] = useState(mediaFilter)
  if (handoffFilter !== mediaFilter) {
    setHandoffFilter(mediaFilter)
    setReplacementTarget(mediaFilter !== 'videoeditor' ? readVideoEditorReplacementTarget() : null)
    setDirectorReplacementTarget(mediaFilter !== 'stories' ? readDirectorClipReplacementTarget() : null)
  }

  return (
    <main className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Top bar */}
      <div className="border-b border-border px-2 py-2 md:px-6 md:py-3">
        <TabFilter />
      </div>

      {/* Content area: feed + thumbnails */}
      <div className={`flex-1 flex min-h-0 min-w-0 overflow-hidden relative ${workspaceSurface === 'generate' ? 'flex-col xl:flex-row' : 'flex-row'}`}>
        <Suspense fallback={<PanelLoadingFallback />}>
        {workspaceSurface === 'generate' && (
          <div className="flex min-h-0 w-full shrink-0 flex-col border-b border-border xl:h-full xl:max-w-xl xl:border-b-0 xl:border-r 2xl:max-w-2xl">
            <DirectGenerationWorkspace />
          </div>
        )}
        {workspaceSurface === 'director' ? (
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <DirectorWorkspace />
          </div>
        ) : mediaFilter === 'assets' ? (
          <AssetsPanel />
        ) : mediaFilter === 'projects' ? (
          <ProjectsPanel />
        ) : mediaFilter === 'workspaces' ? (
          <WorkspaceCollectionsPanel />
        ) : mediaFilter === 'character-replacement' ? (
          <div className="flex-1 min-w-0 overflow-y-auto">
            <CharacterReplacementWorkspace />
          </div>
        ) : mediaFilter === 'scene3d' ? (
          <div className="flex-1 overflow-y-auto p-4 md:p-8">
            <div className="max-w-[1600px] mx-auto">
              <SceneAnimatorPanel />
            </div>
          </div>
        ) : mediaFilter === 'world3d' ? (
          <div className="flex-1 overflow-y-auto p-4 md:p-8">
            <div className="max-w-[1600px] mx-auto">
              <Scene3DEditorPanel />
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
        ) : mediaFilter === 'runs' ? (
          <div className="flex-1 overflow-hidden p-2 md:p-4">
            <div className="max-w-[1900px] mx-auto h-full">
              <RunsPanel />
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
              <DeveloperToolsPanel />
            </div>
          </div>
        ) : <>
        {/* Gallery column: its own toolbar above the rows, so the layout
            switcher belongs to the rows it changes rather than floating over
            the cards or the history strip. */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex min-h-[3.25rem] shrink-0 items-center border-b border-border/60 px-3 py-1 md:px-4">
          <GalleryToolbar
            view={galleryView}
            hasItems={outputs.length > 0}
            selecting={selection.selecting}
            picked={selection.picked.size}
            busy={selection.busy}
            error={selection.error}
            moveTargets={workspaces.map(ws => ws.name).filter(name => name !== activeWorkspace)}
            onOpenHistory={() => setMobileHistoryOpen(true)}
            onStartSelecting={selection.start}
            onSelectAll={selection.selectAll}
            onAction={action => { void selection.apply(action) }}
            onDone={selection.clear}
            onCompare={selection.comparePair ? () => {
              const [first, second] = selection.comparePair!
              setDetail({ name: first, origin: first, compare: second })
              selection.clear()
            } : undefined}
          />
        </div>
        <div
          ref={feedRef}
          data-testid="media-feed"
          className="relative min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain p-3 [overflow-anchor:none] md:p-4"
          style={phoneGrid ? { touchAction: 'pan-y' } : undefined}
          onScroll={handleFeedScroll}
          onWheel={cancelRestore}
          onTouchStart={cancelRestore}
          onPointerDown={cancelRestore}
          onKeyDown={cancelRestore}
        >
          {/* Pipeline + Job placeholders at top (not virtualized — small count) */}
          <div ref={jobsAnchorRef} className="space-y-3 mb-3">
            {replacementTarget && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-500/35 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">
                <Film size={14} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  {tActivity('montage.redoingEditorSlot', { n: replacementTarget.clipIndex + 1, name: replacementTarget.originalName })}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    clearVideoEditorReplacementTarget()
                    setReplacementTarget(null)
                  }}
                  className="rounded border border-emerald-400/30 px-2 py-1 text-[10px] text-emerald-200 hover:bg-emerald-500/20"
                >
                  {tActivity('montage.cancelReplacement')}
                </button>
              </div>
            )}
            {directorReplacementTarget && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-violet-500/40 bg-violet-500/10 px-3 py-2 text-xs text-violet-100">
                <RefreshCw size={14} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  {tActivity('montage.redoingAssemblyClip', { n: directorReplacementTarget.clipIndex + 1 })}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    clearDirectorClipReplacementTarget()
                    setDirectorReplacementTarget(null)
                  }}
                  className="rounded border border-violet-400/30 px-2 py-1 text-[10px] text-violet-100 hover:bg-violet-500/20"
                >
                  {tActivity('montage.cancelReplacement')}
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
          {/* One positioned list for every view. Its height is the exact
              layout height, so the scrollbar never jumps as rows mount. */}
          <div ref={listRef} className="relative" style={{ height: layout.height }}>
            {layout.view === 'feed' ? feedCards : (
              <Suspense fallback={null}>
                <GalleryLayouts
                  layout={layout}
                  range={range}
                  outputs={outputs}
                  workspace={galleryWorkspace}
                  activeIndex={activeIndex}
                  selecting={selection.selecting}
                  picked={selection.picked}
                  onOpen={setSelectedOutput}
                  onOpenDetails={openDetails}
                  onPick={selection.pick}
                  onLongPress={selection.longPress}
                />
              </Suspense>
            )}
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
          <GallerySearchEmpty count={outputs.length} />
          {!outputsLoading && outputs.length === 0 && visibleJobs.length === 0 && !searchQuery.trim() && (() => {
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

        </div>

        {/* Thumbnail sidebar */}
        {galleryView === 'feed' && <ThumbnailGallery
          activeIndex={activeIndex}
          onThumbnailClick={handleThumbnailClick}
        />}
        {detail && <Suspense fallback={null}>
          <GalleryDetailsDialog
            outputs={outputs}
            hasMore={outputs.length < outputsTotal}
            detail={detail}
            workspace={galleryWorkspace}
            onNavigate={navigateDetails}
            onNearEnd={loadMore}
            onClose={closeDetails}
          />
        </Suspense>}
        </>}
        </Suspense>
      </div>
    </main>
  )
}
