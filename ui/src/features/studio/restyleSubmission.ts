import * as api from '../../api/client'
import { isGenerationJobSettled } from '../../lib/generationJobState'
import type { GenerationJob } from '../../types'
import { prependJob, updateJob, withJobs } from '../../stores/jobReducers'
import type { SliceGet, SliceSet } from '../../stores/storeApi'
import type { AppState } from '../../stores/useStore'
import { editJobGenerationDetails } from './editJobDetails'
import { _jobTimingPatch } from './store/toolsSlice'

export async function submitRestyleEdit(
  get: SliceGet<AppState>,
  set: SliceSet<AppState>,
  state: AppState,
): Promise<void> {
    // Standalone branch: the prompt is OPTIONAL here (the server has a
    // sensible default), unlike the shared edit block below which
    // hard-requires one.
    // Repaint is the easy front door to the proven Studio Video/Frames
    // SCAIL-2 Animate path: an edited first frame defines the finished look
    // while the source video supplies motion and camera movement.
      if (!state.editVideoPath || !state.editRepaintFramePath) return
      const repaintMappings = state.editRepaintMappings.slice(0, 5)
      if (repaintMappings.some(mapping => !mapping.source.trim() || !mapping.target.trim())) return
      const promptText = ((state.params.prompt as string) || '').trim()
      const newJob: GenerationJob = {
        id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
        phase: '', message: 'Submitting repaint...', outputFiles: [], error: null, oomInfo: null,
      generationDetails: editJobGenerationDetails(state),
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      try {
        const repaintModel = (state.params.model_type as string) || ''
        const repaintIsScail2 = repaintModel === 'scail2_14B_fast' || repaintModel === 'scail2_14B'
        const result = await api.submitRepaint({
          video_path: state.editVideoPath,
          target_frame_path: state.editRepaintFramePath,
          region_mappings: repaintMappings.map(mapping => ({
            id: mapping.id,
            source: mapping.source.trim(),
            target: mapping.target.trim(),
          })),
          ...(promptText ? { prompt: promptText } : {}),
          resolution_profile: state.editRepaintResolutionProfile,
          ...(repaintIsScail2 ? {
            model_type: repaintModel,
            num_inference_steps: (state.params.num_inference_steps as number) ?? undefined,
            ...(repaintModel === 'scail2_14B' ? {
              guidance_scale: (state.params.guidance_scale as number) ?? undefined,
            } : {}),
          } : {}),
          start_time: state.editStartTime,
          end_time: state.editEndTime,
          seed: (state.params.seed as number) ?? -1,
          negative_prompt: (state.params.negative_prompt as string) || '',
          activated_loras: (state.params.activated_loras as string[]) || [],
          loras_multipliers: (state.params.loras_multipliers as string) || '',
          workspace: state.activeWorkspace,
        })

        set(s => ({
          jobs: s.jobs.map(j => j === newJob
            ? { ...j, id: result.job_id, status: 'queued', message: 'Queued...' }
            : j),
        }))

        const pollInterval = setInterval(async () => {
          if (!get().jobs.find(j => j.id === result.job_id)) {
            clearInterval(pollInterval)
            return
          }
          try {
            const status = await api.fetchJobStatus(result.job_id)
            set(s => ({
              jobs: s.jobs.map(j => j.id !== result.job_id ? j : {
                ...j,
                status: status.status,
                progress: status.progress / 100,
                step: status.step ?? 0,
                totalSteps: status.total_steps ?? 0,
                phase: status.phase ?? '',
                message: status.message,
                outputFiles: status.output_files,
                error: status.error,
                oomInfo: status.oom_info ?? null,
                ..._jobTimingPatch(status),
              }),
            }))
            if (status.status === 'running') void get().maybeRefreshGallery()
            if (status.status === 'completed') {
              clearInterval(pollInterval)
              set(s => {
                const remaining = s.jobs.filter(j => j.id !== result.job_id)
                return withJobs(remaining)
              })
              void get().maybeRefreshGallery({ message: 'New output ready' })
            } else if (isGenerationJobSettled(status.status)) {
              clearInterval(pollInterval)
              set(s => withJobs(s.jobs))
            }
          } catch { /* ignore poll errors */ }
        }, 2000)
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Repaint failed'
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Repaint failed:', msg)
      }
}
