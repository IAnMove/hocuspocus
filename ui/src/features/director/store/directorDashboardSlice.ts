import * as api from '../../../api/client'
import { mapDirectorClipImages } from '../../../lib/directorClipImages'
import type { PipelineListItem, PipelineRepairState, SavedPipelineState } from '../../../types'
import type { DirectorSlice } from '../../../stores/directorSlice'
import type { GallerySlice } from '../../../stores/gallerySlice'
import type { SliceCreator } from '../../../stores/storeApi'

export const DASHBOARD_PIPELINE_PAGE_SIZE = 8
const DIRECTOR_REPAIR_POLL_MS = 2000
const DIRECTOR_REPAIR_ACTIVE = new Set(['queued', 'running', 'cancelling'])
type DirectorRepairPoll = {
  operationId: string
  timer: number | null
}
const _directorRepairPolls = new Map<string, DirectorRepairPoll>()
const _directorRepairDiscoveries = new Map<string, object>()
let _dashboardPipelineLoadToken = 0
let _dashboardPipelineListLoadToken = 0

function _repairNeedsPolling(repair: PipelineRepairState | null | undefined): boolean {
  return !!repair && DIRECTOR_REPAIR_ACTIVE.has(repair.status)
}

function _stopDirectorRepairPoll(pid: string): void {
  const poll = _directorRepairPolls.get(pid)
  if (poll?.timer != null) window.clearTimeout(poll.timer)
  _directorRepairPolls.delete(pid)
}

export function disposeDirectorRepairPolls(): void {
  for (const pid of _directorRepairPolls.keys()) {
    _stopDirectorRepairPoll(pid)
  }
  _directorRepairDiscoveries.clear()
}

export type DirectorDashboardSlice = {
  // Director Pipeline Dashboard
  dashboardOpen: boolean
  dashboardPipelineList: PipelineListItem[]
  dashboardPipelineTotal: number
  dashboardSelectedPipeline: SavedPipelineState | null
  dashboardLoading: boolean
  dashboardLoadError: string | null
  dashboardRetryPipelineId: string | null
  setDashboardOpen: (open: boolean, preferredPipelineId?: string) => void
  loadPipelineList: (preferredPipelineId?: string) => Promise<void>
  /** Resume UI polling for every run in `pipelines` whose repair is still active on the server. */
  discoverActiveDirectorRepairs: (pipelines: PipelineListItem[]) => void
  loadMorePipelineList: () => Promise<void>
  loadSavedPipeline: (pid: string) => Promise<void>
  retryDashboardLoad: () => Promise<void>
  tagClip: (pid: string, clipIndex: number, tag: string | null) => Promise<void>
  updateClipPrompt: (pid: string, clipIndex: number, body: { video_prompt?: string; image_prompt?: string; soundtrack_drive?: boolean }) => Promise<void>
  selectClipVideo: (pid: string, clipIndex: number, filename: string) => Promise<void>
  startPipelineRepair: (pid: string) => Promise<PipelineRepairState>
  cancelPipelineRepair: (pid: string) => Promise<PipelineRepairState>
  pollPipelineRepair: (pid: string, operationId: string) => void
  rerunClipImage: (pid: string, clipIndex: number, prompt?: string) => Promise<unknown>
  rerunClipVideo: (pid: string, clipIndex: number, prompt?: string) => Promise<unknown>
  rerunH3Segment: (pid: string, clipIndex: number, segmentIndex: number, prompt?: string) => Promise<unknown>
  rejoinPipelineClips: (pid: string) => Promise<unknown>
  resumePipeline: (pid: string) => Promise<void>
  deletePipeline: (pid: string) => Promise<void>
  loadDirectorFromPipeline: (pid: string) => Promise<void>
}

/** resumePipeline and loadDirectorFromPipeline write sibling director, gallery, and pipeline fields. */
export type DirectorDashboardSliceHost = DirectorDashboardSlice & Pick<DirectorSlice,
  | 'directorLoading'
  | 'directorError'
  | 'directorSceneDescription'
  | 'directorClipPlans'
  | 'directorClipImages'
  | 'directorStep'
  | 'directorAutoMode'
  | 'directorSeamless'
  | 'directorShotImageGuidance'
> & Pick<GallerySlice,
  | 'maybeRefreshGallery'
  | 'loadOutputs'
  | 'loadWorkspaces'
> & {
  pipelineId: string | null
  pipelineStatus: api.PipelineStatus | null
  pipelinePolling: boolean
  directorEditorDetached: boolean
  pollPipelineStatus: () => void
  sidebarMode: 'director' | 'studio'
}

export const createDirectorDashboardSlice: SliceCreator<DirectorDashboardSlice, DirectorDashboardSliceHost> = (set, get) => ({
  // Director Pipeline Dashboard
  dashboardOpen: false,
  dashboardPipelineList: [],
  dashboardPipelineTotal: 0,
  dashboardSelectedPipeline: null,
  dashboardLoading: false,
  dashboardLoadError: null,
  dashboardRetryPipelineId: null,
  setDashboardOpen: (open, preferredPipelineId) => {
    set({ dashboardOpen: open, dashboardLoadError: null, dashboardRetryPipelineId: null })
    if (open) {
      get().loadPipelineList(preferredPipelineId)
      if (preferredPipelineId) {
        get().loadSavedPipeline(preferredPipelineId)
      } else {
        const selected = get().dashboardSelectedPipeline
        if (selected) get().loadSavedPipeline(selected.pipeline_id)
      }
    }
  },
  loadPipelineList: async (preferredPipelineId) => {
    const loadToken = ++_dashboardPipelineListLoadToken
    const retryPipelineId = preferredPipelineId || get().dashboardSelectedPipeline?.pipeline_id || null
    try {
      const pageSize = Math.max(DASHBOARD_PIPELINE_PAGE_SIZE, get().dashboardPipelineList.length)
      const { pipelines, total } = await api.fetchPipelineList({ limit: pageSize, offset: 0 })
      if (loadToken !== _dashboardPipelineListLoadToken) return
      set({
        dashboardPipelineList: pipelines,
        dashboardPipelineTotal: total,
        dashboardLoadError: null,
        dashboardRetryPipelineId: null,
      })
      // Open the newest thread (or a preferred / still-running one). Older
      // threads stay as list rows until the user clicks them.
      const preferred = preferredPipelineId
        ? pipelines.find(pipeline => pipeline.id === preferredPipelineId)
        : undefined
      const active = preferred
        || pipelines.find(pipeline => pipeline.status === 'running')
        || (!get().dashboardSelectedPipeline ? pipelines[0] : undefined)
      if (active && get().dashboardSelectedPipeline?.pipeline_id !== active.id) {
        await get().loadSavedPipeline(active.id)
      } else if (preferredPipelineId && !preferred) {
        await get().loadSavedPipeline(preferredPipelineId)
      }

      // The repair worker belongs to the server, so a browser reload must
      // rediscover active operations and resume UI polling without requiring
      // the Dashboard to be opened first (boot does it through
      // reconnectDirectorPipelines). Discovery stays separate from the selected
      // pipeline so bootstrapping never opens or changes the overlay.
      get().discoverActiveDirectorRepairs(pipelines)
    } catch (e) {
      if (loadToken !== _dashboardPipelineListLoadToken) return
      console.error('Failed to load pipeline list:', e)
      set({
        dashboardLoadError: e instanceof Error ? e.message : 'Failed to load pipeline list',
        dashboardRetryPipelineId: retryPipelineId,
      })
    }
  },
  discoverActiveDirectorRepairs: (pipelines) => {
    for (const item of pipelines) {
      if (!item.repair_status || !DIRECTOR_REPAIR_ACTIVE.has(item.repair_status)) continue
      if (_directorRepairPolls.has(item.id) || _directorRepairDiscoveries.has(item.id)) continue

      const discovery = {}
      _directorRepairDiscoveries.set(item.id, discovery)
      void api.fetchSavedPipeline(item.id).then(pipeline => {
        if (_directorRepairDiscoveries.get(item.id) !== discovery) return
        if (_directorRepairPolls.has(item.id)) return

        const repair = pipeline.repair
        if (_repairNeedsPolling(repair)) {
          get().pollPipelineRepair(item.id, repair!.operation_id)
          return
        }

        // The operation may have finished between the list and detail
        // requests. Reflect that terminal state and refresh newly-created
        // media instead of waiting for another Dashboard visit.
        set(s => ({
          dashboardPipelineList: s.dashboardPipelineList.map(entry =>
            entry.id === item.id
              ? { ...entry, repair_status: repair?.status || null }
              : entry),
        }))
        void get().maybeRefreshGallery()
      }).catch(e => {
        console.warn(`Failed to reconnect Director repair for ${item.id}:`, e)
      }).finally(() => {
        if (_directorRepairDiscoveries.get(item.id) === discovery) {
          _directorRepairDiscoveries.delete(item.id)
        }
      })
    }
  },
  loadMorePipelineList: async () => {
    const loadToken = ++_dashboardPipelineListLoadToken
    const existing = get().dashboardPipelineList
    try {
      const { pipelines, total } = await api.fetchPipelineList({
        limit: DASHBOARD_PIPELINE_PAGE_SIZE,
        offset: existing.length,
      })
      if (loadToken !== _dashboardPipelineListLoadToken) return
      const seen = new Set(existing.map(item => item.id))
      set({
        dashboardPipelineList: [...existing, ...pipelines.filter(item => !seen.has(item.id))],
        dashboardPipelineTotal: total,
        dashboardLoadError: null,
      })
    } catch (e) {
      if (loadToken !== _dashboardPipelineListLoadToken) return
      console.error('Failed to load more pipelines:', e)
      set({
        dashboardLoadError: e instanceof Error ? e.message : 'Failed to load pipeline list',
      })
    }
  },
  loadSavedPipeline: async (pid) => {
    const loadToken = ++_dashboardPipelineLoadToken
    set({ dashboardLoading: true, dashboardLoadError: null, dashboardRetryPipelineId: pid })
    try {
      const pipeline = await api.fetchSavedPipeline(pid)
      if (loadToken !== _dashboardPipelineLoadToken) return
      set({ dashboardSelectedPipeline: pipeline, dashboardLoading: false, dashboardLoadError: null, dashboardRetryPipelineId: null })
      if (_repairNeedsPolling(pipeline.repair)) {
        get().pollPipelineRepair(pid, pipeline.repair!.operation_id)
      }
    } catch (e) {
      if (loadToken !== _dashboardPipelineLoadToken) return
      const message = e instanceof Error ? e.message : 'Failed to load pipeline'
      const stillWriting = /not found|404/i.test(message)
      console.error('Failed to load pipeline:', e)
      set({
        dashboardLoading: false,
        dashboardLoadError: stillWriting ? null : message,
        dashboardRetryPipelineId: pid,
      })
    }
  },
  retryDashboardLoad: async () => {
    const state = get()
    await get().loadPipelineList(state.dashboardRetryPipelineId || state.dashboardSelectedPipeline?.pipeline_id || undefined)
  },
  deletePipeline: async (pid) => {
    // Clear the selection AND drop the pid from the list in the same
    // update: the dashboard's auto-load effect selects pipelineList[0]
    // whenever selection is null, so a stale list would immediately
    // re-fetch the pipeline being deleted (re-mounting its <img>/<video>
    // elements and re-locking the files on Windows).
    _dashboardPipelineLoadToken += 1
    _dashboardPipelineListLoadToken += 1
    set(s => ({
      dashboardSelectedPipeline: null,
      dashboardPipelineList: s.dashboardPipelineList.filter(p => p.id !== pid),
    }))
    await api.deletePipeline(pid)
    await get().loadPipelineList()
    // Pipeline media were gallery items too — refresh the feed.
    get().loadOutputs()
    get().loadWorkspaces()
  },
  updateClipPrompt: async (pid, clipIndex, body) => {
    const pipeline = await api.updatePipelineClipPrompt(pid, clipIndex, body)
    set(s => {
      if (!s.dashboardSelectedPipeline || s.dashboardSelectedPipeline.pipeline_id !== pid) {
        return { dashboardSelectedPipeline: pipeline }
      }
      return { dashboardSelectedPipeline: pipeline }
    })
  },
  selectClipVideo: async (pid, clipIndex, filename) => {
    await api.selectPipelineClipVideo(pid, clipIndex, filename)
    const pipeline = await api.fetchSavedPipeline(pid)
    set({ dashboardSelectedPipeline: pipeline })
  },
  tagClip: async (pid, clipIndex, tag) => {
    try {
      await api.tagPipelineClip(pid, clipIndex, tag)
      // Update local state
      set(s => {
        if (!s.dashboardSelectedPipeline || s.dashboardSelectedPipeline.pipeline_id !== pid) return {}
        const clips = [...s.dashboardSelectedPipeline.clips]
        if (clipIndex < clips.length) {
          clips[clipIndex] = { ...clips[clipIndex], tag: tag as 'good' | 'needs_work' | null }
        }
        return { dashboardSelectedPipeline: { ...s.dashboardSelectedPipeline, clips } }
      })
    } catch (e) {
      console.error('Failed to tag clip:', e)
    }
  },
  startPipelineRepair: async (pid: string) => {
    const { repair } = await api.startPipelineRepair(pid)
    set(s => {
      const dashboardPipelineList = s.dashboardPipelineList.map(item =>
        item.id === pid ? { ...item, repair_status: repair.status } : item)
      if (!s.dashboardSelectedPipeline || s.dashboardSelectedPipeline.pipeline_id !== pid) {
        return { dashboardPipelineList }
      }
      return {
        dashboardPipelineList,
        dashboardSelectedPipeline: {
          ...s.dashboardSelectedPipeline,
          repair,
        },
      }
    })
    get().pollPipelineRepair(pid, repair.operation_id)
    return repair
  },
  cancelPipelineRepair: async (pid: string) => {
    const { repair } = await api.cancelPipelineRepair(pid)
    set(s => {
      const dashboardPipelineList = s.dashboardPipelineList.map(item =>
        item.id === pid ? { ...item, repair_status: repair.status } : item)
      if (!s.dashboardSelectedPipeline || s.dashboardSelectedPipeline.pipeline_id !== pid) {
        return { dashboardPipelineList }
      }
      return {
        dashboardPipelineList,
        dashboardSelectedPipeline: {
          ...s.dashboardSelectedPipeline,
          repair,
        },
      }
    })
    get().pollPipelineRepair(pid, repair.operation_id)
    return repair
  },
  pollPipelineRepair: (pid: string, operationId: string) => {
    const existing = _directorRepairPolls.get(pid)
    if (existing?.operationId === operationId) return
    if (existing) _stopDirectorRepairPoll(pid)

    const poll: DirectorRepairPoll = { operationId, timer: null }
    _directorRepairPolls.set(pid, poll)

    const tick = async () => {
      if (_directorRepairPolls.get(pid) !== poll) return
      poll.timer = null
      try {
        const pipeline = await api.fetchSavedPipeline(pid)
        if (_directorRepairPolls.get(pid) !== poll) return

        const repair = pipeline.repair
        set(s => {
          const dashboardPipelineList = s.dashboardPipelineList.map(item =>
            item.id === pid ? { ...item, repair_status: repair?.status || null } : item)
          if (!s.dashboardSelectedPipeline || s.dashboardSelectedPipeline.pipeline_id !== pid) {
            return { dashboardPipelineList }
          }
          return { dashboardPipelineList, dashboardSelectedPipeline: pipeline }
        })

        if (repair?.operation_id !== operationId) {
          _stopDirectorRepairPoll(pid)
          if (_repairNeedsPolling(repair)) {
            get().pollPipelineRepair(pid, repair!.operation_id)
          } else {
            void get().loadPipelineList()
            void get().loadOutputs()
          }
          return
        }
        if (!_repairNeedsPolling(repair)) {
          _stopDirectorRepairPoll(pid)
          void get().loadPipelineList()
          void get().loadOutputs()
          return
        }
      } catch (e) {
        console.warn(`Director repair poll failed for ${pid}; retrying:`, e)
      }

      if (_directorRepairPolls.get(pid) === poll) {
        poll.timer = window.setTimeout(tick, DIRECTOR_REPAIR_POLL_MS)
      }
    }

    void tick()
  },
  rerunClipImage: async (pid: string, clipIndex: number, prompt?: string) => {
    set({ dashboardLoading: true })
    try {
      const result = await api.rerunClipImage(pid, clipIndex, prompt)
      // Refresh the pipeline to get updated state
      const pipeline = await api.fetchSavedPipeline(pid)
      set({ dashboardSelectedPipeline: pipeline, dashboardLoading: false })
      // New files (rerun clip / rejoin video) land in the outputs folder —
      // refresh the gallery so they appear without a browser reload.
      get().loadOutputs()
      return result
    } catch (e) {
      console.error('Re-run image failed:', e)
      set({ dashboardLoading: false })
      throw e
    }
  },
  rerunClipVideo: async (pid: string, clipIndex: number, prompt?: string) => {
    set({ dashboardLoading: true })
    try {
      const result = await api.rerunClipVideo(pid, clipIndex, prompt)
      const pipeline = await api.fetchSavedPipeline(pid)
      set({ dashboardSelectedPipeline: pipeline, dashboardLoading: false })
      // New files (rerun clip / rejoin video) land in the outputs folder —
      // refresh the gallery so they appear without a browser reload.
      get().loadOutputs()
      return result
    } catch (e) {
      console.error('Re-run video failed:', e)
      set({ dashboardLoading: false })
      throw e
    }
  },
  rerunH3Segment: async (pid: string, clipIndex: number, segmentIndex: number, prompt?: string) => {
    set({ dashboardLoading: true })
    try {
      const result = await api.rerunH3Segment(pid, clipIndex, segmentIndex, prompt)
      const pipeline = await api.fetchSavedPipeline(pid)
      await get().loadOutputs()
      set({ dashboardSelectedPipeline: pipeline, dashboardLoading: false })
      return result
    } catch (e) {
      console.error('H3 segment regeneration failed:', e)
      set({ dashboardLoading: false })
      throw e
    }
  },
  rejoinPipelineClips: async (pid: string) => {
    set({ dashboardLoading: true })
    try {
      const result = await api.rejoinPipeline(pid)
      const pipeline = await api.fetchSavedPipeline(pid)
      set({ dashboardSelectedPipeline: pipeline, dashboardLoading: false })
      // New files (rerun clip / rejoin video) land in the outputs folder —
      // refresh the gallery so they appear without a browser reload.
      get().loadOutputs()
      return result
    } catch (e) {
      console.error('Rejoin failed:', e)
      set({ dashboardLoading: false })
      throw e
    }
  },
  resumePipeline: async (pid: string) => {
    // Kick the crashed pipeline back into running server-side, then close
    // the Dashboard and reconnect the Director view to it so progress shows.
    await api.resumePipeline(pid)
    set({
      dashboardOpen: false,
      pipelineId: pid,
      pipelineStatus: null,
      pipelinePolling: true,
      directorEditorDetached: false,
      directorLoading: true,
      directorError: null,
    })
    get().pollPipelineStatus()
    void get().loadSavedPipeline(pid)
    void get().loadPipelineList(pid)
  },
  loadDirectorFromPipeline: async (pid) => {
    try {
      const pipeline = await api.fetchSavedPipeline(pid)
      set({
        sidebarMode: 'director' as const,
        directorSceneDescription: pipeline.scene_description || '',
        directorClipPlans: pipeline.clips.map(c => ({
          video_prompt: c.video_prompt || '',
          image_prompt: c.image_prompt || '',
        })),
        directorClipImages: mapDirectorClipImages(
          pipeline.clips.map(c => ({
            index: c.index,
            shot_id: c.shot_id,
            image_prompt: c.image_prompt,
            filename: c.start_image_filename,
          })),
        ),
        directorStep: 'review_video',
        directorAutoMode: pipeline.auto_mode,
        directorSeamless: pipeline.seamless,
        directorShotImageGuidance: pipeline.shot_image_guidance || 'auto',
        dashboardOpen: true,
        dashboardSelectedPipeline: pipeline,
      })
    } catch (e) {
      console.error('Failed to load Director pipeline:', e)
    }
  },
})
