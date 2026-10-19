import * as api from '../../../api/client'
import { beginAppActivity, type ActivitySlice } from '../../activity/store'
import type { AudioAnalysisResult, GenerationMode, PlannedClip, ShortFilmCharacter, ShortFilmPath, SpeakerMapping } from '../../../types'
import type { DirectorSlice } from '../../../stores/directorSlice'
import type { GallerySlice } from '../../../stores/gallerySlice'
import type { ModelOptionsSlice } from '../../../stores/modelOptionsSlice'
import type { SavedModeParams } from '../../../stores/modeSettingsPersistence'
import type { ServicesSlice } from '../../../stores/servicesSlice'
import type { SliceCreator } from '../../../stores/storeApi'

export type ShortFilmSlice = {
  // Short Film Director
  shortFilmSetCharacters: (characters: ShortFilmCharacter[]) => void
  shortFilmSetPath: (path: ShortFilmPath) => void
  shortFilmSetTargetDuration: (duration: number) => void
  shortFilmSetNarrative: (v: boolean) => void
  shortFilmSetVisualStyle: (style: string) => void
  shortFilmSetPreserveVisualStyle: (v: boolean) => void
  setDirectorCharacterVisualStyle: (style: string) => void
  setDirectorAllowClipText: (v: boolean) => void
  setDirectorSpokenLanguage: (language: string) => void
  shortFilmUploadAndAnalyze: (file: File) => Promise<void>
  shortFilmSetPacingBias: (bias: number) => Promise<void>
  shortFilmPlanPrompts: () => Promise<void>
  shortFilmPlanVideoPrompts: () => Promise<void>
  shortFilmPlanFromStory: () => Promise<void>
}

/** The actions call beginAppActivity, which is typed as a reader of ActivitySlice, and they read and write the director fields listed here. */
export type ShortFilmSliceHost = ShortFilmSlice & ActivitySlice & Pick<DirectorSlice,
  | 'directorAnalysis'
  | 'directorPlannedClips'
  | 'directorSceneDescription'
  | 'shortFilmCharacters'
  | 'shortFilmPath'
  | 'shortFilmTargetDuration'
  | 'shortFilmNarrative'
  | 'shortFilmVisualStyle'
  | 'shortFilmPreserveVisualStyle'
  | 'directorCharacterVisualStyle'
  | 'directorAllowClipText'
  | 'directorSpokenLanguage'
  | 'directorCharacterRefLabels'
  | 'directorLocationRefLabels'
  | 'directorCharacterRefPaths'
  | 'directorLocationRefPaths'
  | 'directorClipPlans'
  | 'directorReferenceImagePath'
  | 'directorEnergyBias'
  | 'directorSpeakerMappings'
  | 'directorSpeakers'
  | 'directorLoading'
  | 'directorLoadingMessage'
  | 'directorError'
  | 'directorAudioName'
  | 'directorAudioPath'
  | 'directorStep'
  | 'directorAutoMode'
  | 'directorReferenceImage'
> & Pick<ModelOptionsSlice, 'modelOptions'> & Pick<ServicesSlice, 'servicesConfig'> & Pick<GallerySlice, 'activeWorkspace'> & {
  selectedModelPerMode: Partial<Record<GenerationMode, string>>
  savedParamsPerMode: Partial<Record<GenerationMode, SavedModeParams>>
  llmStreamText: string
  llmStreamDone: boolean
  reconnectJobs: () => Promise<void>
  directorGenerateStartImages: () => Promise<void>
  directorGenerate: () => void
  _uploadDirectorRefs: () => Promise<{ refImagePath: string | null; charPaths: string[]; locPaths: string[] }>
}

export const createShortFilmSlice: SliceCreator<ShortFilmSlice, ShortFilmSliceHost> = (set, get) => ({
  // --- Short Film Director actions ---

  shortFilmSetCharacters: (characters) => set({ shortFilmCharacters: characters }),
  shortFilmSetPath: (path) => set({ shortFilmPath: path }),
  shortFilmSetTargetDuration: (duration) => set({ shortFilmTargetDuration: duration }),
  shortFilmSetNarrative: (v) => set({ shortFilmNarrative: v }),
  shortFilmSetVisualStyle: (style) => set({ shortFilmVisualStyle: style }),
  shortFilmSetPreserveVisualStyle: (v) => set({ shortFilmPreserveVisualStyle: v }),
  setDirectorCharacterVisualStyle: (style) => set({ directorCharacterVisualStyle: style }),
  setDirectorAllowClipText: (v) => set({ directorAllowClipText: v }),
  setDirectorSpokenLanguage: (language) => set({ directorSpokenLanguage: language }),

  shortFilmUploadAndAnalyze: async (file) => {
    const activity = beginAppActivity(get, {
      kind: 'short_film_audio',
      title: 'Short Film Director',
      phase: 'uploading_audio',
      message: `Uploading “${file.name}”…`,
      total: 10,
    })
    set({
      directorLoading: true,
      directorLoadingMessage: 'Uploading audio...',
      directorError: null,
      directorAudioName: file.name,
      directorStep: 'analyze',
    })
    try {
      const uploaded = await api.uploadAudio(file)
      set({ directorAudioPath: uploaded.path, directorLoadingMessage: 'Analyzing audio...' })
      const accepted = await api.startAudioAnalysisJob({
        audio_path: uploaded.path,
        transcribe: true,
        extract_vocals: true,
      })
      void get().reconnectJobs()
      let analysis: AudioAnalysisResult | null = null
      for (;;) {
        const status = await api.fetchAudioAnalysisJob(accepted.job_id)
        set({ directorLoadingMessage: status.message })
        activity.report(status.phase || 'analyzing_audio', status.message, status.step, 10)
        if (status.status === 'completed') {
          analysis = status.result
          break
        }
        if (status.status === 'failed') throw new Error(status.error || status.message)
        if (status.status === 'cancelled') throw new Error('Audio analysis cancelled')
        await new Promise(resolve => window.setTimeout(resolve, 1000))
      }
      if (!analysis) throw new Error('Audio analysis completed without a result')

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
        role: 'speaking' as const,
      }))
      set({ directorSpeakers: speakers, directorSpeakerMappings: speakerMappings })

      // Plan dialogue-paced clip structure (not beat-aligned)
      set({ directorLoadingMessage: 'Planning scenes...' })
      activity.report('planning_clips', 'Planning dialogue-paced scenes…', 9, 10)
      const structure = await api.planDialogueScenes({
        analysis,
        pacing_bias: get().directorEnergyBias,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
      })
      set({
        directorPlannedClips: structure.clips,
        directorStep: 'structure',
        directorLoading: false,
        directorLoadingMessage: null,
      })
      activity.finish(`${structure.clips.length} dialogue scenes ready for review`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Analysis failed'
      console.error('Short film analysis failed:', e)
      set({ directorLoading: false, directorLoadingMessage: null, directorError: msg, directorStep: 'upload' })
      activity.fail(e, 'analyzing_audio')
    }
  },

  shortFilmSetPacingBias: async (bias) => {
    const { directorAnalysis } = get()
    if (!directorAnalysis) return
    const activity = beginAppActivity(get, {
      kind: 'scene_replanning', title: 'Short Film Director', phase: 'planning_clips',
      message: 'Recalculating dialogue scene pacing…', total: 1,
    })
    set({ directorLoading: true, directorEnergyBias: bias })
    try {
      const structure = await api.planDialogueScenes({
        analysis: directorAnalysis,
        pacing_bias: bias,
        fps: get().modelOptions?.fps ?? 16,
        frames_steps: get().modelOptions?.frames_steps ?? 4,
        frames_minimum: get().modelOptions?.frames_minimum ?? 5,
      })
      set({ directorPlannedClips: structure.clips, directorLoading: false })
      activity.finish(`${structure.clips.length} scenes replanned`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to update structure'
      set({ directorLoading: false, directorError: msg })
      activity.fail(e, 'planning_clips')
    }
  },

  shortFilmPlanPrompts: async () => {
    const { directorPlannedClips, directorSceneDescription, directorAnalysis,
            shortFilmCharacters } = get()
    if (!directorPlannedClips.length || !directorSceneDescription.trim()) return
    const activity = beginAppActivity(get, {
      kind: 'short_film_planning',
      title: 'Short Film Director',
      phase: 'planning',
      message: `Planning ${directorPlannedClips.length} scenes…`,
      total: directorPlannedClips.length,
    })
    set({ directorLoading: true, directorError: null, directorStep: 'plan' })
    try {
      // Upload all reference images
      const { refImagePath, charPaths, locPaths } = await get()._uploadDirectorRefs()
      const { directorCharacterRefLabels: charLabels, directorLocationRefLabels: locLabels } = get()
      const extraRefs = {
        ...(charPaths.length > 0 ? { character_ref_paths: charPaths, character_ref_labels: charLabels } : {}),
        ...(locPaths.length > 0 ? { location_ref_paths: locPaths, location_ref_labels: locLabels } : {}),
      }

      // Build speaker mappings
      const speakerMappings: Record<string, { name: string; role: string }> = {}
      for (const m of get().directorSpeakerMappings) {
        if (m.name.trim()) {
          speakerMappings[m.speakerId] = { name: m.name, role: m.role }
        }
      }

      // Generate prompts
      // ?? not || — an explicit user-toggled `false` must be respected
      // (legacy v1 path); only fall back to true when servicesConfig
      // hasn't loaded yet or the field is undefined.
      const useV2 = get().servicesConfig?.use_director_v2 ?? true
      let plans: Array<{ video_prompt: string; image_prompt: string }>

      if (useV2) {
        const result = await api.directorV2Plan({
          workspace: get().activeWorkspace,
          skill_type: 'short_film',
          clips: directorPlannedClips,
          scene_description: directorSceneDescription,
          lyrics: directorAnalysis?.lyrics ?? undefined,
          reference_image_path: refImagePath ?? undefined,
          ...extraRefs,
          speaker_mappings: Object.keys(speakerMappings).length > 0 ? speakerMappings : undefined,
          characters: shortFilmCharacters.length > 0 ? shortFilmCharacters : undefined,
          image_model: get().selectedModelPerMode.image || undefined,
          video_model: get().selectedModelPerMode.video || undefined,
          h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
          h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
          prompt_type: 'both',
        })
        plans = result.clip_plans.map(p => ({
          video_prompt: p.video_prompt || '',
          image_prompt: p.image_prompt || '',
        }))
      } else {
        const result = await api.planShortFilmPrompts({
          clips: directorPlannedClips,
          scene_description: directorSceneDescription,
          lyrics: directorAnalysis?.lyrics ?? undefined,
          reference_image_path: refImagePath,
          ...extraRefs,
          speaker_mappings: Object.keys(speakerMappings).length > 0 ? speakerMappings : undefined,
          characters: shortFilmCharacters.length > 0 ? shortFilmCharacters : undefined,
          video_model: get().selectedModelPerMode.video || undefined,
          h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
          h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
          prompt_type: 'both',
        })
        plans = result.clip_plans.map(p => ({
          video_prompt: p.video_prompt || '',
          image_prompt: p.image_prompt || '',
        }))
      }
      set({
        directorClipPlans: plans,
        directorStep: 'review',
        directorLoading: false,
      })
      activity.finish(`${plans.length} short-film scenes ready for review`)

      // Auto-mode: skip review
      if (get().directorAutoMode) {
        if (get().directorReferenceImage) {
          get().directorGenerateStartImages()
        } else {
          set({ directorStep: 'review_video' })
          get().directorGenerate()
        }
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Planning failed'
      console.error('Short film planning failed:', e)
      set({ directorLoading: false, directorError: msg, directorStep: 'style' })
      activity.fail(e, 'planning')
    }
  },

  shortFilmPlanVideoPrompts: async () => {
    const { directorPlannedClips, directorSceneDescription, directorAnalysis,
            directorClipPlans, directorReferenceImagePath, shortFilmCharacters } = get()
    if (!directorPlannedClips.length || !directorClipPlans.length) return
    const activity = beginAppActivity(get, {
      kind: 'short_film_video_prompts',
      title: 'Short Film Director',
      phase: 'planning',
      message: `Planning motion for ${directorPlannedClips.length} scenes…`,
      total: directorPlannedClips.length,
    })
    set({ directorLoading: true, directorError: null, directorStep: 'plan_video' })
    try {
      const speakerMappings: Record<string, { name: string; role: string }> = {}
      for (const m of get().directorSpeakerMappings) {
        if (m.name.trim()) {
          speakerMappings[m.speakerId] = { name: m.name, role: m.role }
        }
      }

      const existingImagePrompts = directorClipPlans.map(p => p.image_prompt || '')
      const {
        directorCharacterRefPaths: crp2,
        directorCharacterRefLabels: crl2,
        directorLocationRefPaths: lrp2,
        directorLocationRefLabels: lrl2,
      } = get()
      const result = await api.planShortFilmPrompts({
        clips: directorPlannedClips,
        scene_description: directorSceneDescription,
        lyrics: directorAnalysis?.lyrics ?? undefined,
        reference_image_path: directorReferenceImagePath,
        ...(crp2.length > 0 ? { character_ref_paths: crp2, character_ref_labels: crl2 } : {}),
        ...(lrp2.length > 0 ? { location_ref_paths: lrp2, location_ref_labels: lrl2 } : {}),
        speaker_mappings: Object.keys(speakerMappings).length > 0 ? speakerMappings : undefined,
        characters: shortFilmCharacters.length > 0 ? shortFilmCharacters : undefined,
        prompt_type: 'video',
        existing_image_prompts: existingImagePrompts,
        video_model: get().selectedModelPerMode.video || undefined,
        h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
        h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
      })
      const updatedPlans = directorClipPlans.map((plan, i) => ({
        ...plan,
        video_prompt: result.clip_plans[i]?.video_prompt || '',
      }))
      set({
        directorClipPlans: updatedPlans,
        directorStep: 'review_video',
        directorLoading: false,
      })
      activity.finish(`${updatedPlans.length} scene motion prompts ready`)

      if (get().directorAutoMode) {
        get().directorGenerate()
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Video prompt planning failed'
      console.error('Short film video planning failed:', e)
      set({ directorLoading: false, directorError: msg, directorStep: 'generate_images' })
      activity.fail(e, 'planning')
    }
  },

  shortFilmPlanFromStory: async () => {
    const { directorSceneDescription,
            shortFilmCharacters, shortFilmTargetDuration, shortFilmNarrative,
            shortFilmVisualStyle, shortFilmPreserveVisualStyle,
            directorCharacterVisualStyle, directorAllowClipText } = get()
    if (!directorSceneDescription.trim()) return
    const activity = beginAppActivity(get, {
      kind: 'story_film_planning',
      title: 'Short Film Director',
      phase: 'planning',
      message: 'Planning the Story adaptation with the LLM…',
      total: 3,
    })
    set({ directorLoading: true, directorError: null, directorStep: 'plan', llmStreamText: '', llmStreamDone: false })
    try {
      // Upload all reference images
      const { refImagePath, charPaths, locPaths } = await get()._uploadDirectorRefs()
      const { directorCharacterRefLabels: charLabels, directorLocationRefLabels: locLabels } = get()
      const extraRefs = {
        ...(charPaths.length > 0 ? { character_ref_paths: charPaths, character_ref_labels: charLabels } : {}),
        ...(locPaths.length > 0 ? { location_ref_paths: locPaths, location_ref_labels: locLabels } : {}),
      }

      // ?? not || — an explicit user-toggled `false` must be respected
      // (legacy v1 path); only fall back to true when servicesConfig
      // hasn't loaded yet or the field is undefined.
      const useV2 = get().servicesConfig?.use_director_v2 ?? true
      let plans: Array<{ video_prompt: string; image_prompt: string }>
      let storyClips: PlannedClip[] | undefined

      if (useV2) {
        const result = await api.directorV2Plan({
          workspace: get().activeWorkspace,
          skill_type: 'short_film',
          scene_description: directorSceneDescription,
          story_description: directorSceneDescription,
          characters: shortFilmCharacters.length > 0 ? shortFilmCharacters : undefined,
          reference_image_path: refImagePath ?? undefined,
          ...extraRefs,
          target_duration: shortFilmTargetDuration,
          narrative_mode: shortFilmNarrative,
          visual_style: shortFilmVisualStyle || undefined,
          preserve_visual_style: shortFilmPreserveVisualStyle,
          character_visual_style: directorCharacterVisualStyle || undefined,
          allow_clip_text: directorAllowClipText,
          fps: get().modelOptions?.fps ?? 24,
          frames_steps: get().modelOptions?.frames_steps ?? 4,
          frames_minimum: get().modelOptions?.frames_minimum ?? 5,
          image_model: get().selectedModelPerMode.image || undefined,
          video_model: get().selectedModelPerMode.video || undefined,
          h3_reference_mode: get().savedParamsPerMode.video?.h3_reference_mode as 'first_frame' | 'references' | undefined,
          h3_audio_prompt: get().savedParamsPerMode.video?.h3_audio_prompt as string | undefined,
          prompt_type: 'both',
        })
        plans = result.clip_plans.map(p => ({
          video_prompt: p.video_prompt || '',
          image_prompt: p.image_prompt || '',
        }))
        // Extract clips from production plan shots
        const pp = result.production_plan
        if (pp.shots) {
          let cumulative = 0
          storyClips = pp.shots.map((shot) => {
            const duration = shot.duration_sec || 15
            const metadataFrames = shot.metadata?.duration_frames
            const clip = {
              start: cumulative,
              end: cumulative + duration,
              duration_frames: typeof metadataFrames === 'number'
                ? metadataFrames
                : Math.round(duration * (get().modelOptions?.fps ?? 24)),
              section_label: shot.narrative_role || shot.scene_type || 'scene',
              energy: 0.5,
              suggested_prompt_hint: shot.scene_goal || '',
              beat_count: 0,
            }
            cumulative += duration
            return clip
          })
        }
      } else {
        const result = await api.planShortFilmScript({
          story_description: directorSceneDescription,
          characters: shortFilmCharacters.length > 0 ? shortFilmCharacters : undefined,
          reference_image_path: refImagePath ?? undefined,
          ...extraRefs,
          target_duration: shortFilmTargetDuration,
          narrative_mode: shortFilmNarrative,
          fps: get().modelOptions?.fps ?? 24,
          frames_steps: get().modelOptions?.frames_steps ?? 4,
          frames_minimum: get().modelOptions?.frames_minimum ?? 5,
          visual_style: shortFilmVisualStyle || undefined,
          preserve_visual_style: shortFilmPreserveVisualStyle,
          character_visual_style: directorCharacterVisualStyle || undefined,
          allow_clip_text: directorAllowClipText,
        })
        storyClips = result.clips
        plans = result.clip_plans.map(p => ({
          video_prompt: p.video_prompt || '',
          image_prompt: p.image_prompt || '',
        }))
      }

      set({ llmStreamDone: true })

      set({
        directorPlannedClips: storyClips || get().directorPlannedClips,
        directorClipPlans: plans,
        directorStep: 'review',
        directorLoading: false,
      })
      activity.finish(`${plans.length} Story film scenes ready for review`)

      // Auto-mode: skip review steps
      if (get().directorAutoMode) {
        if (get().directorReferenceImage) {
          get().directorGenerateStartImages()
        } else {
          set({ directorStep: 'review_video' })
          get().directorGenerate()
        }
      }
    } catch (e: unknown) {
      set({ llmStreamDone: true })
      const msg = e instanceof Error ? e.message : 'Story planning failed'
      console.error('Short film story planning failed:', e)
      set({ directorLoading: false, directorError: msg, directorStep: 'style' })
      activity.fail(e, 'planning')
    }
  },
})
