import * as api from '../../api/client'
import { isGenerationJobSettled } from '../../lib/generationJobState'
import type { GenerationJob } from '../../types'
import { prependJob, updateJob, withJobs } from '../../stores/jobReducers'
import type { SliceGet, SliceSet } from '../../stores/storeApi'
import type { AppState } from '../../stores/useStore'
import { _jobTimingPatch } from './store/toolsSlice'

export async function submitRetakeInpaintEdit(
  get: SliceGet<AppState>,
  set: SliceSet<AppState>,
  state: AppState,
): Promise<void> {
      if (!state.editVideoPath) return
      const prompt = (state.params.prompt as string || '').trim()
      if (!prompt) return

    const newJob: GenerationJob = {
      id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
      phase: '', message: 'Submitting...', outputFiles: [], error: null, oomInfo: null, createdAt: Date.now(),
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      try {
        let result: { job_id: string }
        if (state.editSubMode === 'edit_anything') {
          result = await api.submitEditAnything({
            video_path: state.editVideoPath,
            prompt,
            model_type: state.params.model_type as string,
            start_time: state.editStartTime,
            end_time: state.editEndTime,
            lora_strength: state.editAnythingLoraStrength,
            retake_strength: state.editRetakeStrength,
            seed: (state.params.seed as number) ?? -1,
            // Edit Anything LoRA card: start with CFG=1 on distilled; raise
            // only if the edit is too weak. We route the user's global CFG
            // slider through so they can experiment.
            guidance_scale: (state.params.guidance_scale as number) ?? 1.0,
            num_inference_steps: (state.params.num_inference_steps as number) ?? 8,
            negative_prompt: (state.params.negative_prompt as string) || '',
            activated_loras: (state.params.activated_loras as string[]) || [],
            loras_multipliers: (state.params.loras_multipliers as string) || '',
            workspace: state.activeWorkspace,
            // Optional boundary anchors. Empty values mean "use source
            // frames" (today's auto-extract behavior); ltx2.py treats
            // missing/null/empty path as "fall back to source".
            ...(state.editAnythingStartAnchor ? { start_anchor_path: state.editAnythingStartAnchor } : {}),
            ...(state.editAnythingEndAnchor ? { end_anchor_path: state.editAnythingEndAnchor } : {}),
          })
        } else if (state.editSubMode === 'inpaint') {
          result = await api.submitInpaint({
            video_path: state.editVideoPath,
            description: prompt,
            sam_target: state.editSamTarget || undefined,
            invert_mask: state.editInvertMask || undefined,
            start_time: state.editStartTime,
            end_time: state.editEndTime,
            model_type: state.params.model_type as string,
            seed: (state.params.seed as number) ?? -1,
            // Inpaint needs CFG > 1.0 to make the prompt actually influence
            // the masked region. The edit-specific editPromptStrength slider
            // (default 3.5) drives this; the global params.guidance_scale is
            // fine for normal generation but would silently default to 1.0
            // and silently break inpaint.
            guidance_scale: state.editPromptStrength,
            retake_strength: state.editRetakeStrength,
            num_inference_steps: (state.params.num_inference_steps as number) ?? 8,
            negative_prompt: (state.params.negative_prompt as string) || '',
            resolution: (state.params.resolution as string) || '',
            activated_loras: (state.params.activated_loras as string[]) || [],
            loras_multipliers: (state.params.loras_multipliers as string) || '',
            masks_path: state.editMasksPath || undefined,
            workspace: state.activeWorkspace,
          })
        } else {
          result = await api.submitRetake({
            video_path: state.editVideoPath,
            start_time: state.editStartTime,
            end_time: state.editEndTime,
            prompt,
            model_type: state.params.model_type as string,
            retake_strength: state.editRetakeStrength,
            retake_engine: state.editRetakeEngine,
            regenerate_audio: state.editRegenerateAudio,
            seed: (state.params.seed as number) ?? -1,
            // Retake also benefits from CFG > 1.0 when the user provides a
            // prompt that should drive the regenerated region (e.g. new
            // outfit, different style). Previously stuck at 1.0 via
            // params.guidance_scale fallback — same silent bug as inpaint.
            guidance_scale: state.editPromptStrength,
            num_inference_steps: (state.params.num_inference_steps as number) ?? 8,
            negative_prompt: (state.params.negative_prompt as string) || '',
            resolution: (state.params.resolution as string) || '',
            activated_loras: (state.params.activated_loras as string[]) || [],
            loras_multipliers: (state.params.loras_multipliers as string) || '',
            workspace: state.activeWorkspace,
          })
        }

        set(s => ({
          jobs: s.jobs.map(j => j === newJob ? { ...j, id: result.job_id, status: 'queued', message: 'Queued...' } : j),
        }))

        // Standard job polling (same as regular generation)
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
        const msg = e instanceof Error ? e.message : 'Generation failed'
        // Submit itself failed (pre-queue). Convert the placeholder to a
        // failed state in place so the user sees what went wrong instead of
        // the tile silently disappearing.
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Edit generation failed:', msg)
      }
}
