export interface ModelFamily {
  id: string
  label: string
  order: number
}

export type DirectorPipelineType = 'music_video' | 'short_film_audio' | 'short_film_story'
export type DirectorShotImageGuidance = 'auto' | 'prompt_only' | 'generate'
export type DirectorShotImagePolicy = 'generate' | 'prompt_only' | 'direct_references'

export interface DirectorCapabilityResult {
  compatible: boolean
  reason: string
}

export interface DirectorModelCompatibility {
  image: DirectorCapabilityResult
  video: Record<DirectorPipelineType | 'seamless', DirectorCapabilityResult>
  supports_audio_input: boolean
  generates_audio: boolean
  supports_voice_reference: boolean
  voice_reference_mode?: 'none' | 'id_lora' | 'native_reference'
  video_strategy?: 'rolling_window' | 'bounded_start_end' | 'omni_reference'
  audio_input_mode?: 'none' | 'generic_audio_guide' | 'reference_manifest' | 'timeline_remux'
  reference_mode?: 'none' | 'start_frame' | 'start_end' | 'omni_manifest'
  shot_image_support?: 'required' | 'optional' | 'direct_references'
  supports_endpoint_continuity?: boolean
  clip_min_frames?: number | null
  clip_max_frames?: number | null
  clip_frame_step?: number | null
  max_image_refs: number | null
}

export interface ModelDef {
  model_type: string
  name: string
  description?: string
  selector_help?: string
  lora_compatibility_note?: string
  family: string
  architecture: string
  is_i2v: boolean
  is_t2v: boolean
  guidance_max_phases: number
  fps: number
  supports_end_frame?: boolean
  /** Legacy broad flag: accepts input audio OR generates output audio. */
  supports_audio?: boolean
  supports_audio_input?: boolean
  generates_audio?: boolean
  supports_ref_images?: boolean
  director?: DirectorModelCompatibility
  is_downloaded?: boolean
  // True when this model is only available with Mature Mode enabled.
  // Backend always returns the entry; UI filters it out when
  // servicesConfig.nsfw_mode is false. When nsfw_mode flips on, the
  // store auto-adds these models to enabledModels so they appear in
  // selectors without the user having to enable each one manually.
  nsfw_only?: boolean
  // Hunyuan3D variants stored in one shared HF repo: deleting this
  // model's cache also removes the weights of every listed sibling.
  shared_cache_group?: string[]
  // Weight-managed tool models (e.g. UniRig): shown in the settings
  // catalog for download/delete, but never selectable for generation.
  tool_only?: boolean
}

export interface Resolution {
  label: string
  value: string
}

export interface GenerateParams {
  prompt: string
  /** ACE-Step "Music Caption" — style/genre/instruments/mood (music mode). */
  alt_prompt?: string
  model_type: string
  resolution: string
  video_length: number
  num_inference_steps: number
  guidance_scale: number
  seed: number
  image_mode: number
  negative_prompt: string
  repeat_generation: number
  activated_loras: string[]
  loras_multipliers: string
  image_start?: string | string[] | null
  image_end?: string | string[] | null
  multi_prompts_gen_type?: number
  sliding_window_size?: number
  sliding_window_overlap?: number
  /** Explicitly honor a manually locked window above the model's VRAM-aware recommendation. */
  sliding_window_memory_override?: boolean
  /** Optional model-specific transformer step cache. */
  skip_steps_cache_type?: '' | 'first_block'
  /** First Block Cache residual-change threshold. */
  skip_steps_multiplier?: number
  /** Percentage of denoising steps to run before caching may begin. */
  skip_steps_start_step_perc?: number
  guidance_phases?: number
  video_prompt_type?: string
  audio_prompt_type?: string
  image_prompt_type?: string
  input_video_strength?: number
  /** Keep an I2V start image's medium and rendering style in the motion prompt. */
  preserve_source_style?: boolean
  /** Fit without distortion (black matte) or explicitly crop to the video canvas. */
  image_fit_mode?: 'contain' | 'source' | 'crop'
  flow_shift?: number
  audio_guide?: string
  audio_scale?: number
  video_guide?: string
  image_refs?: string[]
  /** MiniMax H3 Ref2VA video references (their embedded audio is paired automatically). */
  h3_ref_videos?: string[]
  /** MiniMax H3 Ref2VA standalone audio references. */
  h3_ref_audios?: string[]
  h3_audio_shift?: number
  /** Sound direction written into MiniMax H3's overall_soundscape field. */
  h3_audio_prompt?: string
  h3_ref_image_size?: 'match' | 'max'
  /** Explicit H3 conditioning contract: exact start frame or omni references. */
  h3_reference_mode?: 'first_frame' | 'references'
  /** Quantized MiniMax H3 checkpoint pair; quality/INT8 is recommended for RTX 4090. */
  h3_model_profile?: 'balanced' | 'quality' | 'low_memory'
  frames_positions?: string
  injection_strength?: number
  settings_version?: number
  self_refiner_setting?: number
  stage2_steps?: number
  generation_mode?: string
  per_clip_frames?: number[]
  per_clip_keyframes?: string[][]
  remove_background_images_ref?: number
  // TTS-specific
  audio_guide2?: string
  duration_seconds?: number
  pause_seconds?: number
  temperature?: number
  custom_settings?: Record<string, unknown>
  // Loose params: backend accepts additional optional fields. Declared
  // explicitly here so TypeScript narrows JSX children correctly (an
  // index signature widens explicit fields to `unknown` in some contexts).
  progressive_pipeline?: boolean
  single_stage_pipeline?: boolean
  // Runs the reference two-stage pipeline (baked-in TenStrip 10Eros V5
  // workflow config) instead of the standard one. Only sent for models
  // whose def declares reference_pipeline support.
  reference_pipeline?: boolean
  progressive_stage1_image_weight?: number
  progressive_stage2_steps?: number
  progressive_stage2_sigma?: number
  progressive_stage3_steps?: number
  progressive_stage3_sigma?: number
  progressive_stage3_image_weight?: number
  stg_scale?: number
  // STG only runs when the backend sees perturbation_switch === 2 with the
  // model-correct perturbation_layers; startGeneration derives the switch
  // from stg_scale and _applyModelDefaults supplies the layers/window.
  perturbation_switch?: number
  perturbation_layers?: number[]
  perturbation_start_perc?: number
  perturbation_end_perc?: number
  cfg_rescale?: number
  use_gradient_estimation?: boolean
  ge_gamma?: number
  ge_alpha?: number
  keyframe_conditioning_mode?: string
  keyframe_inject_mode?: string
  MMAudio_setting?: number
  MMAudio_prompt?: string
  MMAudio_neg_prompt?: string
  // Continue / Blend mode
  video_source?: string
  // TTS post-processing extras
  tts_dynaudnorm?: boolean
  tts_comp_threshold?: number
  tts_comp_attack?: number
  tts_comp_release?: number
  tts_comp_makeup?: number
  tts_voice_count?: number
  // MiniMax H3 Ref2VA ordered Omni-reference manifest.
  minimax_h3_references?: MiniMaxH3Reference[]
  minimax_h3_reference_detail?: 'match' | 'max'
  minimax_h3_text_encoder?: 'nvfp4_awq' | 'gguf_q2_k' | 'gguf_q4_k_m' | 'int8' | 'bf16'
  /** One-click managed H3 Turbo recipe for Full or Pruned H3. */
  minimax_h3_turbo_mode?: boolean
  /** Automatically expand one long H3 concept into window-local prompts. */
  minimax_h3_window_storyboard?: boolean
  /** Compiled Context-IR prompts, one per continuation pass. */
  h3_window_prompts?: string[]
  h3_window_plan_signature?: string
  h3_window_plan?: H3WindowPlan
}

export type MiniMaxH3ReferenceType = 'image' | 'video' | 'audio'
export type MiniMaxH3AudioIntent = 'voice' | 'drive' | 'style'

export interface MiniMaxH3Reference {
  id: string
  type: MiniMaxH3ReferenceType
  path: string
  filename: string
  url?: string
  role?: string
  audio_intent?: MiniMaxH3AudioIntent
  include_audio?: boolean
  has_audio?: boolean
  audio_path?: string
  audio_filename?: string
  audio_duration_seconds?: number | null
  duration_seconds?: number | null
}

export interface H3WindowPlanWindow {
  index: number
  title: string
  start_frame: number
  end_frame: number
  start_seconds: number
  end_seconds: number
  opening_state: string
  closing_state: string
  prompt: string
}

export interface H3WindowPlan {
  source_prompt: string
  signature: string
  planned_by: 'llm' | 'deterministic_fallback' | 'not_needed'
  total_frames: number
  window_frames: number
  effective_window_frames?: number
  window_count: number
  resolution: string
  model_type: string
  subject_continuity?: string
  setting_continuity?: string
  windows: H3WindowPlanWindow[]
  window_prompts: string[]
}

/** OOM (out-of-VRAM) failure metadata. Set on jobs and pipelines that
 *  failed with a CUDA OutOfMemoryError. The OomRecoveryBanner watches
 *  for this on the latest failure and surfaces a "Lower VRAM headroom?"
 *  banner with a one-click permanent-fix button. Backend logic in
 *  app/services/oom_detect.py. */
export interface OomInfo {
  is_oom: true
  /** The vram_safety_coefficient value in effect when the OOM happened. */
  current_coefficient: number
  /** Suggested next-lower coefficient (current - 0.10), or null if
   *  current is already at the 0.50 floor — at that point coefficient
   *  can't help and the user needs a smaller model / lower resolution. */
  suggested_coefficient: number | null
  /** Truncated stringified exception for UI display (≤300 chars). */
  message: string
}

/** Frozen, non-sensitive recipe reported by the backend for an active job.
 * It intentionally excludes prompts and local media paths. */
export interface GenerationDetails {
  model_type?: string
  model_name?: string
  generation_mode?: string
  resolution?: string
  seed?: number | string
  steps?: number
  guidance?: number
  frames?: number
  duration_seconds?: number
  dialogue_words?: number
  dialogue_syllables?: number
  dialogue_seconds_per_syllable?: number
  dialogue_duration_calculated?: number
  dialogue_duration_minimum_limited?: boolean
  repeat?: number
  profile?: string
  flow_shift?: number
  audio_shift?: number
  turbo?: boolean
  cache?: boolean
  cache_type?: string
  lora_count?: number
  loras?: string[]
  clip_count?: number
  text_provider?: string
  text_model?: string
  image_model_type?: string
  image_model_name?: string
  image_resolution?: string
  image_steps?: number
  video_model_type?: string
  video_model_name?: string
  video_resolution?: string
  video_steps?: number
}

export interface GenerationJob {
  id: string
  status: 'queued' | 'waiting_resource' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled'
  progress: number
  step: number
  totalSteps: number
  phase: string
  message: string
  outputFiles: string[]
  error: string | null
  createdAt?: number
  /** Active processing start; intentionally absent while only queued. */
  startedAt?: number
  finishedAt?: number
  queuePosition?: number | null
  taskTimings?: GenerationTaskTiming[]
  /** Present only on failed jobs that look like CUDA OOMs (see OomInfo). */
  oomInfo?: OomInfo | null
  /** Exact prompts assigned to an in-flight H3 sliding-window generation. */
  h3WindowPlan?: H3WindowPlan | null
  /** Exact submitted model/settings summary, safe to show in activity UI. */
  generationDetails?: GenerationDetails
}

export interface GenerationTaskTiming {
  panel_no: number
  panel_total: number
  prompt_preview: string
  status: 'running' | 'completed' | 'failed' | 'skipped'
  total_seconds?: number
  phase_timings: Array<{ phase: string; seconds: number }>
}

export interface OutputFile {
  name: string
  url: string
  type: 'video' | 'image' | 'audio' | 'model3d' | 'scene' | 'comic'
  mode: GenerationMode | 'model3d' | null
  /** Edit sub-mode tag from the .meta.json sidecar params (set by the
   *  retake/inpaint/outpaint/restyle/edit_anything endpoints). The gallery's
   *  Edits filter checks this to identify edit-mode outputs regardless of
   *  the parent `mode`, since e.g. outpaint endpoints write mode='video'. */
  edit_sub_mode?: EditSubMode | null
  favorite: boolean
  size: number
  created_at: number
  /** Unix timestamp for when generation and output publication finished. */
  completed_at?: number
  /** Metadata is exact; file is a best-effort fallback for legacy/imports. */
  completion_time_source?: 'metadata' | 'file'
  /** Static preview for 3D output cards; never a live model viewer. */
  thumbnail_url?: string | null
  /** Assembled production result, never a component clip. */
  result_kind?: VideoResultKind | null
}

export type SceneLayerType = 'model3d' | 'image' | 'video' | 'overlay' | 'effect' | 'camera'
export type SceneAtmosphereKind =
  | 'rain'
  | 'snow'
  | 'dust'
  | 'embers'
  | 'fog'
  | 'smoke'
  | 'ash'
  | 'fireflies'
  | 'confetti'
  | 'bokeh'
  | 'sparkles'
  | 'bubbles'
  | 'speedlines'
  | 'leaves'
export type SceneCurve = 'linear' | 'ease' | 'dramatic' | 'bounce'
export type SceneFrameRate = 30 | 60
export type SceneBlendMode = 'normal' | 'multiply' | 'screen' | 'overlay' | 'lighten' | 'darken'
export type SceneMask = 'none' | 'rounded' | 'ellipse'

export interface SceneKeyframe {
  id: string
  /** Seconds from the beginning of this layer's animation. */
  time: number
  x: number
  y: number
  scale: number
  opacity: number
  rotation: number
  /** Easing used from this keyframe to the next one. */
  curve: SceneCurve
}

export interface SceneAnimationEvent {
  id: string
  /** Local layer time in seconds, before offset/speed/loop are applied. */
  time: number
  name: string
  /** Optional plain-text metadata for a game engine, sound cue or external tool. */
  payload?: string
}

export interface SceneLayer {
  id: string
  name: string
  type: SceneLayerType
  source: string
  thumbnail?: string
  visible: boolean
  z: number
  /** Prevent accidental transform, timing and inspector edits. */
  locked?: boolean
  /** Object URLs cannot survive a scene export/import and need reassignment. */
  missingAsset?: boolean
  /** Image/video is cropped to cover the complete scene frame. */
  fill?: boolean
  /** Deterministic full-frame procedural particles, shared by preview,
   * scene JSON and browser capture. Only used by effect layers. */
  atmosphere?: {
    kind: SceneAtmosphereKind
    density: number
    speed: number
    size: number
    wind: number
    color: string
  }
  /** Camera-pan multiplier: 0 ignores camera pan, 1 follows it normally,
   *  and values above 1 create foreground parallax. Camera zoom/roll still
   *  affect every visual layer. Ignored by camera layers. */
  parallax?: number
  relationship?: {
    type: 'parent' | 'follow' | 'lookAt'
    targetLayerId: string
    offsetX?: number
    offsetY?: number
    strength?: number
    rotationOffset?: number
  }
  /** 2D composition effects shared by DOM preview and canvas capture. */
  effects?: {
    blur?: number
    brightness?: number
    contrast?: number
    saturation?: number
    hue?: number
    glow?: number
    shadow?: number
    blendMode?: SceneBlendMode
    mask?: SceneMask
    maskRadius?: number
  }
  /** Repeats this visual layer along one axis and scrolls the copies in a
   * seamless loop. Useful for music-video strips, cascades and tiled props. */
  strip?: {
    enabled: boolean
    count: number
    spacing: number
    direction: 'up' | 'down' | 'left' | 'right'
    /** Scene-percent units travelled per second. */
    speed: number
    /** Initial offset along the selected axis, in scene percent. */
    phase?: number
    /** Foreground silhouette locked to each tile join so a looping plate never shows its seam. */
    seamOccluder?: {
      enabled: boolean
      kind: 'pole' | 'lamp' | 'tree' | 'column'
    }
  }
  transform: {
    x: number
    y: number
    scale: number
    opacity: number
    /** 2D rotation for images/video/overlays. */
    rotation?: number
    /** Persisted model-viewer camera orbit in degrees. */
    rotationX?: number
    rotationY?: number
  }
  animation: {
    start: { x: number; y: number; scale: number; opacity?: number; rotation?: number }
    end: { x: number; y: number; scale: number; opacity?: number; rotation?: number }
    /** Multi-keyframe timeline. Older scenes continue to use start/end. */
    keyframes?: SceneKeyframe[]
    /** Metadata markers only; Maestro does not execute them during browser capture. */
    events?: SceneAnimationEvent[]
    duration: number
    curve: SceneCurve
    /** Scene time in seconds before this layer's local motion starts. */
    offset?: number
    /** Local motion playback multiplier. */
    speed?: number
    /** Repeat the selected local time range until the scene ends. */
    loop?: boolean
    /** Optional local in/out range, in seconds. */
    trimStart?: number
    trimEnd?: number
    /** Deterministic camera shake; only used by camera layers. */
    shake?: {
      amount: number
      frequency: number
      seed?: number
      /** Optional local-time window used when a shake preset is chained. */
      startTime?: number
      endTime?: number
    }
    spin?: boolean
    rotationSpeed?: number
    /** Name of a baked glTF skeletal clip to play (rigged GLB layers). */
    clip?: string
    /** Skeletal clip timing is independent from the layer transform timing. */
    clipOffset?: number
    clipSpeed?: number
    clipReverse?: boolean
    clipLoop?: boolean
    clipTrimStart?: number
    clipTrimEnd?: number
    /** Optional motion relationship: this layer circles another scene layer. */
    orbit?: {
      targetLayerId: string
      radiusX: number
      radiusY: number
      turns: number
      phase: number
      /** Number of evenly-spaced instances travelling around the target. */
      count?: number
      /** Keeps the original angle or points each instance toward/away from the target. */
      facing?: 'fixed' | 'center' | 'outward'
      /** Fine adjustment from the target layer's visual center, in scene percent. */
      centerOffsetX?: number
      centerOffsetY?: number
    }
  }
}

export interface Scene {
  version: 1
  name: string
  width: number
  height: number
  /** Preview, timeline and browser capture sampling rate. Defaults to 30 for legacy scenes. */
  fps?: SceneFrameRate
  duration: number
  layers: SceneLayer[]
  composition?: {
    showGrid: boolean
    gridSize: number
    snap: boolean
    safeArea: 'none' | 'action' | 'title' | 'vertical' | 'all'
  }
  /** Durable, serializable record of copilot edits. Kept with the scene so
   * save/export can retain the exact human intent and applied operations. */
  copilotAudit?: Array<{
    id: string
    createdAt: string
    scope: 'layer' | 'scene'
    selectedLayerId?: string
    intent: string
    summary: string
    operations: Array<Record<string, unknown>>
    validation: 'applied'
    model?: string
  }>
  /** Template provenance remains with an editable scene and its exported MP4 metadata. */
  narrative?: {
    templateId: string
    controls: Record<string, string | number | boolean | undefined>
    /** The exact existing assets assigned when the template was mounted. */
    assets?: Array<{ slot: string; source: string; name?: string; type?: SceneLayerType }>
    /** Deterministic human-readable direction used to compile this template. */
    prompt?: string
  }
}

export type VideoResultKind = 'music_video' | 'trailer' | 'series_episode' | 'chapter'
export type MediaFilter = 'all' | 'images' | 'videos' | 'audio' | 'model3d' | 'scenes' | 'stories' | 'series' | 'styles' | 'comics' | 'videoeditor' | 'scene3d' | 'animate3d' | 'avatars' | 'multiclip' | 'favorites' | 'workspaces' | 'characters' | 'videoclips' | 'trailers' | 'series_episodes' | 'auditdev'
export type AspectRatio = 'auto' | '21:9' | '16:9' | '9:16' | '1:1' | '4:3' | '3:4'
export type ResolutionPreset = 'auto' | '480p' | '540p' | '720p' | '768p' | '1080p'
export type ScailResolutionProfile = '480p' | '512p' | '704p'
/** Backward-compatible name for saved Recast/API callers. */
export type RecastResolutionProfile = ScailResolutionProfile
export type GenerationMode = 'image' | 'video' | 'audio' | 'model3d' | 'avatar' | 'tools'
export type EditSubMode = 'retake' | 'inpaint' | 'restyle' | 'outpaint' | 'edit_anything' | 'recast'
export type AudioSubMode = 'speech' | 'music' | 'sfx' | 'mixer'

export interface RecastReferenceAsset {
  file: File | null
  path: string
  url: string
}

export interface RecastCharacterMapping {
  id: string
  target: string
  refFile: File | null
  refPath: string
  refUrl: string
  additionalRefs: RecastReferenceAsset[]
  referenceAlignedToSource: boolean
}

/** Optional SCAIL-2 Repaint correspondence. The source phrase is tracked
 * through the control video and the target phrase is segmented in the edited
 * first frame; both receive the same stable semantic color. */
export interface RepaintRegionMapping {
  id: string
  source: string
  target: string
}

export interface ChoiceConfig {
  selection?: string[]
  choices?: [string, string][]
  labels?: Record<string, string>
  default?: string
  label?: string
  show_label?: boolean
  letters_filter?: string
}

export interface SlidingWindowMemoryPolicy {
  checkpoint?: 'full' | 'pruned'
  manual_override?: boolean
  auto_resolution_pixels?: Record<string, number>
  resolution_bands: Array<{
    min_pixels: number
    vram_tiers: Array<{
      max_vram_gb?: number
      frames: number | null
      fallback_resolution?: string
    }>
  }>
}

export interface ModelOptions {
  model_type: string
  architecture: string
  guidance_max_phases: number
  lock_guidance_phases: boolean
  sliding_window: boolean
  video_continuation?: boolean
  motion_amplitude: boolean
  flow_shift: boolean
  tea_cache: boolean
  first_block_cache?: boolean
  skip_steps_multiplier_choices?: [string, number][] | null
  skip_steps_multiplier_label?: string
  default_skip_steps_multiplier?: number
  default_skip_steps_start_step_perc?: number
  returns_audio: boolean
  any_audio_prompt: boolean
  audio_scale_name: string
  lock_inference_steps: boolean
  lock_guidance_scale: boolean
  no_negative_prompt: boolean
  i2v_class: boolean
  t2v_class: boolean
  image_outputs: boolean
  supports_end_frame: boolean
  /** Which conditioning letters the model accepts: T(ext), S(tart), E(nd), V(ideo), L(ast). */
  image_prompt_types_allowed?: string
  video_guide_label?: string | null
  omni_reference?: boolean
  omni_reference_limits?: {
    image: number
    video: number
    audio: number
    total: number
  } | null
  omni_reference_detail_choices?: [string, 'match' | 'max'][] | null
  omni_reference_detail_default?: 'match' | 'max'
  minimax_h3_text_encoder_choices?: {
    value: string
    label: string
    size_hint: string
    recommended?: boolean
  }[] | null
  minimax_h3_text_encoder_default?: string
  minimax_h3_turbo?: {
    filename: string
    label: string
    experimental: boolean
    steps: number
    weight: number
    guide: string
  } | null
  minimax_h3_runtime_advisory?: {
    level: 'warning' | 'info'
    title: string
    message: string
    reasons: Array<{
      code: 'triton_unavailable' | 'system_ram_low' | string
      message: string
    }>
    recommended_model_type?: string
    recommended_turbo?: boolean
    estimated_pipeline_ram_gb?: number
    minimum_system_ram_gb?: number
    detected_ram_gb?: number | null
    supports_triton?: boolean | null
    blocking: boolean
  } | null
  resolution_presets?: Partial<Record<ResolutionPreset, {
    label: string
    experimental?: boolean
    hint?: string
    values: Partial<Record<AspectRatio, string>>
  }>> | null
  resolution_preset_order?: ResolutionPreset[] | null
  supports_auto_aspect?: boolean
  guide_preprocessing: ChoiceConfig | null
  guide_custom_choices: ChoiceConfig | null
  image_ref_choices: ChoiceConfig | null
  audio_prompt_type_sources: ChoiceConfig | null
  background_removal_label: string | null
  max_image_refs?: number | null
  sample_solvers: [string, string][] | null
  self_refiner: boolean
  self_refiner_max_plans: number
  sliding_window_defaults: Record<string, number> | null
  sliding_window_auto_prompt_pacing?: boolean
  sliding_window_memory_policy?: SlidingWindowMemoryPolicy | null
  /** Native one-pass policy used by Director. Omni publishes this without
   * exposing Studio sliding-window controls. */
  director_memory_policy?: SlidingWindowMemoryPolicy | null
  // LTX-2 Dev pipeline capabilities (guidance controls in Advanced Settings)
  perturbation?: boolean
  reference_pipeline?: boolean
  cfg_star?: boolean
  adaptive_projected_guidance?: boolean
  audio_guidance?: boolean
  fps: number
  frames_minimum: number
  frames_steps: number
  frames_maximum?: number | null
  default_num_inference_steps: number | null
  /** Model's preferred flow shift, applied on model selection. Distinct from
   *  the `flow_shift` boolean above, which only says whether to show the
   *  control. */
  default_flow_shift?: number | null
  /** The model's declared temporal grid (mirrors align_model_frame_count).
   *  modulus 0 means the model declares none and frame counts are left alone. */
  frame_alignment_modulus?: number
  frame_alignment_remainder?: number
  frame_alignment_mode?: string
  default_guidance_scale: number | null
  hide_resolution_presets: boolean
  input_video_strength_label: string
  vae_upsampler_modes: number[]
  // TTS-specific
  audio_only: boolean
  duration_slider: { label: string; min: number; max: number; increment: number; default: number } | null
  pause_between_sentences: boolean
  temperature_enabled: boolean
  custom_settings_def: { id: string; label: string; name: string; type: string }[] | null
  h3_reference_inputs?: boolean
}

export interface SystemConfig {
  // HocusPocus release version (repo-root VERSION file), shown next to the
  // app title. Optional: older backends don't send it.
  app_version?: string
  attention_mode: string
  transformer_quantization: string
  vae_config: number
  compile: string
  video_profile: number
  image_profile: number
  audio_profile: number
  video_output_codec: string
  image_output_codec: string
  enhancer_enabled: number
  prompt_enhancer_quantization: string
  attention_modes_available: string[]
  vram_safety_coefficient: number
  // Linked model folders (absolute paths outside the Maestro install,
  // e.g. an existing Wan2GP install's ckpts). Searched read-only for
  // already-downloaded checkpoints; new downloads always go to Maestro's
  // own ckpts folder.
  model_folders: string[]
}

export interface ModelFolderCandidate {
  app: string
  path: string
  files: number
  folders: number
  size_gb: number
  linked: boolean
}

export interface OutputGenerationTimings {
  total_time_sec?: number | null
  prompt_generation_time_sec?: number | null
  image_generation_time_sec?: number | null
  video_generation_time_sec?: number | null
  assembly_time_sec?: number | null
}

export interface OutputMetadata {
  source: 'sidecar' | 'embedded' | 'none'
  params: Record<string, unknown> | null
  upload_filenames?: Record<string, string>
  job_id?: string
  task_id?: string | null
  root_task_id?: string | null
  generation_time?: number
  generation_timings?: OutputGenerationTimings
  director_pipeline_id?: string
  created_at?: number
  completed_at?: number
  finished_at?: number
}

export interface VideoExtraInfo {
  overview: string
  youtube: {
    title: string
    description: string
  }
  x: {
    post: string
  }
  language: string
  language_label: string
  source_fingerprint: string
  prompt_count: number
  director_context: boolean
  generated_at?: number
}

export interface VideoClipInfo {
  name: string
  created_at: number | null
  file_modified_at: number | null
  file_size_bytes: number
  job_id: string
  generation_mode: string
  model_type: string
  resolution: string
  seed: string | number | null
  video_length_frames: string | number | null
  num_inference_steps: string | number | null
  guidance_scale: string | number | null
  generation_time_sec: number | null
  generation_timings: OutputGenerationTimings
  prompt: string
  negative_prompt: string
  audio_prompt: string
  saved_metadata: Record<string, unknown>
}

export interface VideoExtraInfoStatus {
  available: boolean
  language: string
  language_label: string
  data: VideoExtraInfo | null
  prompt_count: number
  director_context: boolean
  clip: VideoClipInfo
}

export interface MultiClipKeyframe {
  file: File | null
  path: string | null
}

export interface MultiClip {
  prompt: string
  startImage: File | null
  startImagePath: string | null
  endImage: File | null
  endImagePath: string | null
  durationFrames?: number
  keyframes: MultiClipKeyframe[]
}

export type SettingsTab = 'performance' | 'integrations'

export interface ProductionProfile {
  version: 1
  text: {
    provider: 'local' | 'remote' | 'openai' | 'anthropic' | 'deepseek' | 'minimax' | 'openai-compatible'
    model: string
  }
  image: {
    provider: 'maestro' | 'local' | 'minimax'
    model: string
  }
  music: {
    provider: 'maestro' | 'local' | 'minimax'
    model: string
  }
  video: {
    provider: 'maestro' | 'local'
    model: string
    settings: {
      profile: string
      steps: number
      flowShift: number
      audioShift: number
      turbo: boolean
      cache: boolean
      loras: string[]
      resolution: ResolutionPreset
      aspectRatio: AspectRatio
    }
  }
}

export interface ServicesConfig {
  llm_model_id: string
  llm_device: string
  llm_provider: string
  llm_remote_url: string
  enhance_llm_model_id: string
  enhance_llm_device: string
  google_api_key: string
  google_api_key_set: boolean
  openai_api_key: string
  openai_api_key_set: boolean
  deepseek_api_key: string
  deepseek_api_key_set: boolean
  compatible_api_key: string
  compatible_api_key_set: boolean
  compatible_base_url: string
  anthropic_api_key: string
  anthropic_api_key_set: boolean
  minimax_api_key: string
  minimax_api_key_set: boolean
  use_director_v2: boolean
  nsfw_mode: boolean
  nsfw_accepted_at: string | null
  director_prompt_polish: 'off' | 'full_guide' | 'light_guide' | 'third_pass'
  workflow_parallelism_enabled: boolean
  debug_trace_enabled: boolean
  debug_trace_log_path: string
  civitai_api_key: string
  civitai_api_key_set: boolean
  voice_reference_enabled: boolean
  ltx_progressive_pipeline: boolean
  /** Master gate for experimental / power-user features. When false
   *  (default), the Services panel hides Director v2 engine, Voice
   *  Reference, external API keys (Google/OpenAI/Anthropic), and the
   *  Studio prompt enhancer config; the Edit mode picker hides
   *  Inpaint. Flipping this on surfaces all of them. */
  show_experimental: boolean
  /** Storage Manager opt-in: allow removing duplicate files FROM linked
   *  installs (Recycle Bin only). Default off — informed consent. */
  storage_allow_linked_removal?: boolean
  /** Performance auto-tune master switch. When true (default for fresh
   *  installs), Settings → System Performance shows a single auto card
   *  with detected hardware + recommended profile, and the underlying
   *  knobs collapse under "Show advanced settings". When false (set
   *  automatically on migration for pre-existing installs), the
   *  advanced fields are visible by default and the user is in
   *  manual mode. Editing any field while auto is on flips this off. */
  auto_performance: boolean
  /** Multi-shot LoRA mode. When true, Pass 2 emits storyboard-format
   *  video_prompts for 20s shots, letting an IC-LoRA (e.g. Maque AI
   *  LTX-2.3 IC-LoRA) cut between camera angles inside a single
   *  generation. Short reaction shots (≤15s) and long sustained
   *  shots (≥40s) keep the regular single-camera flowing format.
   *  User must also have the matching LoRA in their video_loras
   *  selection for the cuts to actually render. */
  director_multishot_lora_mode: boolean
  /** FlashVSR (DiT super-resolution) spatial-upsampling settings.
   *  flashvsr_mode: 1=tiny, 2=full, 3=tiny-long. topk_ratio 0..4 (sparse-attn
   *  density). backend: 'auto' | 'triton_sparse' | 'sparge'. */
  flashvsr_mode: number
  flashvsr_topk_ratio: number
  flashvsr_backend: string
}

// Performance Auto-Tune (Settings → System Performance card) — backed
// by GET /api/v1/system-detect and POST /api/v1/system-detect/apply.
// The card shows the user's detected hardware + the recommended
// profile in plain English; the apply endpoint writes the
// recommendation into wgp_config.json.

/** Hardware detection result from /api/v1/system-detect. Mirrors the
 *  schema documented in app/services/hardware_detect.py — keep in sync
 *  if you add new probe fields there. */
export interface HardwareInfo {
  cuda_available: boolean
  gpu_name: string
  gpu_vram_gb: number
  gpu_capability: string  // e.g. "sm89", "sm120", or "" if no CUDA
  ram_gb: number
  cpu_count: number
  ram_tier: 'high' | 'low' | 'very_low'
  vram_tier: 'high' | 'low' | 'tight' | 'none'
  supports_fp8: boolean
  supports_nvfp4: boolean
  supports_sage: boolean
  supports_sage2: boolean
  supports_flash: boolean
  supports_triton: boolean
}

/** Recommended settings the auto-tune engine produced for the detected
 *  hardware. Underscore-prefixed fields are display-only metadata —
 *  the rest are config keys that get written to wgp_config.json. */
export interface RecommendedSettings {
  video_profile: number
  image_profile: number
  audio_profile: number
  transformer_quantization: 'int8' | 'fp8' | 'bf16'
  vae_config: number
  vram_safety_coefficient: number
  attention_mode: string
  compile: string
  /** Friendly label for the auto card, e.g. "Profile 1 — Optimized for fastest generation" */
  _recommendation_label: string
  /** Verbose reason string for tooltips and debug logs */
  _recommendation_reason: string
}

/** Response shape from GET /api/v1/system-detect. */
export interface SystemDetectResponse {
  hardware: HardwareInfo
  recommended: RecommendedSettings
  auto_enabled: boolean
}

/** Response shape from POST /api/v1/system-detect/apply. */
export interface SystemDetectApplyResponse {
  status: string
  hardware: HardwareInfo
  applied: Record<string, unknown>
  label: string
  reason: string
  /** True when one of the *_profile keys changed — UI should show
   *  "changes take effect on next model load" toast. */
  profile_changed: boolean
}

// CivitAI Browser types
export interface CivitAIModel {
  id: number
  name: string
  description?: string
  type: string
  nsfw: boolean
  tags: string[]
  creator: { username: string; image: string | null }
  stats: { downloadCount: number; favoriteCount: number; thumbsUpCount: number; rating: number; ratingCount: number }
  modelVersions: CivitAIModelVersion[]
}

export interface CivitAIModelVersion {
  id: number
  name: string
  baseModel: string
  trainedWords: string[]
  files: CivitAIFile[]
  images: CivitAIImage[]
  description?: string
  localArch?: string | null
  /** Version release date from CivitAI — persisted into the download
   *  sidecar so My LoRAs can sort by newest release. */
  publishedAt?: string
}

export interface CivitAIFile {
  id: number
  name: string
  sizeKB: number
  type: string
  downloadUrl: string
  metadata: { format?: string; size?: string; fp?: string }
}

export interface CivitAIImage {
  url: string
  type: string
  width: number
  height: number
  nsfwLevel: number
  meta?: { prompt?: string; negativePrompt?: string; steps?: number; cfgScale?: number; sampler?: string }
}

export interface CivitAISearchResult {
  items: CivitAIModel[]
  metadata: { nextCursor?: string; totalItems?: number }
}

export interface CivitAIDownload {
  id: string
  filename: string
  status: 'downloading' | 'completed' | 'failed'
  progress: number
  bytes_downloaded: number
  bytes_total: number
  error: string | null
  /** Unix timestamps (seconds) supplied by the download registry. */
  started_at: number | null
  completed_at: number | null
  /** Present after a downloaded checkpoint is registered as a model. */
  model_type?: string | null
  // Non-fatal warnings raised after the download finished — most
  // commonly the architecture-mismatch warning when a Klein-4B-trained
  // LoRA lands in flux2_klein_9b/ or vice versa. UI shows these inline
  // on the download row.
  warnings?: string[]
}

export interface LoraWeightPhase {
  phase: number
  default: number
  min: number
  max: number
  label: string
}

export interface LoraRecommendedWeights {
  source?: 'civitai' | 'default'
  default: number
  min: number
  max: number
  phases?: LoraWeightPhase[]
}

export interface LoraInfo {
  filename: string
  trained_words: string[]
  preview_url: string | null
  civitai_model_id: number | null
  recommended_weights: LoraRecommendedWeights | null
  /** Managed choices may be listed before their first-use download. */
  managed?: boolean
  has_guide: boolean
  guide?: string | null
  /** NSFW flag from the .civitai.json sidecar (or inferred from filename/tags).
   *  Used to filter out adult-content LoRAs from the Advanced Settings list
   *  unless the user explicitly opts in. */
  nsfw?: boolean
  /** True when the user has manually overridden the NSFW classification via
   *  /api/v1/loras/nsfw-override. The UI surfaces this so the user can tell
   *  at a glance which LoRAs they've corrected vs which are using CivitAI's
   *  raw flag. */
  nsfw_overridden?: boolean
  /** ISO timestamp of when the file was downloaded — sidecar `downloadedAt`
   *  when present, else the weight file's mtime. Shown as an age chip in
   *  the Studio/Director LoRA pickers. */
  downloaded_at?: string | null
  /** ISO timestamp of the CivitAI version's publish date (sidecar
   *  `publishedAt`). Null for HF/hand-installed LoRAs without sidecar data. */
  released_at?: string | null
  /** Stable identifier that survives version updates.
   *  Format: `civitai:{modelId}` when sidecar has a CivitAI modelId,
   *  otherwise `local:{filename}`. Use this as the persistence key for
   *  activations, weights, and other LoRA-keyed state instead of the
   *  filename, so updating a LoRA from v1.2 → v1.5 carries settings forward. */
  lora_id: string
  /** Update status from the cached CivitAI manifest. Populated by
   *  /api/v1/loras/check-updates and surfaced through this endpoint
   *  without an extra round-trip. The UI uses this to render badges. */
  update_status?: LoraUpdateStatus
  latest_version_id?: number | null
  current_version_id?: number | null
  latest_published_at?: string | null
  latest_changelog?: string | null
}

/** Per-LoRA update state surfaced from the cached manifest.
 *  - `current`:   sidecar version matches CivitAI's latest
 *  - `available`: a newer version exists on CivitAI
 *  - `unknown`:   not yet checked, no sidecar, or transient API failure
 *  - `local`:     no CivitAI sidecar at all (hand-installed / personal LoRA)
 *  - `removed`:   CivitAI returned 404 (creator unpublished or deleted) */
export type LoraUpdateStatus = 'current' | 'available' | 'unknown' | 'local' | 'removed'

export interface LlmStatus {
  loaded: boolean
  model_id: string | null
  device: string | null
  provider: string
}

/** Live hardware telemetry for the sidebar status indicators.
 *  Backs HardwareStatusBar; polled ~2s via GET /api/v1/system-stats. */
export interface SystemStats {
  cpu: { percent: number }
  ram: { percent: number; used_gb: number; total_gb: number }
  gpu: {
    available: boolean
    /** Headline GPU utilization. On Windows this is the 3D-engine perf
     *  counter (matches Task Manager); elsewhere the NVML/nvidia-smi value. */
    percent: number
    /** NVML / nvidia-smi compute utilization, kept for the tooltip. */
    compute_percent?: number
    vram_used_gb: number
    vram_total_gb: number
    vram_percent: number
  }
  /** Generation model currently resident in VRAM (WGP/mmgp). `loaded`
   *  distinguishes "actually in memory now" from "last/selected type". */
  model: { name: string | null; model_type: string | null; loaded: boolean }
  /** Changes when Maestro restarts or a different React build is deployed.
   *  The client uses it to avoid running a stale bundle indefinitely. */
  runtime?: { instance_id: string; ui_build_id: string }
}

export interface LlmModelOption {
  id: string
  label: string
  size_hint: string
}

export interface AudioBeat {
  time: number
  strength: number
}

export interface AudioSection {
  start: number
  end: number
  label: string
  energy: number
}

export interface LyricSegment {
  start: number
  end: number
  text: string
  speaker?: string | null
}

export interface SongStructureEntry {
  label: string
  display_label: string
  start: number
}

export interface AudioAnalysisResult {
  duration: number
  sample_rate: number
  bpm: number
  beats: AudioBeat[]
  downbeats: number[]
  sections: AudioSection[]
  onset_envelope: number[]
  lyrics: LyricSegment[] | null
  vocals_path: string | null
  warnings?: string[] | null
  song_structure?: SongStructureEntry[] | null
}

export interface SuggestedClip {
  start: number
  end: number
  section_label: string
  energy: number
  suggested_prompt_hint: string
}

export interface PlannedClip extends SuggestedClip {
  beat_count: number
  duration_frames: number
  dominant_speaker?: string | null
}

export interface SpeakerMapping {
  speakerId: string
  name: string
  role: 'rapping' | 'singing' | 'speaking' | ''
}

export interface ClipPlan {
  video_prompt: string
  image_prompt: string
  window_prompts?: Array<string | { prompt?: string; text?: string }>
  h3_segment_prompts?: string[]
  metadata?: Record<string, unknown>
}

export type MusicVideoMode = 'performance' | 'narrative' | 'hybrid' | 'abstract'
export type MusicVideoLipSync = 'frequent' | 'occasional' | 'none'
export type MusicVideoGenerationMode = 'image_guided' | 'direct_video'

export const LEGACY_HEAVY_METAL_DIRECT_VIDEO_MASTER_PROMPT = 'A scene from the 1981 adult animated science fiction anthology film Heavy Metal, professional color grading, in the exact visual style and aesthetics of the 1981 film Heavy Metal. In the distinctive painted animation style of Heavy Metal 1981: painterly textures, grainy film texture, dark saturated colors, strong contrast, rough ink contours, airbrushed highlights and the classic heavy metal fantasy / sci-fi atmosphere of the 1981 film. World vocabulary: alien warriors, industrial spacecraft, decadent neon cities, monsters and alien deserts under red or purple skies. Never anime, clean digital art, modern 3D CGI or photorealistic live action.'

export const DEFAULT_DIRECT_VIDEO_MASTER_PROMPT = 'Maintain one coherent visual language across every clip. Keep recurring characters, materials, palette, lighting and rendering technique consistent. Do not introduce another medium or visual style unless it is explicitly requested.'

export interface MusicVideoTreatment {
  generation_mode: MusicVideoGenerationMode
  direct_video_master_prompt: string
  mode: MusicVideoMode
  performer_presence: number
  lip_sync: MusicVideoLipSync
  recurring_sets: string[]
  wardrobe: string
  palette: string
  camera_language: string
  recurring_motif: string
  chorus_signature: string
  surrealism: number
  forbidden_elements: string
}

/** Partial plan returned from single-phase LLM calls */
export interface PartialClipPlan {
  video_prompt?: string
  image_prompt?: string
}

export interface DirectorClipImage {
  clipIndex: number
  shotId?: string
  prompt: string
  file: File | null
  filename: string
}

export interface DirectorImageGenProgress {
  current: number
  total: number
  currentClipLabel: string
  status: 'generating' | 'polling' | 'downloading' | 'done' | 'error'
}

// `comic` is the UI workflow selector; `comic_movie` is the canonical
// Director V2 planner value returned by the backend.
export const DIRECTOR_SKILLS = ['music_video', 'short_film', 'podcast', 'viral_video', 'comic', 'comic_movie'] as const
export type DirectorSkill = typeof DIRECTOR_SKILLS[number]

export function isDirectorSkill(value: unknown): value is DirectorSkill {
  return typeof value === 'string' && (DIRECTOR_SKILLS as readonly string[]).includes(value)
}
export type ShortFilmPath = 'audio' | 'story'

export interface ShortFilmCharacter {
  name: string
  description: string
}

export interface ShortFilmScene {
  scene_number: number
  title: string
  start: number
  end: number
  duration_frames: number
  characters: string[]
  dialogue: string[]
  action: string
  mood: string
}

// ── Director v2 Schema Types ──────────────────────────────────────────

export interface DirectorFlags {
  use_shared_shot_schema?: boolean
  use_mode_specific_renderers?: boolean
  use_prompt_validation?: boolean
  use_prompt_compression?: boolean
  use_llm_refinement?: boolean
  aggressive_compression?: boolean
  log_validation_details?: boolean
  log_compression_deltas?: boolean
}

export interface SubjectRef {
  visual_description: string
  character_id?: string
  position_or_relation?: string
}

export interface DialogueBeat {
  spoken_text: string
  speaker_id?: string
  delivery?: string
  physical_cue?: string
  priority?: 'low' | 'medium' | 'high'
}

export interface CameraPlan {
  framing: string
  angle?: string
  movement?: string
  movement_intensity?: 'static' | 'subtle' | 'moderate' | 'dynamic'
  lens_feel?: string
  reframing_notes?: string
}

export interface AudioPlan {
  mode: 'generated_audio' | 'audio_driven' | 'dialogue_driven' | 'music_driven' | 'ambient_only'
  ambience?: string
  effects?: string[]
  vocal_style?: string
  timing_anchor?: 'audio' | 'video' | 'balanced'
  lip_sync_critical?: boolean
}

export interface ShotPlan {
  shot_id: string
  index: number
  duration_sec: number
  skill_type: DirectorSkill
  scene_goal: string
  narrative_role?: string
  scene_type?: string
  source_mode_preference?: 't2v' | 'i2v' | 'a2v' | 'retake' | 'extend'
  image_strategy?: 'reference_edit' | 'reference_inspired' | 'fresh_generation' | 'none'
  continuity_strategy?: 'independent' | 'continuous' | 'extend_previous'
  subjects_on_screen: SubjectRef[]
  spatial_setup: string
  environment: string
  visual_style: string
  lighting: string
  mood: string
  action_beats: string[]
  performance_beats?: string[]
  dialogue_beats?: DialogueBeat[]
  camera_plan: CameraPlan
  audio_plan: AudioPlan
  ending_beat: string
  constraints?: string[]
  continuity_refs?: string[]
  metadata?: Record<string, unknown>
}

export interface CharacterProfile {
  id: string
  physical_description: string
  display_name?: string
  wardrobe?: string
  voice_description?: string
}

export interface ProductionPlan {
  skill_type: DirectorSkill
  shots: ShotPlan[]
  title?: string
  global_style?: string
  total_duration_sec?: number
  characters?: CharacterProfile[]
  continuity_notes?: string[]
}

export interface DirectorV2PlanRequest {
  skill_type: DirectorSkill
  activity_id?: string
  workspace?: string
  plan_job_id?: string
  scene_description?: string
  story_description?: string
  clips?: unknown[]
  lyrics?: unknown[]
  bpm?: number
  reference_image_path?: string
  character_ref_paths?: string[]
  character_ref_labels?: string[]
  location_ref_paths?: string[]
  location_ref_labels?: string[]
  speaker_mappings?: Record<string, unknown>
  characters?: Array<{ name: string; description: string }>
  audio_path?: string
  target_duration?: number
  target_scenes?: number
  narrative_mode?: boolean
  fps?: number
  frames_steps?: number
  frames_minimum?: number
  concept?: string
  visual_style?: string
  preserve_visual_style?: boolean
  character_visual_style?: string
  allow_clip_text?: boolean
  platform?: string
  style?: string
  prompt_type?: string
  image_model?: string
  video_model?: string
  h3_reference_mode?: 'first_frame' | 'references'
  h3_audio_prompt?: string
  seamless?: boolean
  multishot_lora_mode?: boolean
  music_video_treatment?: MusicVideoTreatment
  director_flags?: Record<string, boolean>
}

export interface DirectorV2PlanProgress {
  id: string
  status: 'running' | 'completed' | 'failed'
  phase: string
  current: number
  total: number
  detail: string
  stream_text?: string
  stream_done?: boolean
  usage?: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
    calls?: number
  }
}

export interface DirectorV2PlanResponse {
  clip_plans: Array<{ video_prompt: string; image_prompt: string }>
  production_plan: ProductionPlan
  skill_type: DirectorSkill
  plan_job_id?: string
}

export interface DirectorV2PlanJob {
  jobId: string
  workspace: string
  skillType: DirectorSkill
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  phase: string
  message: string
  total: number
  completedIndices: number[]
  missingIndices: number[]
  completedBatches: Array<{ indices: number[]; completedAt: number }>
  activeBatch: number[]
  calls: number
  usage: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
    calls?: number
  }
  error?: string | null
  result?: DirectorV2PlanResponse | null
  createdAt: number
  updatedAt: number
  finishedAt?: number | null
}

export interface DirectorV2PlanFailureDetail {
  code: 'director_plan_incomplete'
  message: string
  job: DirectorV2PlanJob
  resume: {
    action: 'resume_missing'
    method: 'POST'
    path: string
  }
  imagesQueued: false
}

/** Runtime boundary for durable Director job snapshots returned on failures. */
export function isDirectorV2PlanJob(value: unknown): value is DirectorV2PlanJob {
  if (!value || typeof value !== 'object') return false
  const job = value as Record<string, unknown>
  const statuses = ['queued', 'running', 'completed', 'failed', 'cancelled']
  const isNumberArray = (items: unknown): items is number[] => (
    Array.isArray(items) && items.every(item => Number.isInteger(item))
  )
  return typeof job.jobId === 'string'
    && typeof job.workspace === 'string'
    && isDirectorSkill(job.skillType)
    && typeof job.status === 'string'
    && statuses.includes(job.status)
    && typeof job.phase === 'string'
    && typeof job.message === 'string'
    && typeof job.total === 'number'
    && isNumberArray(job.completedIndices)
    && isNumberArray(job.missingIndices)
    && Array.isArray(job.completedBatches)
    && isNumberArray(job.activeBatch)
    && typeof job.calls === 'number'
    && !!job.usage
    && typeof job.usage === 'object'
    && typeof job.createdAt === 'number'
    && typeof job.updatedAt === 'number'
}

/** Runtime boundary for the structured partial-plan failure contract. */
export function isDirectorV2PlanFailureDetail(value: unknown): value is DirectorV2PlanFailureDetail {
  if (!value || typeof value !== 'object') return false
  const detail = value as Record<string, unknown>
  const resume = detail.resume as Record<string, unknown> | undefined
  return detail.code === 'director_plan_incomplete'
    && typeof detail.message === 'string'
    && isDirectorV2PlanJob(detail.job)
    && !!resume
    && resume.action === 'resume_missing'
    && resume.method === 'POST'
    && typeof resume.path === 'string'
    && detail.imagesQueued === false
}

/** Runtime boundary for the Director v2 response returned by the backend. */
export function isDirectorV2PlanResponse(value: unknown): value is DirectorV2PlanResponse {
  if (!value || typeof value !== 'object') return false
  const response = value as Record<string, unknown>
  const productionPlan = response.production_plan
  if (!productionPlan || typeof productionPlan !== 'object') return false
  const plan = productionPlan as Record<string, unknown>
  return isDirectorSkill(response.skill_type)
    && isDirectorSkill(plan.skill_type)
    && Array.isArray(response.clip_plans)
    && response.clip_plans.every(clip => {
      if (!clip || typeof clip !== 'object') return false
      const item = clip as Record<string, unknown>
      return typeof item.video_prompt === 'string' && typeof item.image_prompt === 'string'
    })
    && Array.isArray(plan.shots)
    && (response.plan_job_id === undefined || typeof response.plan_job_id === 'string')
}

// ── Director Pipeline Dashboard ──────────────────────────────────────────

export interface PipelineVideoAttempt {
  id: string
  filename: string
  created_at: number
  seed?: number | null
  prompt?: string
  model_type?: string
  resolution?: string
  video_length?: number | null
  source?: 'original' | 'regenerated' | 'studio' | 'recovered' | string
}

export interface PlannedDirectorClip {
  start?: number
  end?: number
  duration_sec?: number
  duration_frames?: number
  section_label?: string
  suggested_prompt_hint?: string
  _director_h3_source_prompt?: string
  _director_audio_plan?: Record<string, unknown>
  _director_dialogue_beats?: Array<Record<string, unknown>>
  _director_subjects_on_screen?: Array<Record<string, unknown>>
  _director_duration_sec?: number
  _director_h3_prompt_mode?: string
  _director_project_context?: string
  [key: string]: unknown
}

export interface PipelineClipState {
  index: number
  shot_id?: string
  seed?: number
  duration_seconds?: number
  planned_clip: PlannedClip | null
  image_prompt: string
  video_prompt: string
  keyframe_prompts: string[]
  window_prompts: string[]
  window_count: number
  image_prompt_pre_polish: string | null
  video_prompt_pre_polish: string | null
  window_prompts_pre_polish: string[] | null
  keyframe_prompts_pre_polish: string[] | null
  start_image_filename: string | null
  keyframe_filenames: string[]
  video_filename: string | null
  video_attempts?: PipelineVideoAttempt[]
  /** Explicit user choice. Legacy checkpoints use video_filename implicitly. */
  selected_video_filename?: string | null
  video_stale?: boolean
  tag: 'good' | 'needs_work' | null
  image_gen_time_sec: number | null
  video_gen_time_sec: number | null
  h3_references?: H3ShotReferenceManifest | null
  h3_segment_prompts?: string[]
  h3_segments?: H3SegmentState[]
  h3_prompt_validation?: 'optimized' | 'deterministic_fallback' | 'direct_video_contract' | null
  _director_h3_source_prompt?: string
  _director_audio_plan?: Record<string, unknown>
  _director_dialogue_beats?: Array<Record<string, unknown>>
  _director_subjects_on_screen?: Array<Record<string, unknown>>
  _director_h3_prompt_mode?: string
}

export interface H3SegmentState {
  index: number
  filename: string
  prompt: string
  frames: number
  seed: number
  reference_mode: 'first_frame' | 'references' | 'direct_video'
  start_image_filename?: string
  stale?: boolean
  created_at?: number
  updated_at?: number
}

export interface H3ShotReferenceManifest {
  shot_index: number
  mode: 'first_frame' | 'references' | 'direct_video'
  shot_frame: string
  image_references: string[]
  location_reference: string
  location_label: string
  requested_location_label?: string
  video_references: string[]
  audio_references: string[]
  note: string
  warnings?: string[]
  continuity_mode?: 'identity_safe_hybrid' | 'direct_text_to_video'
}

export interface PipelineLlmPass {
  pass: string
  system_prompt: string
  user_prompt?: string
  response_text: string
  thinking_text: string | null
}

export interface PipelineLlmLog {
  provider: string
  model_id: string
  passes?: PipelineLlmPass[]
  system_prompt: string
  response_text: string
  thinking_text: string | null
  planning_time_sec: number
}

export type PipelineRepairStatus =
  | 'queued'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'interrupted'

export interface PipelineRepairState {
  operation_id: string
  status: PipelineRepairStatus
  phase: 'queued' | 'images' | 'videos' | 'rejoin' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  current: number
  total: number
  clip_index: number | null
  message: string
  error: string | null
  cancel_requested?: boolean
  started_at: number
  updated_at: number
  completed_at: number | null
  result_filename: string | null
}

export interface SavedPipelineState {
  version: number
  pipeline_id: string
  created_at: number
  completed_at: number | null
  status: string
  phase?: string
  error?: string | null
  pipeline_type: string
  generation_mode?: 'image_guided' | 'direct_video'
  direct_video_master_prompt?: string
  comic_id?: string | null
  workspace?: string
  preview_clips?: Array<Record<string, unknown>>
  scene_description: string
  reference_image_path: string | null
  auto_mode: boolean
  seamless: boolean
  image_model: string
  video_model: string
  video_params?: Record<string, unknown>
  h3_reference_manifest?: H3ShotReferenceManifest[]
  h3_prompt_validation?: {
    status: 'optimized' | 'deterministic_fallback' | 'direct_video_contract'
    segments?: number
    error?: string
  } | null
  /** Effective saved behavior. Missing on legacy projects, which require images. */
  shot_image_policy?: DirectorShotImagePolicy
  shot_image_guidance?: DirectorShotImageGuidance
  llm_log: PipelineLlmLog | null
  clips: PipelineClipState[]
  planned_clips?: PlannedDirectorClip[]
  clip_plans?: Array<Record<string, unknown>>
  character_ref_paths?: string[]
  location_ref_paths?: string[]
  image_loras?: Record<string, unknown>
  video_loras?: Record<string, unknown>
  queue_source?: 'clips' | 'clip_plans' | 'planned'
  output_files: string[]
  final_output_filename?: string
  prompt_generation_time_sec?: number | null
  image_generation_time_sec?: number | null
  video_generation_time_sec?: number | null
  assembly_time_sec?: number | null
  assembly_count?: number
  assembled_at?: number | null
  total_time_sec: number | null
  repair?: PipelineRepairState | null
}

export interface PipelineListItem {
  id: string
  status: string
  phase?: string
  pipeline_type: string
  generation_mode?: 'image_guided' | 'direct_video'
  comic_id?: string | null
  created_at: number
  clip_count: number
  output_count: number
  scene_description: string
  workspace: string
  error?: string | null
  repair_status?: PipelineRepairStatus | null
}
