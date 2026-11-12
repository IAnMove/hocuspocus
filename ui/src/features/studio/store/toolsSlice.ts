import * as api from '../../../api/client'
import i18n from '../../../i18n'
import { isGenerationJobSettled } from '../../../lib/generationJobState'
import type { GenerationJob } from '../../../types'
import { _downloadTimestampMs } from '../../../stores/civitaiSlice'
import { prependJob, removeJob, updateJob, withJobs } from '../../../stores/jobReducers'
import type { SliceCreator } from '../../../stores/storeApi'
import type { AppState } from '../../../stores/useStore'

export function _jobTimingPatch(status: api.ApiJobStatus): Partial<GenerationJob> {
  const patch: Partial<GenerationJob> = {}
  if (status.created_at !== undefined) {
    patch.createdAt = _downloadTimestampMs(status.created_at) ?? undefined
  }
  if (status.started_at !== undefined) {
    patch.startedAt = _downloadTimestampMs(status.started_at) ?? undefined
  }
  if (status.finished_at !== undefined) {
    patch.finishedAt = _downloadTimestampMs(status.finished_at) ?? undefined
  }
  if (status.queue_position !== undefined) {
    patch.queuePosition = status.queue_position
  }
  if (status.generation_details) {
    patch.generationDetails = status.generation_details
  }
  return patch
}

export type ToolsSlice = {
  // ── Tools area (standalone post-processing on an existing clip) ──────
  // Apply FlashVSR upscale or SeedVC revoice to any gallery output or an
  // uploaded clip, independent of a generation. See ToolsPanel.tsx + the
  // /api/v1/tools/* endpoints.
  toolsTool: 'upscale' | 'revoice' | 'remove_background'
  setToolsTool: (t: 'upscale' | 'revoice' | 'remove_background') => void
  /** Gallery filename (resolved against the workspace) OR an absolute upload path. */
  toolsSourcePath: string | null
  toolsSourceName: string | null
  toolsSourceUrl: string | null
  toolsSourceAssetId: string | null
  toolsSourceWorkspace: string | null
  toolsSourceKind: 'image' | 'video' | 'audio' | 'model3d' | null
  setToolsSource: (src: { path: string; name: string; url: string | null; assetId?: string | null; workspace?: string | null; kind?: 'image' | 'video' | 'audio' | 'model3d' | null } | null) => void
  toolsUpscaleMethod: string
  setToolsUpscaleMethod: (m: string) => void
  toolsRevoiceMode: 'single' | 'two'
  setToolsRevoiceMode: (m: 'single' | 'two') => void
  toolsRevoiceRefs: ({ filename: string; path: string } | null)[]
  setToolsRevoiceRef: (index: number, ref: { filename: string; path: string } | null) => void
  toolsRemoveBackgroundInstruction: string
  setToolsRemoveBackgroundInstruction: (instruction: string) => void
  /** Incremented when a tool publishes an asset so mounted Tools panels can refresh their catalog. */
  toolsAssetsRevision: number
  toolsSubmitting: boolean
  runTool: () => Promise<void>
  /** Gallery one-click: upscale a specific clip now, with the configured method. */
  quickUpscaleClip: (name: string, url: string | null) => Promise<void>
  /** Gallery one-click: load a clip into the Tools panel for a tool that needs
   *  setup before running (e.g. revoice needs voice references), and switch to it. */
  sendClipToTools: (name: string, url: string | null, tool: 'upscale' | 'revoice') => void
}

/** runTool passes the store snapshot into the tools command submission. */
export type ToolsSliceHost = AppState

export const createToolsSlice: SliceCreator<ToolsSlice, ToolsSliceHost> = (set, get) => ({
  // ── Tools area (standalone post-processing on an existing clip) ──────
  toolsTool: 'upscale',
  setToolsTool: (t) => set({ toolsTool: t }),
  toolsSourcePath: null,
  toolsSourceName: null,
  toolsSourceUrl: null,
  toolsSourceAssetId: null,
  toolsSourceWorkspace: null,
  toolsSourceKind: null,
  setToolsSource: (src) => set(src
    ? {
      toolsSourcePath: src.path,
      toolsSourceName: src.name,
      toolsSourceUrl: src.url,
      toolsSourceAssetId: src.assetId ?? null,
      toolsSourceWorkspace: src.workspace ?? null,
      toolsSourceKind: src.kind ?? null,
    }
    : {
      toolsSourcePath: null,
      toolsSourceName: null,
      toolsSourceUrl: null,
      toolsSourceAssetId: null,
      toolsSourceWorkspace: null,
      toolsSourceKind: null,
    }),
  toolsUpscaleMethod: 'flashvsr2',
  setToolsUpscaleMethod: (m) => set({ toolsUpscaleMethod: m }),
  toolsRevoiceMode: 'single',
  setToolsRevoiceMode: (m) => set({ toolsRevoiceMode: m }),
  toolsRevoiceRefs: [null, null],
  setToolsRevoiceRef: (index, ref) => set(s => {
    const next = [...s.toolsRevoiceRefs]
    while (next.length <= index) next.push(null)
    next[index] = ref
    return { toolsRevoiceRefs: next }
  }),
  toolsRemoveBackgroundInstruction: '',
  setToolsRemoveBackgroundInstruction: (instruction) => set({ toolsRemoveBackgroundInstruction: instruction }),
  toolsAssetsRevision: 0,
  toolsSubmitting: false,
  runTool: async () => {
    const s = get()
    if (s.toolsSubmitting) return
    const source = s.toolsSourcePath
    if (!source) return
    const tool = s.toolsTool

    // Revoice needs at least one resolved voice reference.
    const refPaths = s.toolsRevoiceRefs
      .filter((r): r is { filename: string; path: string } => !!r && !!r.path)
      .map(r => r.path)
    if (tool === 'revoice' && refPaths.length === 0) return
    if (tool === 'remove_background' && s.toolsSourceKind !== 'image' && s.toolsSourceKind !== 'video') return
    if (tool === 'upscale' && s.toolsSourceKind !== 'image' && s.toolsSourceKind !== 'video') return
    if (tool === 'revoice' && s.toolsSourceKind !== 'video') return
    set({ toolsSubmitting: true })

    // Placeholder job tile — mirrors the blend/edit submit pattern so the
    // progress shows in the main feed and the gallery refreshes on completion.
    const removingBackground = tool === 'remove_background'
    const newJob: GenerationJob = {
      id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
      phase: '', message: tool === 'upscale'
        ? 'Submitting upscale...'
        : tool === 'revoice'
          ? 'Submitting revoice...'
          : i18n.t('tools.submittingRemoveBackground', { ns: 'studio' }),
      outputFiles: [], error: null, oomInfo: null, createdAt: Date.now(),
    }
    set(st => {
      return prependJob(st.jobs, newJob)
    })

    try {
      const result = tool === 'upscale'
        ? await (async () => {
          const { prepareStudioToolsUpscaleSubmission, toolsUpscaleParamsFromState } =
            await import('../toolsCommandSubmission')
          return (await prepareStudioToolsUpscaleSubmission(
            toolsUpscaleParamsFromState(s),
            s,
            get,
            { actor: 'user', capability: 'tools.upscale' },
          )).submit()
        })()
        : tool === 'revoice'
          ? await api.submitToolRevoice({ video_path: source, voice_ref_paths: refPaths, mode: s.toolsRevoiceMode, workspace: s.activeWorkspace })
          : await api.submitToolRemoveBackground({
            asset_id: s.toolsSourceAssetId || undefined,
            source,
            source_workspace: s.toolsSourceWorkspace || undefined,
            workspace: s.activeWorkspace,
            instruction: s.toolsRemoveBackgroundInstruction,
            provenance: { actor: 'user' },
          })

      const taskId = 'task_id' in result && typeof result.task_id === 'string'
        ? result.task_id
        : result.job_id
      set(st => ({
        jobs: st.jobs.map(j => j === newJob ? {
          ...j,
          id: result.job_id,
          taskId,
          status: 'queued',
          message: removingBackground ? i18n.t('tools.queuedRemoveBackground', { ns: 'studio' }) : 'Queued...',
        } : j),
      }))

      const pollInterval = setInterval(async () => {
        if (!get().jobs.find(j => j.id === result.job_id)) { clearInterval(pollInterval); return }
        try {
          const status = await api.fetchJobStatus(result.job_id)
          set(st => ({
            jobs: st.jobs.map(j => j.id !== result.job_id ? j : {
              ...j, status: status.status, progress: status.progress / 100,
              step: status.step ?? 0, totalSteps: status.total_steps ?? 0,
              phase: status.phase ?? '', message: status.message,
              outputFiles: status.output_files, error: status.error, oomInfo: status.oom_info ?? null,
              ..._jobTimingPatch(status),
            }),
          }))
          if (status.status === 'running') void get().maybeRefreshGallery()
          if (status.status === 'completed') {
            clearInterval(pollInterval)
            if (removingBackground) set(st => ({ toolsAssetsRevision: st.toolsAssetsRevision + 1 }))
            set(st => {
              return removeJob(st.jobs, j => j.id === result.job_id)
            })
            void get().maybeRefreshGallery({ message: 'New output ready' })
          } else if (isGenerationJobSettled(status.status)) {
            clearInterval(pollInterval)
            // Keep the terminal tile visible so the user can inspect or dismiss it.
            set(st => withJobs(st.jobs))
          }
        } catch { /* ignore poll errors */ }
      }, 2000)
    } catch (e) {
      const msg = e instanceof Error ? e.message : (tool === 'upscale'
        ? 'Upscale failed'
        : tool === 'revoice'
          ? 'Revoice failed'
          : i18n.t('tools.removeBackgroundFailed', { ns: 'studio' }))
      set(st => updateJob(st.jobs, j => j === newJob, j => ({
        ...j, id: j.id || `tool-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
      })))
      console.error(`Tool ${tool} failed:`, msg)
    } finally {
      set({ toolsSubmitting: false })
    }
  },
  quickUpscaleClip: async (name, url) => {
    // Point the Tools state at this clip and run an upscale immediately,
    // reusing runTool()'s submit+poll. The Tools panel reflects this clip
    // afterward (harmless — and convenient if the user opens it).
    set({ toolsTool: 'upscale', toolsSourcePath: name, toolsSourceName: name, toolsSourceUrl: url, toolsSourceAssetId: null, toolsSourceWorkspace: null, toolsSourceKind: 'video' })
    // The shortcut is exposed from the video activity view, so the current
    // mode is usually video. Switch to Tools before runTool snapshots the
    // form; this also mounts the durable ACK panel that presents the command.
    const state = get()
    state.setSettingsOpen(false)
    state.setDashboardOpen(false)
    state.setSidebarMode('studio')
    state.setSidebarOpen(true)
    state.setGenerationMode('tools')
    state.setMediaFilter('videos')
    await get().runTool()
  },
  sendClipToTools: (name, url, tool) => {
    set({ toolsTool: tool, toolsSourcePath: name, toolsSourceName: name, toolsSourceUrl: url, toolsSourceAssetId: null, toolsSourceWorkspace: null, toolsSourceKind: 'video' })
    get().setGenerationMode('tools')
    get().setMediaFilter('all')
  },
})
