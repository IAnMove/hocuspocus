import * as api from '../../api/client'
import { isGenerationJobSettled } from '../../lib/generationJobState'
import type { GenerationJob } from '../../types'
import { prependJob, updateJob, withJobs } from '../../stores/jobReducers'
import type { SliceGet, SliceSet } from '../../stores/storeApi'
import type { AppState } from '../../stores/useStore'
import { editJobGenerationDetails } from './editJobDetails'
import { _jobTimingPatch } from './store/toolsSlice'

export async function submitOutpaintEdit(
  get: SliceGet<AppState>,
  set: SliceSet<AppState>,
  state: AppState,
): Promise<void> {
      if (!state.editVideoPath) return
      const prompt = (state.params.prompt as string || '').trim()

      // Resolve source pixel dimensions from the loaded video metadata.
      // We need them to convert the canvas-relative video box into absolute
      // pad_top/bottom/left/right pixel values that the server expects.
      const srcRes = state.editVideoResolution || ''
      const [srcWStr, srcHStr] = srcRes.split('x')
      const srcW = parseInt(srcWStr) || 0
      const srcH = parseInt(srcHStr) || 0
      if (srcW <= 0 || srcH <= 0) {
        console.error('Outpaint: source dimensions unknown')
        return
      }

      // Resolve canvas dimensions in source-pixel-space from the chosen aspect.
      // Canvas is grown so the source fits inside without cropping; pure
      // letterbox math.
      const aspect = state.outpaintAspect
      let canvasW = srcW, canvasH = srcH
      if (aspect !== 'source') {
        const [aw, ah] = aspect.split(':').map(Number)
        const target = aw / ah
        const srcRatio = srcW / srcH
        if (srcRatio > target) {
          canvasW = srcW
          canvasH = Math.round(srcW / target)
        } else {
          canvasH = srcH
          canvasW = Math.round(srcH * target)
        }
      }

      // The video box is canvas-relative (0–1). Convert to pixel pads.
      const box = state.outpaintVideoBox
      const videoX = Math.round(box.x * canvasW)
      const videoY = Math.round(box.y * canvasH)
      const videoW = Math.round(box.w * canvasW)
      const videoH = Math.round(box.h * canvasH)
      const padTop = Math.max(0, videoY)
      const padLeft = Math.max(0, videoX)
      const padBottom = Math.max(0, canvasH - videoY - videoH)
      const padRight = Math.max(0, canvasW - videoX - videoW)
      const totalPad = padTop + padBottom + padLeft + padRight
      if (totalPad === 0) return

      // Mirror the computed pads to outpaintPadding so metadata sidecars
      // and any older read paths still see the values.
      set({ outpaintPadding: { top: padTop, bottom: padBottom, left: padLeft, right: padRight } })

      // Optional film-strip trim: only send if user picked a non-trivial range.
      const trimStart = state.outpaintTrimStart || 0
      const trimEnd = state.outpaintTrimEnd || 0
      const sendTrim = trimEnd > trimStart && trimEnd > 0.05

    const newJob: GenerationJob = {
      id: '', status: 'queued', progress: 0, step: 0, totalSteps: 0,
      phase: '', message: 'Submitting outpaint...', outputFiles: [], error: null, oomInfo: null,
      generationDetails: editJobGenerationDetails(state), createdAt: Date.now(),
      }
      set(s => {
        return prependJob(s.jobs, newJob)
      })

      // Sliding window size: the Advanced Settings slider stores seconds.
      // Convert to frames using the loaded model's fps so the same value
      // round-trips between video and outpaint modes. Falls back to 25
      // (LTX-2 22B's native rate) if modelOptions hasn't loaded yet.
      const fps = (state.modelOptions?.fps as number) || 25
      const windowFrames = Math.max(1, Math.round(state.slidingWindowSeconds * fps))
      const overlapFrames = state.slidingWindowOverlap || 9

      try {
        const result = await api.submitOutpaint({
          video_path: state.editVideoPath,
          prompt: prompt || 'extend the scene naturally',
          model_type: state.params.model_type as string,
          pad_top: padTop,
          pad_bottom: padBottom,
          pad_left: padLeft,
          pad_right: padRight,
          outpaint_aspect: state.outpaintAspect,
          resolution_preset: state.outpaintResolutionPreset,
          source_preservation: 1.0,
          outpaint_lora_strength: 1.0,
          mask_preserving_outpaint: state.outpaintMaskPreserving,
          preserve_source_audio: state.outpaintPreserveSourceAudio,
          lock_source_pixels: false,
          trim_window_smear: state.outpaintTrimSmear,
          sliding_window_size: windowFrames,
          sliding_window_overlap: overlapFrames,
          ...(sendTrim ? { start_time: trimStart, end_time: trimEnd } : {}),
          num_inference_steps: (state.params.num_inference_steps as number) ?? undefined,
          guidance_scale: (state.params.guidance_scale as number) ?? undefined,
          negative_prompt: (state.params.negative_prompt as string) || undefined,
          seed: (state.params.seed as number) ?? -1,
          activated_loras: (state.params.activated_loras as string[]) || [],
          loras_multipliers: (state.params.loras_multipliers as string) || '',
          workspace: state.activeWorkspace,
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
        const msg = e instanceof Error ? e.message : 'Outpaint failed'
        // Submit itself failed (pre-queue). Convert the placeholder to a
        // failed state in place so the user sees what went wrong instead of
        // the tile silently disappearing.
        set(s => updateJob(s.jobs, j => j === newJob, j => ({
          ...j, id: j.id || `submit-fail-${Date.now()}`, status: 'failed', message: msg, error: msg,
        })))
        console.error('Outpaint failed:', msg)
      }
}
