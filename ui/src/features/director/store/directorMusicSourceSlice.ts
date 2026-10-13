import * as api from '../../../api/client'
import { beginAppActivity, type ActivitySlice } from '../../activity/store'
import type { AudioAnalysisResult, DirectorSkill, GenerationMode, SpeakerMapping } from '../../../types'
import type { DirectorPipelineSlice } from './directorPipelineSlice'
import type { DirectorSlice } from '../../../stores/directorSlice'
import type { GallerySlice } from '../../../stores/gallerySlice'
import type { ModelOptionsSlice } from '../../../stores/modelOptionsSlice'
import type { ServicesSlice } from '../../../stores/servicesSlice'
import type { SliceCreator } from '../../../stores/storeApi'

/** Trailer excerpt and transcription hints, shared by every way audio can
 *  reach Director. */
type DirectorAudioOptions = {
  lyricsHint?: string
  trimStart?: number
  trimEnd?: number
  totalDuration?: number
}

/** How one track reaches Director. Only the delivery differs — posting the
 *  bytes, or naming a file the server already has — and it answers with the
 *  server-side path the rest of the flow works from. Adopted songs stay in
 *  their workspace folder, so that workspace has to travel with the path. */
type DirectorAudioSource = {
  name: string
  phase: 'uploading_audio' | 'adopting_audio'
  activityMessage: string
  loadingMessage: string
  workspace?: string
  deliver: () => Promise<{ path: string }>
}

export type DirectorMusicSourceSlice = {
  directorUploadAndAnalyze: (file: File, opts?: DirectorAudioOptions) => Promise<void>
  /** Bring in a track the server already holds — a workspace output, an
   *  earlier upload — by name. Story Lab's generated songs come this way:
   *  pulling the file into the browser only to post the same bytes back is a
   *  round trip over the network for a file already on that disk, and it is
   *  what broke when the UI is driven from another machine. */
  directorAdoptAndAnalyze: (reference: { audio_path: string; workspace?: string }, name: string, opts?: DirectorAudioOptions) => Promise<void>
  /** The hand-off both of the above share: deliver the audio, optionally cut
   *  the trailer excerpt, then analyze and plan. */
  directorLoadAudioSource: (source: DirectorAudioSource, opts?: DirectorAudioOptions) => Promise<void>
  // Music Video: generate-the-track source + song setup
  directorWriteSong: () => Promise<void>
  directorGenerateTrack: () => Promise<void>
  directorAnalyzeAndPlan: (audioPath: string, opts?: { transcribe?: boolean; lyricsHint?: string; classifyLyricsHint?: string; activityId?: string; totalDuration?: number; workspace?: string }) => Promise<void>
  directorSetEnergyBias: (bias: number) => Promise<void>
  directorSetPacingProfile: (profile: 'cinematic' | 'balanced' | 'rhythmic') => Promise<void>
}

/** Audio source and song setup read and write the director fields listed here. directorConfirmStructure stays on the store until the music-video actions move. */
export type DirectorMusicSourceSliceHost = DirectorMusicSourceSlice & ActivitySlice & Pick<DirectorSlice,
  | 'directorLoading'
  | 'directorLoadingMessage'
  | 'directorError'
  | 'directorAudioName'
  | 'directorStep'
  | 'directorAudioPath'
  | 'directorAnalysis'
  | 'directorSpeakers'
  | 'directorSpeakerMappings'
  | 'directorPlannedClips'
  | 'directorReferenceImagePath'
  | 'directorReferenceImage'
  | 'directorSongStyle'
  | 'directorSongLyrics'
  | 'directorSongDescription'
  | 'directorSongDuration'
  | 'directorSongInstrumental'
  | 'directorTrackGenerating'
  | 'directorEnergyBias'
  | 'directorPacingProfile'
  | 'directorSceneDescription'
  | 'directorAutoMode'
> & Pick<DirectorPipelineSlice, 'startDirectorPipeline'> & Pick<GallerySlice, 'activeWorkspace'> & Pick<ModelOptionsSlice, 'modelOptions'> & Pick<ServicesSlice, 'productionProfile'> & {
  directorSkill: DirectorSkill | null
  directorConfirmStructure: () => void
  reconnectJobs: () => Promise<void>
  selectedModelPerMode: Partial<Record<GenerationMode, string>>
}

export const createDirectorMusicSourceSlice: SliceCreator<DirectorMusicSourceSlice, DirectorMusicSourceSliceHost> = (set, get) => ({
  directorUploadAndAnalyze: (file, opts) => get().directorLoadAudioSource({
    name: file.name,
    phase: 'uploading_audio',
    activityMessage: `Uploading “${file.name}”…`,
    loadingMessage: 'Uploading audio...',
    deliver: () => api.uploadAudio(file),
  }, opts),

  directorAdoptAndAnalyze: (reference, name, opts) => get().directorLoadAudioSource({
    name,
    phase: 'adopting_audio',
    activityMessage: `Loading “${name}”…`,
    loadingMessage: 'Loading audio...',
    workspace: reference.workspace,
    deliver: () => api.adoptAudio(reference),
  }, opts),

  directorLoadAudioSource: async (source, opts) => {
    const activityId = `director-audio:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    get().upsertActivity({
      id: activityId,
      kind: 'audio_analysis',
      title: 'Prepare music video',
      status: 'running',
      phase: source.phase,
      message: source.activityMessage,
      current: 1,
      total: 10,
    })
    set({
      directorLoading: true,
      directorLoadingMessage: source.loadingMessage,
      directorError: null,
      directorAudioName: source.name,
      directorStep: 'analyze',
    })
    let analysisStarted = false
    try {
      const delivered = await source.deliver()
      const shouldTrim = Number.isFinite(opts?.trimStart)
        && Number.isFinite(opts?.trimEnd)
        && Number(opts?.trimEnd) > Number(opts?.trimStart) + 0.99
      if (shouldTrim) {
        get().upsertActivity({
          id: activityId,
          kind: 'audio_analysis',
          title: 'Prepare musical trailer',
          status: 'running',
          phase: 'trimming_audio',
          message: `Cutting ${Number(opts?.trimStart).toFixed(1)}s–${Number(opts?.trimEnd).toFixed(1)}s…`,
          current: 1,
          total: 10,
        })
      }
      const workspace = source.workspace ?? get().activeWorkspace
      const prepared = shouldTrim
        ? await api.trimAudio({
            audio_path: delivered.path,
            start: Number(opts?.trimStart),
            end: Number(opts?.trimEnd),
            workspace,
          })
        : delivered
      analysisStarted = true
      await get().directorAnalyzeAndPlan(prepared.path, {
        transcribe: true,
        lyricsHint: opts?.lyricsHint,
        classifyLyricsHint: shouldTrim ? '' : opts?.lyricsHint,
        activityId,
        totalDuration: opts?.totalDuration,
        workspace,
      })
    } catch (e: unknown) {
      if (analysisStarted) return
      const msg = e instanceof Error ? e.message : 'The audio could not be loaded'
      console.error('Director audio hand-off failed:', e)
      set({ directorLoading: false, directorLoadingMessage: null, directorError: msg, directorStep: 'upload' })
      if (get().activities[activityId]?.status !== 'failed') {
        get().upsertActivity({
          id: activityId,
          kind: 'audio_analysis',
          title: 'Prepare music video',
          status: 'failed',
          phase: source.phase,
          message: msg,
          error: msg,
        })
      }
    }
  },

  // Shared analyze → section-classify → plan-structure chain. Works for an
  // UPLOADED track or a GENERATED one — both converge here with an audio path
  // on disk and land on the 'structure' step, so everything downstream is
  // identical regardless of where the audio came from.
  directorAnalyzeAndPlan: async (audioPath, opts) => {
    const transcribe = opts?.transcribe !== false
    const activityId = opts?.activityId
      || `director-audio:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
    let frontendActivityOpen = true
    let backendAccepted = false
    let postActivity: ReturnType<typeof beginAppActivity> | null = null
    const analysisSteps: Record<string, number> = {
      loading_audio: 2,
      detecting_beats: 3,
      identifying_sections: 4,
      loading_vocal_model: 4,
      extracting_vocals: 5,
      loading_transcription_model: 5,
      transcribing: 6,
      loading_diarization_model: 6,
      identifying_speakers: 7,
      finalizing: 8,
    }
    const reportActivity = (phase: string, message: string, current?: number) => {
      if (!frontendActivityOpen) return
      get().upsertActivity({
        id: activityId,
        kind: 'audio_analysis',
        title: 'Prepare music video',
        status: 'running',
        phase,
        message,
        current: current ?? analysisSteps[phase] ?? 2,
        total: 10,
      })
    }
    reportActivity('analyzing_audio', 'Analyzing audio…', 2)
    set({
      directorAudioPath: audioPath,
      directorLoading: true,
      directorLoadingMessage: 'Analyzing audio...',
      directorError: null,
      directorStep: 'analyze',
    })
    try {
      const accepted = await api.startAudioAnalysisJob({
        audio_path: audioPath,
        transcribe,
        extract_vocals: transcribe,
        lyrics_hint: opts?.lyricsHint || undefined,
        workspace: opts?.workspace ?? get().activeWorkspace,
      })
      backendAccepted = true
      get().upsertActivity({
        id: activityId,
        kind: 'audio_analysis',
        title: 'Prepare music video',
        status: 'completed',
        phase: 'handed_off',
        message: `Continuing as recoverable audio job ${accepted.job_id}`,
        current: 1,
        total: 1,
      })
      frontendActivityOpen = false
      window.setTimeout(() => get().removeActivity(activityId), 4000)
      void get().reconnectJobs()

      let analysis: AudioAnalysisResult | null = null
      for (;;) {
        const status = await api.fetchAudioAnalysisJob(accepted.job_id)
        set({ directorLoadingMessage: status.message })
        if (status.status === 'completed') {
          analysis = status.result
          break
        }
        if (status.status === 'failed') throw new Error(status.error || status.message)
        if (status.status === 'cancelled') throw new Error('Audio analysis cancelled')
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
      if (!analysis) throw new Error('Audio analysis completed without a result')

      postActivity = beginAppActivity(get, {
        kind: 'director_audio_structure',
        title: 'Prepare music video',
        phase: 'classifying_sections',
        message: 'Preparing the editable song structure…',
        total: 2,
      })

      // Try LLM-based section classification (falls back to heuristic)
      if (analysis.lyrics && analysis.lyrics.length > 0) {
        try {
          set({ directorLoadingMessage: 'Identifying sections (LLM)...' })
          postActivity.report(
            'classifying_sections',
            'Classifying verses, choruses and bridges…',
            0,
            2,
          )
          const classified = await api.classifySections({
            analysis,
            lyrics_hint: (opts?.classifyLyricsHint ?? opts?.lyricsHint) || undefined,
          })
          analysis = {
            ...analysis,
            sections: classified.sections,
            song_structure: classified.song_structure || null,
          }
        } catch {
          // LLM not available — keep heuristic labels
        }
      }

      set({ directorAnalysis: analysis })

      // Extract unique speakers from diarized lyrics
      const speakers: string[] = []
      if (analysis.lyrics) {
        const seen = new Set<string>()
        for (const seg of analysis.lyrics) {
          if (seg.speaker && !seen.has(seg.speaker)) {
            seen.add(seg.speaker)
            speakers.push(seg.speaker)
          }
        }
      }
      const speakerMappings: SpeakerMapping[] = speakers.map(s => ({
        speakerId: s,
        name: '',
        role: '' as const,
      }))
      set({ directorSpeakers: speakers, directorSpeakerMappings: speakerMappings })

      // Plan beat-aligned clip structure
      set({ directorLoadingMessage: 'Planning clip structure...' })
      postActivity.report('planning_clips', 'Planning beat-aligned clips…', 1, 2)
      const structure = await api.planClipStructure({
        analysis,
        energy_bias: get().directorEnergyBias,
        pacing_profile: get().directorSkill === 'music_video' ? get().directorPacingProfile : undefined,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
        total_duration: Number.isFinite(opts?.totalDuration) && Number(opts?.totalDuration) > 0
          ? Number(opts?.totalDuration)
          : undefined,
        // Authoritative: the Director's video model (modelOptions above may
        // belong to a music model — e.g. ACE-Step after generating a track —
        // whose fps fallback of 16 used to shrink clips by 16/25).
        video_model: get().selectedModelPerMode.video || undefined,
      })
      set({
        directorPlannedClips: structure.clips,
        directorStep: 'structure',
        directorLoading: false,
        directorLoadingMessage: null,
      })
      postActivity.finish(`${structure.clips.length} clips planned — review the pacing`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Analysis failed'
      console.error('Director analysis failed:', e)
      postActivity?.fail(e, 'preparing_structure')
      if (msg === 'Audio analysis cancelled') {
        set({ directorLoading: false, directorLoadingMessage: null, directorError: null, directorStep: 'upload' })
        return
      }
      set({ directorLoading: false, directorLoadingMessage: null, directorError: msg, directorStep: 'upload' })
      if (!backendAccepted) {
        frontendActivityOpen = false
        get().upsertActivity({
          id: activityId,
          kind: 'audio_analysis',
          title: 'Prepare music video',
          status: 'failed',
          phase: 'analyzing_audio',
          message: msg,
          error: msg,
        })
      }
      throw e
    }
  },

  // Music Video: write the song (Style + Lyrics) from the description, with
  // the optional reference image informing the style via the vision LLM.
  // Throws on failure so the UI can surface it inline.
  directorWriteSong: async () => {
    const s = get()
    const description = s.directorSongDescription.trim()
    if (!description) return
    const activity = beginAppActivity(get, {
      kind: 'director_songwriting',
      title: 'Music Video Director',
      phase: 'writing_song',
      message: 'Writing the music prompt and structured lyrics…',
      total: 2,
      generationDetails: {
        text_provider: s.productionProfile.text.provider,
        text_model: s.productionProfile.text.model,
      },
    })
    let refPath = s.directorReferenceImagePath
    try {
      if (!refPath && s.directorReferenceImage) {
        activity.report('uploading_artwork', 'Uploading the visual reference…', 1, 2)
        try {
          refPath = (await api.uploadImage(s.directorReferenceImage)).path
          set({ directorReferenceImagePath: refPath })
        } catch { /* image upload is best-effort */ }
      }
      activity.report('writing_song', 'Writing the music prompt and structured lyrics…', 1, 2)
      set({ directorError: null })
      const r = await api.writeSong({
        description,
        instrumental: s.directorSongInstrumental,
        reference_image_path: refPath || undefined,
      })
      set({
        directorSongStyle: r.style || '',
        directorSongLyrics: s.directorSongInstrumental ? '[Instrumental]' : (r.lyrics || ''),
      })
      activity.finish('Song prompt and lyrics ready')
    } catch (error) {
      activity.fail(error)
      throw error
    }
  },

  // Music Video: generate the track (writing the song first if the user only
  // gave a description), then hand off to the SAME analyze → plan-structure
  // chain the upload flow uses. In Auto mode, continue straight into the
  // pipeline so it's fully hands-off.
  directorGenerateTrack: async () => {
    const s = get()
    const instrumental = s.directorSongInstrumental
    const description = s.directorSongDescription.trim()
    const style = s.directorSongStyle.trim()
    const lyrics = s.directorSongLyrics.trim()
    if (!description && !style && !lyrics) {
      set({ directorError: 'Describe your song (or fill in Style / Lyrics) first.' })
      return
    }
    const activity = beginAppActivity(get, {
      kind: 'director_music',
      title: 'Music Video Director',
      phase: 'generating_music',
      message: 'Preparing music generation…',
      total: 2,
      generationDetails: {
        model_type: `${s.productionProfile.music.provider}:${s.productionProfile.music.model}`,
        model_name: s.productionProfile.music.model,
        duration_seconds: s.directorSongDuration,
      },
    })
    // Upload the reference image so it can inform BOTH the music and visuals.
    let refPath = s.directorReferenceImagePath
    if (!refPath && s.directorReferenceImage) {
      try {
        refPath = (await api.uploadImage(s.directorReferenceImage)).path
        set({ directorReferenceImagePath: refPath })
      } catch { /* image upload is best-effort */ }
    }
    set({
      directorTrackGenerating: true,
      directorError: null,
      directorLoading: true,
      directorLoadingMessage: 'Generating music track…',
      directorStep: 'analyze',
    })
    try {
      // generateMusic is a BLOCKING POST — the browser only learns the job id
      // when it finishes — but the backend registers the job immediately. Run
      // the same discovery a fresh browser uses at page load (reconnectJobs:
      // deduped, self-polling) so the gallery shows a live placeholder card
      // during the render instead of nothing until LLM planning.
      const trackPromise = api.generateMusic({
        description: description || undefined,
        style: style || undefined,
        lyrics: instrumental ? '[Instrumental]' : (lyrics || undefined),
        instrumental,
        duration_seconds: s.directorSongDuration,
        reference_image_path: refPath || undefined,
        workspace: get().activeWorkspace || undefined,
        initiator: 'Director · Music video',
      })
      setTimeout(() => { void get().reconnectJobs() }, 1200)
      setTimeout(() => { void get().reconnectJobs() }, 5000)
      activity.report('generating_music', 'Generating the music track…', 1, 2)
      const r = await trackPromise
      // Persist the (possibly LLM-written) song back into the editable fields.
      set({
        directorSongStyle: r.style || style,
        directorSongLyrics: instrumental ? '[Instrumental]' : (r.lyrics || lyrics),
        directorTrackGenerating: false,
      })
      // Pre-fill the scene description from the song brief so the visual
      // planner has context. The 'style' step shows it (editable); Auto mode
      // uses it directly.
      if (!get().directorSceneDescription.trim() && description) {
        set({ directorSceneDescription: description })
      }
      activity.finish('Music track ready; starting audio analysis')
      // Same analyze → plan-structure chain as the upload flow. Instrumental
      // tracks skip transcription (no lyrics to find). For vocal tracks we
      // KNOW the written lyrics — seed Whisper with them so the timed
      // transcription matches what ACE-Step actually sang.
      await get().directorAnalyzeAndPlan(r.audio_path, {
        transcribe: !instrumental,
        lyricsHint: instrumental ? undefined : (r.lyrics || lyrics || undefined),
        totalDuration: s.directorSongDuration,
      })
      // Manual mode now pauses on the visible structure review. Auto mode
      // accepts the selected pacing profile and continues hands-free.
      if (get().directorStep === 'structure' && get().directorAutoMode) {
        get().directorConfirmStructure()
        await get().startDirectorPipeline()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Music generation failed'
      console.error('Director music generation failed:', e)
      set({
        directorTrackGenerating: false,
        directorLoading: false,
        directorLoadingMessage: null,
        directorError: msg,
        directorStep: 'upload',
      })
      activity.fail(e, 'generating_music')
    }
  },

  directorSetEnergyBias: async (bias) => {
    const { directorAnalysis } = get()
    if (!directorAnalysis) return
    const activity = beginAppActivity(get, {
      kind: 'clip_replanning', title: 'Director', phase: 'planning_clips',
      message: 'Recalculating clip structure…', total: 1,
    })
    set({ directorLoading: true, directorEnergyBias: bias })
    try {
      const structure = await api.planClipStructure({
        analysis: directorAnalysis,
        energy_bias: bias,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
        video_model: get().selectedModelPerMode.video || undefined,
      })
      set({ directorPlannedClips: structure.clips, directorLoading: false })
      activity.finish(`${structure.clips.length} clips replanned`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to update structure'
      set({ directorLoading: false, directorError: msg })
      activity.fail(e, 'planning_clips')
    }
  },

  directorSetPacingProfile: async (profile) => {
    const { directorAnalysis } = get()
    set({ directorPacingProfile: profile })
    if (!directorAnalysis) return
    const activity = beginAppActivity(get, {
      kind: 'clip_replanning', title: 'Music Video Director', phase: 'planning_clips',
      message: `Applying ${profile} editing rhythm…`, total: 1,
    })
    set({ directorLoading: true, directorError: null })
    try {
      const structure = await api.planClipStructure({
        analysis: directorAnalysis,
        pacing_profile: profile,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
        video_model: get().selectedModelPerMode.video || undefined,
      })
      set({ directorPlannedClips: structure.clips, directorLoading: false })
      activity.finish(`${structure.clips.length} clips planned with ${profile} pacing`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to update music-video pacing'
      set({ directorLoading: false, directorError: msg })
      activity.fail(e, 'planning_clips')
    }
  },
})
