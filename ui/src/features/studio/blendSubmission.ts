import * as api from '../../api/client'
import { isGenerationJobSettled } from '../../lib/generationJobState'
import type { GenerationJob } from '../../types'
import { prependJob, updateJob, withJobs } from '../../stores/jobReducers'
import type { SliceGet, SliceSet } from '../../stores/storeApi'
import type { AppState } from '../../stores/useStore'
import { _jobTimingPatch } from './store/toolsSlice'

export async function submitBlendEdit(
  get: SliceGet<AppState>,
  set: SliceSet<AppState>,
  state: AppState,
): Promise<void> {
      if (!state.blendClipAPath || !state.blendClipBPath) return
      const prompt = (state.params.prompt as string || '').trim()

    const newJob: GenerationJob = {
      id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
      phase: '', message: 'Submitting blend...', outputFiles: [], error: null, oomInfo: null, createdAt: Date.now(),
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      try {
        const result = await api.submitBlend({
          clip_a_path: state.blendClipAPath,
          clip_b_path: state.blendClipBPath,
          prompt: prompt || 'smooth natural transition between the two clips',
          model_type: state.params.model_type as string,
          blend_mode: state.blendMode,
          overlap_sec: state.blendOverlapSec,
          // Blend-specific tuning knobs (exposed in BlendControls sliders)
          motion_prefix_sec: state.blendMotionPrefixSec,
          motion_suffix_sec: state.blendMotionSuffixSec,
          input_video_strength: state.blendAnchorStrength,
          seed: (state.params.seed as number) ?? -1,
          activated_loras: (state.params.activated_loras as string[]) || [],
          loras_multipliers: (state.params.loras_multipliers as string) || '',
          workspace: state.activeWorkspace,
          // Pass the full Studio params so the backend can inherit the user's
          // progressive_pipeline / num_inference_steps / guidance_scale /
          // negative_prompt settings, matching what a manual SE generation
          // would have used. Blend-specific fields (image_start/end, video_length,
          // resolution, image_prompt_type) are overridden server-side.
          base_params: state.params as unknown as Record<string, unknown>,
        })

        set(s => ({
          jobs: s.jobs.map(j => j === newJob ? { ...j, id: result.job_id, status: 'queued', message: 'Queued...' } : j),
        }))

        const pollInterval = setInterval(async () => {
          if (!get().jobs.find(j => j.id === result.job_id)) { clearInterval(pollInterval); return }
          try {
            const status = await api.fetchJobStatus(result.job_id)
            set(s => ({
              jobs: s.jobs.map(j => j.id !== result.job_id ? j : {
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
              set(s => {
                const remaining = s.jobs.filter(j => j.id !== result.job_id)
                return withJobs(remaining)
              })
              void get().maybeRefreshGallery({ message: 'New output ready' })
            } else if (isGenerationJobSettled(status.status)) {
              clearInterval(pollInterval)
              // Keep the failed/cancelled job in the queue so its placeholder
              // stays visible with the error message — user dismisses via X.
              set(s => withJobs(s.jobs))
            }
          } catch { /* ignore poll errors */ }
        }, 2000)
      } catch (e) {
        const msg = e instanceof Error ? e.message : 'Blend failed'
        // Submit itself failed (pre-queue). Convert the placeholder to a
        // failed state in place so the user sees what went wrong instead of
        // the tile silently disappearing.
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Blend failed:', msg)
      }
}
