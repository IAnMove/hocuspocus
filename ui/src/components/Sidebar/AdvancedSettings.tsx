import { useState, useEffect, useRef } from 'react'
import { X, Save, Trash2, FolderOpen, SlidersHorizontal } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { PostProcessing } from './PostProcessing'
import { ControlVideoSection } from './ControlVideoSection'
import { LoraSelector } from '../SettingsDrawer/LoraSelector'
import { ResolutionPresets } from './ResolutionPresets'
import { AspectRatioGrid } from './AspectRatioGrid'
import { WindowSettings } from './DurationSlider'
import type { GenerateParams } from '../../types'

function PresetManager() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const presets = useStore(s => s.presets)
  const loadPresets = useStore(s => s.loadPresets)
  const savePreset = useStore(s => s.savePreset)
  const loadPresetFn = useStore(s => s.loadPreset)
  const deletePreset = useStore(s => s.deletePreset)
  const generationMode = useStore(s => s.generationMode)
  const currentModel = useStore(s => s.params.model_type)
  const [saveName, setSaveName] = useState('')
  const [showSave, setShowSave] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  useEffect(() => { loadPresets() }, [loadPresets])

  const modePresets = presets.filter(p => p.mode === generationMode && p.model_type === currentModel)

  const handleSave = () => {
    if (!saveName.trim()) return
    savePreset(saveName.trim())
    setSaveName('')
    setShowSave(false)
  }

  const handleDelete = (id: string) => {
    if (confirmDelete === id) {
      deletePreset(id)
      setConfirmDelete(null)
    } else {
      setConfirmDelete(id)
      setTimeout(() => setConfirmDelete(null), 3000)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.presets')}</label>
        <button
          onClick={() => setShowSave(!showSave)}
          className="text-[10px] text-accent-blue hover:text-accent-blue-hover flex items-center gap-0.5"
        >
          <Save size={10} /> {t('advanced.saveCurrent')}
        </button>
      </div>

      {showSave && (
        <div className="flex gap-1.5 mb-2">
          <input
            type="text"
            value={saveName}
            onChange={e => setSaveName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSave()}
            placeholder={t('advanced.presetName')}
            className="flex-1 bg-bg-tertiary border border-border rounded px-2 py-1 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
            autoFocus
          />
          <button
            onClick={handleSave}
            disabled={!saveName.trim()}
            className="px-2 py-1 text-xs bg-accent-blue text-white rounded hover:bg-accent-blue-hover disabled:opacity-50"
          >
            {tCommon('actions.save')}
          </button>
        </div>
      )}

      {modePresets.length > 0 ? (
        <div className="space-y-1 max-h-[120px] overflow-y-auto">
          {modePresets.map(p => (
            <div key={p.id} className="flex items-center gap-1.5 group">
              <button
                onClick={() => loadPresetFn(p)}
                className="flex-1 text-left px-2 py-1.5 rounded text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors truncate flex items-center gap-1.5"
                title={t('advanced.loraCount', { name: p.name, count: p.activated_loras.length, model: p.model_type })}
              >
                <FolderOpen size={10} className="shrink-0 text-text-muted" />
                <span className="truncate">{p.name}</span>
              </button>
              <button
                onClick={() => handleDelete(p.id)}
                className={`p-1 rounded transition-colors shrink-0 ${
                  confirmDelete === p.id
                    ? 'text-red-400 bg-red-500/20'
                    : 'text-text-muted opacity-0 group-hover:opacity-100 hover:text-red-400'
                }`}
              >
                <Trash2 size={10} />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[10px] text-text-muted">{t('advanced.noPresets', { mode: generationMode })}</p>
      )}
    </div>
  )
}

/** Active advanced features as human-readable labels. Drives the badge
 *  count AND its hover tooltip, so a surprising number names its source
 *  instead of sending the user hunting through every section. */
function useAdvancedActiveItems(): string[] {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const modelOptions = useStore(s => s.modelOptions)
  const spatialUpsampling = useStore(s => s.spatialUpsampling)
  const filmGrainIntensity = useStore(s => s.filmGrainIntensity)
  const generationMode = useStore(s => s.generationMode)
  const editSubMode = useStore(s => s.editSubMode)
  const isScailEdit = (
    generationMode === 'avatar'
    && (editSubMode === 'recast' || editSubMode === 'restyle')
  )
  const isScailHq = isScailEdit && params.model_type === 'scail2_14B'

  const items: string[] = []
  if (params.seed !== -1) items.push(t('advanced.active.seed', { seed: params.seed }))
  if (params.minimax_h3_turbo_mode) items.push(t('advanced.active.h3Turbo'))
  if (params.skip_steps_cache_type === 'first_block') {
    items.push(t('advanced.active.h3Cache', { value: params.skip_steps_multiplier ?? 0.08 }))
  }
  if (
    modelOptions?.sliding_window_auto_prompt_pacing === true
    && params.minimax_h3_window_storyboard === false
  ) items.push(t('advanced.active.windowOff'))
  if (
    (params.negative_prompt?.length ?? 0) > 0
    && (!isScailEdit || isScailHq)
  ) items.push(t('advanced.active.negative'))
  for (const l of params.activated_loras) items.push(t('advanced.active.lora', { name: l.replace(/\.(safetensors|sft)$/i, '') }))
  if (!isScailEdit && spatialUpsampling) items.push(t('advanced.active.upscaling', { method: spatialUpsampling }))
  if (!isScailEdit && filmGrainIntensity > 0) items.push(t('advanced.active.filmGrain'))
  if (!isScailEdit && (params.self_refiner_setting ?? 0) > 0) items.push(t('advanced.active.selfRefiner'))
  if (
    modelOptions?.minimax_h3_text_encoder_choices?.length
    && params.minimax_h3_text_encoder
    && params.minimax_h3_text_encoder !== modelOptions.minimax_h3_text_encoder_default
  ) {
    const selected = modelOptions.minimax_h3_text_encoder_choices.find(
      choice => choice.value === params.minimax_h3_text_encoder
    )
    items.push(t('advanced.active.encoder', { name: selected?.label || params.minimax_h3_text_encoder }))
  }
  // injection_strength only matters when injected frames actually exist.
  // The persisted snapshot strips image_refs (file paths are ephemeral)
  // but kept the strength value — counting it alone produced a ghost
  // badge with nothing visibly active in the panel.
  const refCount = Array.isArray(params.image_refs) ? params.image_refs.length : (params.image_refs ? 1 : 0)
  if (!isScailEdit && params.injection_strength != null && params.injection_strength !== 1.0 && refCount > 0) items.push(t('advanced.active.injection'))
  if (params.preserve_source_style === false) items.push(t('advanced.active.restyleAllowed'))
  if (params.image_fit_mode === 'crop') items.push(t('advanced.active.crop'))
  // Process letter codes persist by design (the dropdown remembers the
  // user's choice across sessions), but their REQUIRED inputs are
  // ephemeral and stripped from persistence: frames injection ("F")
  // needs image refs, control-video letters ("V") need a guide file.
  // A remembered choice with no input does nothing at generation time,
  // so it must not count — this was the refresh-surviving ghost. Strip only
  // a TRAILING "T" (the extend-alignment flag); an internal "T" is a real
  // process letter (depth_temporal: TVG/PTVG/TEVG) and must survive.
  const vptVisible = (params.video_prompt_type || '').replace(/T$/, '')
  if (!isScailEdit && modelOptions?.guide_custom_choices && vptVisible) {
    const effective = vptVisible.includes('F')
      ? refCount > 0
      : vptVisible.includes('V')
        ? !!params.video_guide
        : true
    if (effective) items.push(t('advanced.active.process', { code: vptVisible }))
  }
  return items
}

export function AdvancedSettings() {
  const { t } = useUiTranslation('studio')
  const [open, setOpen] = useState(false)
  const params = useStore(s => s.params)
  const setParam = useStore(s => s.setParam)
  const modelOptions = useStore(s => s.modelOptions)
  const generationMode = useStore(s => s.generationMode)
  const editSubMode = useStore(s => s.editSubMode)
  const audioSubMode = useStore(s => s.audioSubMode)
  const isAudio = generationMode === 'audio'
  const isSfx = isAudio && audioSubMode === 'sfx'
  const isAudioOnly = modelOptions?.audio_only === true || isSfx
  const isVideo = generationMode === 'video'
  const isAvatar = generationMode === 'avatar'
  const isOutpaint = isAvatar && editSubMode === 'outpaint'
  const isRecast = isAvatar && editSubMode === 'recast'
  const isRepaint = isAvatar && editSubMode === 'restyle'
  const isScailEdit = isRecast || isRepaint
  const scailModelType = String(params.model_type || '')
  const isScailFast = (
    isScailEdit
    && (
      scailModelType === 'scail2_14B_fast'
      || scailModelType === 'scail2_14B_recast_fast'
    )
  )
  const isScailHq = isScailEdit && scailModelType === 'scail2_14B'
  const h3TurboMode = (
    params.minimax_h3_turbo_mode === true
    && modelOptions?.minimax_h3_turbo != null
  )
  const showInferenceSteps = (
    !isAudioOnly
    && (isScailEdit || !modelOptions?.lock_inference_steps)
  )
  const showGuidanceScale = (
    !isAudioOnly
    && (
      isScailEdit
        ? isScailHq
        : !modelOptions?.lock_guidance_scale
    )
  )
  const showNegativePrompt = (
    !modelOptions?.no_negative_prompt
    && (!isScailEdit || isScailHq)
  )
  const hasStartImage = useStore(s => !!(s.startImage || s.params.image_start))
  const hasEndImage = useStore(s => !!(s.endImage || s.params.image_end))
  const hasImageRefs = useStore(s => {
    const refs = s.params.image_refs
    return refs && refs.length > 0
  })
  const durationSeconds = useStore(s => s.durationSeconds)
  const setDurationSeconds = useStore(s => s.setDurationSeconds)
  const panelRef = useRef<HTMLDivElement>(null)
  const advancedItems = useAdvancedActiveItems()
  const advancedCount = advancedItems.length

  // Close on escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  return (
    <>
      {/* Trigger button */}
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors border ${
          open ? 'border-accent-blue text-accent-blue' : 'border-border text-text-secondary hover:text-text-primary hover:border-border-light'
        }`}
      >
        <SlidersHorizontal size={13} />
        <span className="hidden md:inline">{t('chrome.advanced')}</span>
        {advancedCount > 0 && (
          <span
            title={advancedItems.join('\n')}
            className="min-w-[16px] h-4 rounded-full bg-accent-blue text-white text-[9px] font-bold flex items-center justify-center px-1"
          >
            {advancedCount}
          </span>
        )}
      </button>

      {/* Popup overlay — always mounted to preserve state (frames injection, etc.) */}
      {open && <div className="fixed inset-0 bg-black/30 z-50" onClick={() => setOpen(false)} />}
      <div
        ref={panelRef}
        className={`fixed top-0 h-full bg-bg-secondary border-r border-border z-50 flex flex-col shadow-2xl overflow-hidden transition-transform duration-200
          left-0 w-full md:left-[420px] md:w-[380px] md:max-w-[90vw] ${
          open ? 'translate-x-0' : '-translate-x-full md:-translate-x-[800px] pointer-events-none'
        }`}
        style={{ maxHeight: '100vh' }}
      >
            {/* Header */}
            <div className="px-4 py-3 border-b border-border flex items-center justify-between shrink-0">
              <span className="text-sm font-semibold text-text-primary">{t('advanced.title')}</span>
              <button onClick={() => setOpen(false)} className="p-1 rounded-lg hover:bg-bg-hover text-text-secondary">
                <X size={16} />
              </button>
            </div>

            {/* Scrollable content */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
              {/* Recast/Repaint own their output-quality profiles in the main
                  workflow. Their dedicated endpoints also choose adaptive
                  windows, so generic controls would be misleading here. */}
              {!isAudio && !isScailEdit && (
                <>
                  {!isOutpaint && !modelOptions?.hide_resolution_presets && <ResolutionPresets />}
                  {!isAvatar && <AspectRatioGrid />}
                </>
              )}

              {/* The Qwen conditioner is shared by every H3 transformer.
                  Expose it once here instead of multiplying model entries. */}
              {modelOptions?.minimax_h3_text_encoder_choices?.length ? (
                <div>
                  <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
                    {t('advanced.h3Encoder')}
                  </label>
                  <select
                    value={params.minimax_h3_text_encoder || modelOptions.minimax_h3_text_encoder_default || modelOptions.minimax_h3_text_encoder_choices[0]?.value}
                    onChange={e => setParam('minimax_h3_text_encoder', e.target.value as GenerateParams['minimax_h3_text_encoder'])}
                    className="w-full bg-bg-tertiary border border-border rounded px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
                  >
                    {modelOptions.minimax_h3_text_encoder_choices.map(choice => (
                      <option key={choice.value} value={choice.value}>
                        {choice.label}
                      </option>
                    ))}
                  </select>
                  <p className="text-[9px] text-text-muted mt-1">
                    {modelOptions.minimax_h3_text_encoder_choices.find(
                      choice => choice.value === (params.minimax_h3_text_encoder || modelOptions.minimax_h3_text_encoder_default)
                    )?.size_hint || t('advanced.encoderReload')}
                  </p>
                </div>
              ) : null}

              {modelOptions?.first_block_cache && (
                <div className="space-y-2 p-2.5 bg-bg-tertiary/40 rounded-lg border border-border/60">
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={params.skip_steps_cache_type === 'first_block'}
                      onChange={e => {
                        setParam(
                          'skip_steps_cache_type',
                          e.target.checked ? 'first_block' : '',
                        )
                        if (e.target.checked && params.skip_steps_multiplier == null) {
                          setParam(
                            'skip_steps_multiplier',
                            modelOptions.default_skip_steps_multiplier ?? 0.08,
                          )
                        }
                      }}
                      className="accent-accent-blue"
                    />
                    <span className="text-[11px] text-text-muted uppercase tracking-wider group-hover:text-text-secondary transition-colors">
                      {t('advanced.firstBlockCache')}
                    </span>
                    <span className="text-[9px] text-amber-300/90 border border-amber-400/30 rounded px-1 py-0.5">
                      {t('chrome.experimental')}
                    </span>
                  </label>
                  {params.skip_steps_cache_type === 'first_block' && (
                    <div className="space-y-2 pl-1 border-l border-border ml-1">
                      <div>
                        <label className="text-[10px] text-text-muted block mb-1">
                          {modelOptions.skip_steps_multiplier_label || t('advanced.cacheThreshold')}
                        </label>
                        <select
                          value={params.skip_steps_multiplier ?? modelOptions.default_skip_steps_multiplier ?? 0.08}
                          onChange={e => setParam('skip_steps_multiplier', Number(e.target.value))}
                          className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
                        >
                          {(modelOptions.skip_steps_multiplier_choices || []).map(([label, value]) => (
                            <option key={value} value={value}>{label}</option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.warmup')}</label>
                          <span className="text-[10px] text-text-secondary">
                            {params.skip_steps_start_step_perc ?? modelOptions.default_skip_steps_start_step_perc ?? 25}%
                          </span>
                        </div>
                        <input
                          type="range"
                          min={0}
                          max={75}
                          step={5}
                          value={params.skip_steps_start_step_perc ?? modelOptions.default_skip_steps_start_step_perc ?? 25}
                          onChange={e => setParam('skip_steps_start_step_perc', Number(e.target.value))}
                          className="w-full"
                        />
                      </div>
                    </div>
                  )}
                  <p className="text-[9px] text-text-muted">
                    {t('advanced.cacheHint')}
                  </p>
                </div>
              )}

              {/* Window Settings */}
              {(isVideo || (isAvatar && !isScailEdit))
                && modelOptions?.sliding_window
                && <WindowSettings />}

              {isVideo && modelOptions?.sliding_window_auto_prompt_pacing === true && (
                <div className="space-y-1">
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={params.minimax_h3_window_storyboard !== false}
                      onChange={e => setParam('minimax_h3_window_storyboard', e.target.checked)}
                      className="accent-accent-blue"
                    />
                    <span className="text-[11px] text-text-muted uppercase tracking-wider group-hover:text-text-secondary transition-colors">
                      {t('advanced.planWindows')}
                    </span>
                  </label>
                  <p className="text-[9px] text-text-muted">
                    {t('advanced.planWindowsHint')}
                  </p>
                </div>
              )}

              {/* TTS Settings */}
              {isAudioOnly && (
                <>
                  {/* Max Duration */}
                  {modelOptions?.duration_slider && (
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-[11px] text-text-muted uppercase tracking-wider">
                          {modelOptions.duration_slider.label || t('advanced.maxDuration')}
                        </label>
                        <span className="text-xs text-text-secondary">{Math.round(durationSeconds)}s</span>
                      </div>
                      <input
                        type="range"
                        min={modelOptions.duration_slider.min} max={modelOptions.duration_slider.max} step={modelOptions.duration_slider.increment}
                        value={durationSeconds}
                        onChange={e => setDurationSeconds(parseFloat(e.target.value))}
                        className="w-full"
                      />
                    </div>
                  )}

                  {/* Speaker Pause */}
                  {modelOptions?.pause_between_sentences && (
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.speakerPause')}</label>
                        <span className="text-xs text-text-secondary">{(params.pause_seconds ?? 0.5).toFixed(2)}s</span>
                      </div>
                      <input
                        type="range" min={0} max={2} step={0.05}
                        value={params.pause_seconds ?? 0.5}
                        onChange={e => setParam('pause_seconds', parseFloat(e.target.value))}
                        className="w-full"
                      />
                    </div>
                  )}

                  {/* Temperature */}
                  {modelOptions?.temperature_enabled && (
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.temperature')}</label>
                        <span className="text-xs text-text-secondary">{(params.temperature ?? 1.0).toFixed(2)}</span>
                      </div>
                      <input
                        type="range" min={0.1} max={1.5} step={0.01}
                        value={params.temperature ?? 1.0}
                        onChange={e => setParam('temperature', parseFloat(e.target.value))}
                        className="w-full"
                      />
                    </div>
                  )}

                  {/* Guidance Scale */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.guidanceCfg')}</label>
                      <span className="text-xs text-text-secondary">{(params.guidance_scale ?? 3.0).toFixed(1)}</span>
                    </div>
                    <input
                      type="range" min={1} max={20} step={0.1}
                      value={params.guidance_scale ?? 3.0}
                      onChange={e => setParam('guidance_scale', parseFloat(e.target.value))}
                      className="w-full"
                    />
                  </div>

                  {/* Auto-Split */}
                  {modelOptions?.custom_settings_def?.map(setting => (
                    <div key={setting.id}>
                      <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{setting.name}</label>
                      <input
                        type="number"
                        placeholder={t('advanced.emptyDisabled')}
                        value={String((params.custom_settings as Record<string, unknown> | undefined)?.[setting.id] ?? '')}
                        onChange={e => {
                          const val = e.target.value.trim()
                          const cs = { ...(params.custom_settings || {}) } as Record<string, unknown>
                          if (val === '') {
                            delete cs[setting.id]
                          } else {
                            cs[setting.id] = parseFloat(val)
                          }
                          setParam('custom_settings', Object.keys(cs).length > 0 ? cs : undefined)
                        }}
                        className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                      />
                      <p className="text-[10px] text-text-muted mt-1">{setting.label}</p>
                    </div>
                  ))}

                  {/* Compressor Settings — shown when Smooth Speaker Volumes is enabled */}
                  {params.tts_dynaudnorm === true && (
                    <div className="space-y-3 p-2.5 bg-bg-tertiary/50 rounded-lg border border-border/50">
                      <label className="text-[10px] text-text-muted uppercase tracking-wider block">{t('advanced.compressor')}</label>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.threshold')}</label>
                          <span className="text-[10px] text-text-secondary">{Number(params.tts_comp_threshold ?? -25)}dB</span>
                        </div>
                        <input type="range" min={-50} max={-10} step={1}
                          value={Number(params.tts_comp_threshold ?? -25)}
                          onChange={e => setParam('tts_comp_threshold', parseInt(e.target.value))}
                          className="w-full" />
                        <p className="text-[9px] text-text-muted">{t('advanced.thresholdHint')}</p>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.attack')}</label>
                          <span className="text-[10px] text-text-secondary">{Number(params.tts_comp_attack ?? 5)}ms</span>
                        </div>
                        <input type="range" min={1} max={50} step={1}
                          value={Number(params.tts_comp_attack ?? 5)}
                          onChange={e => setParam('tts_comp_attack', parseInt(e.target.value))}
                          className="w-full" />
                        <p className="text-[9px] text-text-muted">{t('advanced.attackHint')}</p>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.release')}</label>
                          <span className="text-[10px] text-text-secondary">{Number(params.tts_comp_release ?? 100)}ms</span>
                        </div>
                        <input type="range" min={20} max={500} step={10}
                          value={Number(params.tts_comp_release ?? 100)}
                          onChange={e => setParam('tts_comp_release', parseInt(e.target.value))}
                          className="w-full" />
                        <p className="text-[9px] text-text-muted">{t('advanced.releaseHint')}</p>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.makeup')}</label>
                          <span className="text-[10px] text-text-secondary">{Number(params.tts_comp_makeup ?? 4)}dB</span>
                        </div>
                        <input type="range" min={0} max={12} step={1}
                          value={Number(params.tts_comp_makeup ?? 4)}
                          onChange={e => setParam('tts_comp_makeup', parseInt(e.target.value))}
                          className="w-full" />
                        <p className="text-[9px] text-text-muted">{t('advanced.makeupHint')}</p>
                      </div>
                    </div>
                  )}
                </>
              )}

              {/* Post Processing */}
              {!isAudio && !isScailEdit && <PostProcessing />}

              {(
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.seed')}</label>
                  <button onClick={() => setParam('seed', -1)} className="text-[10px] text-accent-blue hover:text-accent-blue-hover">
                    {t('chrome.random')}
                  </button>
                </div>
                <input
                  type="number"
                  value={Number(params.seed)}
                  onChange={e => setParam('seed', Number(e.target.value))}
                  className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                  placeholder={t('advanced.seedPlaceholder')}
                />
              </div>
              ) as any /* eslint-disable-line @typescript-eslint/no-explicit-any -- preserves the legacy JSX child inference boundary. */}

              {/* Self Refiner */}
              {!isScailEdit && modelOptions?.self_refiner === true ? (
                <div>
                  <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('advanced.selfRefiner')}</label>
                  <select
                    value={params.self_refiner_setting ?? 0}
                    onChange={e => setParam('self_refiner_setting', Number(e.target.value))}
                    className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
                  >
                    <option value={0}>{t('chrome.disabled')}</option>
                    <option value={1}>{t('advanced.p1')}</option>
                    <option value={2}>{t('advanced.p2')}</option>
                  </select>
                </div>
              ) : null}

              {/* I2V style anchoring. The start frame carries much of the
                  appearance, but an explicit prompt anchor materially reduces
                  anime/comic inputs drifting toward photorealism. */}
              {isVideo && (hasStartImage || params.image_mode === 2) && (
                <div className="space-y-2">
                  <label className="block text-[10px] text-text-muted">
                    {t('advanced.startFit')}
                    <select
                      value={params.image_fit_mode === 'crop' ? 'crop' : 'contain'}
                      onChange={e => setParam('image_fit_mode', e.target.value as 'contain' | 'crop')}
                      className="mt-1 w-full rounded-lg border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:border-accent-blue focus:outline-none"
                    >
                      <option value="contain">{t('advanced.fitBars')}</option>
                      <option value="crop">{t('advanced.cropFill')}</option>
                    </select>
                  </label>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={params.preserve_source_style !== false}
                      onChange={e => setParam('preserve_source_style', e.target.checked)}
                      className="accent-accent-blue"
                    />
                    <span className="text-[11px] uppercase tracking-wider text-text-muted">
                      {t('advanced.preserveStyle')}
                    </span>
                  </label>
                  <p className="text-[9px] text-text-muted/60">
                    {t('advanced.fitHint')}
                  </p>
                </div>
              )}

              {/* Stage 2 Steps */}
              {/* Pipeline Mode Toggle — distilled LTX models only */}
              {!isScailEdit && modelOptions?.lock_inference_steps && (
                <div className="space-y-3">
                  {/* Single / 2-Stage / 3-Stage segmented control — mutually exclusive */}
                  <div>
                    <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('advanced.pipeline')}</label>
                    <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
                      <button
                        onClick={() => { setParam('progressive_pipeline', false); setParam('single_stage_pipeline', true) }}
                        className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
                          !!params.single_stage_pipeline && !params.progressive_pipeline
                            ? 'bg-bg-active text-text-primary'
                            : 'text-text-secondary hover:text-text-primary'
                        }`}
                        title={t('advanced.singleTitle')}
                      >
                        {t('advanced.single')}
                      </button>
                      <button
                        onClick={() => { setParam('progressive_pipeline', false); setParam('single_stage_pipeline', false) }}
                        className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
                          !params.progressive_pipeline && !params.single_stage_pipeline
                            ? 'bg-bg-active text-text-primary'
                            : 'text-text-secondary hover:text-text-primary'
                        }`}
                        title={t('advanced.standardTitle')}
                      >
                        {t('advanced.standard')}
                      </button>
                      <button
                        onClick={() => { setParam('progressive_pipeline', true); setParam('single_stage_pipeline', false) }}
                        className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
                          params.progressive_pipeline
                            ? 'bg-bg-active text-text-primary'
                            : 'text-text-secondary hover:text-text-primary'
                        }`}
                        title={t('advanced.progressiveTitle')}
                      >
                        {t('advanced.progressive')}
                      </button>
                    </div>
                  </div>

                  {/* Single-Stage: no extra controls — stage 1 runs at full res */}
                  {!!params.single_stage_pipeline && !params.progressive_pipeline && (
                    <div className="text-[10px] text-text-muted px-1">
                      {t('advanced.singleHint')}
                    </div>
                  )}

                  {/* Standard 2-Stage: Stage 2 steps only */}
                  {!params.progressive_pipeline && !params.single_stage_pipeline && (
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.stage2Steps')}</label>
                        <span className="text-xs text-text-secondary">{params.stage2_steps || 3}</span>
                      </div>
                      <input
                        type="range" min={2} max={7} step={1}
                        value={params.stage2_steps || 3}
                        onChange={e => setParam('stage2_steps', Number(e.target.value))}
                        className="w-full accent-accent-blue"
                      />
                      <div className="flex justify-between text-[10px] text-text-muted mt-0.5">
                        <span>{t('advanced.faster')}</span><span>{t('advanced.moreDetail')}</span>
                      </div>
                    </div>
                  )}

                  {/* Progressive 3-Stage controls */}
                  {!!params.progressive_pipeline && (
                    <div className="space-y-3 pt-1 border-t border-border/30">
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.stage1Weight')}</label>
                          <span className="text-[10px] text-text-secondary">{(params.progressive_stage1_image_weight ?? 0.7).toFixed(2)}</span>
                        </div>
                        <input type="range" min={0.3} max={1.0} step={0.05}
                          value={params.progressive_stage1_image_weight ?? 0.7}
                          onChange={e => setParam('progressive_stage1_image_weight', parseFloat(e.target.value))}
                          className="w-full accent-accent-blue" />
                        <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
                          <span>{t('advanced.moreMotion')}</span><span>{t('advanced.matchStart')}</span>
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.stage2Half')}</label>
                          <span className="text-[10px] text-text-secondary">{params.progressive_stage2_steps ?? 5}</span>
                        </div>
                        <input type="range" min={1} max={8} step={1}
                          value={params.progressive_stage2_steps ?? 5}
                          onChange={e => setParam('progressive_stage2_steps', Number(e.target.value))}
                          className="w-full accent-accent-blue" />
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.stage3Full')}</label>
                          <span className="text-[10px] text-text-secondary">{params.progressive_stage3_steps ?? 3}</span>
                        </div>
                        <input type="range" min={1} max={8} step={1}
                          value={params.progressive_stage3_steps ?? 3}
                          onChange={e => setParam('progressive_stage3_steps', Number(e.target.value))}
                          className="w-full accent-accent-blue" />
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.stage2Sigma')}</label>
                          <span className="text-[10px] text-text-secondary">{(params.progressive_stage2_sigma ?? 0.85).toFixed(2)}</span>
                        </div>
                        <input type="range" min={0.5} max={1.0} step={0.05}
                          value={params.progressive_stage2_sigma ?? 0.85}
                          onChange={e => setParam('progressive_stage2_sigma', parseFloat(e.target.value))}
                          className="w-full accent-accent-blue" />
                        <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
                          <span>{t('advanced.preserve')}</span><span>{t('advanced.regenerate')}</span>
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.stage3Sigma')}</label>
                          <span className="text-[10px] text-text-secondary">{(params.progressive_stage3_sigma ?? 0.85).toFixed(2)}</span>
                        </div>
                        <input type="range" min={0.5} max={1.0} step={0.05}
                          value={params.progressive_stage3_sigma ?? 0.85}
                          onChange={e => setParam('progressive_stage3_sigma', parseFloat(e.target.value))}
                          className="w-full accent-accent-blue" />
                        <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
                          <span>{t('advanced.preserve')}</span><span>{t('advanced.regenerate')}</span>
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <label className="text-[10px] text-text-muted">{t('advanced.stage3Weight')}</label>
                          <span className="text-[10px] text-text-secondary">{(params.progressive_stage3_image_weight ?? 0.7).toFixed(2)}</span>
                        </div>
                        <input type="range" min={0.3} max={1.0} step={0.05}
                          value={params.progressive_stage3_image_weight ?? 0.7}
                          onChange={e => setParam('progressive_stage3_image_weight', parseFloat(e.target.value))}
                          className="w-full accent-accent-blue" />
                        <div className="flex justify-between text-[9px] text-text-muted mt-0.5">
                          <span>{t('advanced.moreFreedom')}</span><span>{t('advanced.matchStart')}</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Reference Pipeline (10Eros — runs the author's published
                  ComfyUI workflow config: 9+3 eased steps, per-step CFG
                  2.0/1.5 then off, STG on blocks 14+19 for the first 4
                  steps, RF euler_ancestral). Shown only for models whose
                  def declares reference_pipeline support. */}
              {!isScailEdit && (modelOptions as Record<string, unknown> | null)?.reference_pipeline && (
                <div className="space-y-1">
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input type="checkbox"
                      checked={!!params.reference_pipeline}
                      onChange={e => setParam('reference_pipeline', e.target.checked ? true : undefined)}
                      className="accent-accent-blue" />
                    <span className="text-[11px] text-text-muted uppercase tracking-wider group-hover:text-text-secondary transition-colors">
                      {t('advanced.referencePipeline')}
                    </span>
                  </label>
                  <p className="text-[9px] text-text-muted">
                    {t('advanced.referencePipelineHint')}
                  </p>
                </div>
              )}

              {/* Dedicated SCAIL edit endpoints honor this value for both
                  Fast and HQ; other distilled models retain their lock. */}
              {showInferenceSteps && (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.inferenceSteps')}</label>
                    <input
                      type="number"
                      value={params.num_inference_steps}
                      disabled={h3TurboMode}
                      onChange={e => setParam('num_inference_steps', Number(e.target.value))}
                      className="w-16 bg-bg-tertiary border border-border rounded px-2 py-0.5 text-xs text-text-primary text-center focus:outline-none focus:border-accent-blue disabled:cursor-not-allowed disabled:opacity-50"
                    />
                  </div>
                  <input
                    type="range" min={1} max={50} step={1}
                    value={params.num_inference_steps}
                    disabled={h3TurboMode}
                    onChange={e => setParam('num_inference_steps', Number(e.target.value))}
                    className="w-full disabled:cursor-not-allowed disabled:opacity-50"
                  />
                  {h3TurboMode && (
                    <p className="text-[9px] text-text-muted mt-0.5">
                      {t('advanced.turboLock', { steps: modelOptions?.minimax_h3_turbo?.steps })}
                    </p>
                  )}
                  {isScailFast && (
                    <p className="text-[9px] text-text-muted mt-0.5">
                      {t('advanced.fastCfg')}
                    </p>
                  )}
                </div>
              )}

              {/* Guidance Scale (hidden for TTS — shown in TTS section above) */}
              {showGuidanceScale && (
                <div>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.guidanceScale')}</label>
                    <input
                      type="number"
                      value={params.guidance_scale}
                      onChange={e => setParam('guidance_scale', Number(e.target.value))}
                      step={0.1}
                      className="w-16 bg-bg-tertiary border border-border rounded px-2 py-0.5 text-xs text-text-primary text-center focus:outline-none focus:border-accent-blue"
                    />
                  </div>
                  <input
                    type="range" min={0} max={20} step={0.1}
                    value={params.guidance_scale}
                    onChange={e => setParam('guidance_scale', Number(e.target.value))}
                    className="w-full"
                  />
                </div>
              )}

              {/* LTX-2 Dev Pipeline Controls — only for models with perturbation/CFG-Star support */}
              {!isScailEdit && (modelOptions as Record<string, unknown> | null)?.perturbation && (
                <>
                  {/* STG Scale */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.stg')}</label>
                      <span className="text-xs text-text-secondary">{(params.stg_scale ?? 0) > 0 ? (params.stg_scale as number).toFixed(1) : t('chrome.off')}</span>
                    </div>
                    <input type="range" min={0} max={3} step={0.1}
                      value={params.stg_scale ?? 0}
                      onChange={e => setParam('stg_scale', parseFloat(e.target.value))}
                      className="w-full" />
                    <p className="text-[9px] text-text-muted mt-0.5">{t('advanced.stgHint')}</p>
                  </div>

                  {/* CFG Rescale */}
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.cfgRescale')}</label>
                      <span className="text-xs text-text-secondary">{(params.cfg_rescale ?? 0).toFixed(2)}</span>
                    </div>
                    <input type="range" min={0} max={1} step={0.05}
                      value={params.cfg_rescale ?? 0}
                      onChange={e => setParam('cfg_rescale', parseFloat(e.target.value))}
                      className="w-full" />
                    <p className="text-[9px] text-text-muted mt-0.5">{t('advanced.cfgRescaleHint')}</p>
                  </div>

                  {/* Gradient Estimation */}
                  <div className="space-y-1.5">
                    <label className="flex items-center gap-2 cursor-pointer group">
                      <input type="checkbox"
                        checked={!!params.use_gradient_estimation}
                        onChange={e => setParam('use_gradient_estimation', e.target.checked ? true : undefined)}
                        className="accent-accent-blue" />
                      <span className="text-[11px] text-text-muted uppercase tracking-wider group-hover:text-text-secondary transition-colors">
                        {t('advanced.gradient')}
                      </span>
                    </label>
                    {params.use_gradient_estimation && (
                      <div className="pl-1 border-l border-border ml-1 space-y-1.5">
                        <p className="text-[9px] text-accent-blue/80">{t('advanced.gradientHint')}</p>
                        <div>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-[10px] text-text-muted">{t('advanced.gamma')}</span>
                            <span className="text-[9px] text-text-muted">{(params.ge_gamma ?? 2.0).toFixed(1)}</span>
                          </div>
                          <input type="range" min={1} max={4} step={0.1}
                            value={params.ge_gamma ?? 2.0}
                            onChange={e => setParam('ge_gamma', parseFloat(e.target.value))}
                            className="w-full" />
                        </div>
                      </div>
                    )}
                  </div>
                </>
              )}

              {/* Keyframe Conditioning Mode — Start/End frames */}
              {!isScailEdit && (isVideo || isAvatar) && (hasStartImage || hasEndImage) && (
                <div>
                  <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('advanced.startEndMode')}</label>
                  <select
                    value={params.keyframe_conditioning_mode || 'replace'}
                    onChange={e => setParam('keyframe_conditioning_mode', e.target.value)}
                    className="w-full bg-bg-tertiary border border-border rounded px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
                  >
                    <option value="replace">{t('advanced.replaceDefault')}</option>
                    <option value="additive">{t('advanced.additiveSmooth')}</option>
                  </select>
                  <p className="text-[9px] text-text-muted mt-0.5">{t('advanced.replaceHint')}</p>
                </div>
              )}

              {/* Keyframe Conditioning Mode — Injected keyframes */}
              {!isScailEdit && (isVideo || isAvatar) && hasImageRefs && (
                <div>
                  <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('advanced.injectMode')}</label>
                  <select
                    value={params.keyframe_inject_mode || 'additive'}
                    onChange={e => setParam('keyframe_inject_mode', e.target.value)}
                    className="w-full bg-bg-tertiary border border-border rounded px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue"
                  >
                    <option value="additive">{t('advanced.additiveDefault')}</option>
                    <option value="replace">{t('advanced.replaceStrict')}</option>
                  </select>
                  <p className="text-[9px] text-text-muted mt-0.5">{t('advanced.injectHint')}</p>
                </div>
              )}

              {/* Negative Prompt */}
              {showNegativePrompt && (
                <div>
                  <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('advanced.negative')}</label>
                  <textarea
                    value={params.negative_prompt || ''}
                    onChange={e => setParam('negative_prompt', e.target.value)}
                    placeholder={t('advanced.negativePlaceholder')}
                    rows={2}
                    className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                    style={{ resize: 'vertical', minHeight: 48 }}
                  />
                </div>
              )}

              {/* MMAudio — video models only */}
              {isVideo && (
                <div className="space-y-2">
                  <label className="flex items-center gap-2 cursor-pointer group">
                    <input
                      type="checkbox"
                      checked={params.MMAudio_setting === 1}
                      onChange={e => setParam('MMAudio_setting', e.target.checked ? 1 : 0)}
                      className="accent-accent-blue"
                    />
                    <span className="text-[11px] text-text-muted uppercase tracking-wider group-hover:text-text-secondary transition-colors">
                      {t('advanced.mmaudio')}
                    </span>
                  </label>
                  {params.MMAudio_setting === 1 && (
                    <div className="space-y-2 pl-1 border-l border-border ml-1">
                      <div>
                        <label className="text-[10px] text-text-muted block mb-1">{t('advanced.mmaudioPrompt')}</label>
                        <input
                          type="text"
                          value={(params.MMAudio_prompt) || ''}
                          onChange={e => setParam('MMAudio_prompt', e.target.value)}
                          placeholder={t('advanced.mmaudioPromptPh')}
                          className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                        />
                      </div>
                      <div>
                        <label className="text-[10px] text-text-muted block mb-1">{t('advanced.mmaudioNeg')}</label>
                        <input
                          type="text"
                          value={(params.MMAudio_neg_prompt) || ''}
                          onChange={e => setParam('MMAudio_neg_prompt', e.target.value)}
                          placeholder={t('advanced.mmaudioNegPh')}
                          className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Presets */}
              <PresetManager />

              {/* Official Outpaint owns its stage-one-only IC-LoRA schedule. */}
              {!isOutpaint && <LoraSelector />}

              {/* Dedicated SCAIL edit endpoints own their source video,
                  edited/reference frames, masks, and process selection. */}
              {(modelOptions?.guide_preprocessing || modelOptions?.guide_custom_choices) &&
                !isScailEdit && (
                <ControlVideoSection />
              )}

              {/* Dedicated Recast/Repaint submissions create one edit job. */}
              {!isScailEdit && <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('advanced.outputCount')}</label>
                  <span className="text-xs text-text-secondary">{params.repeat_generation || 1}</span>
                </div>
                <input
                  type="range" min={1} max={10} step={1}
                  value={params.repeat_generation || 1}
                  onChange={e => setParam('repeat_generation', Number(e.target.value))}
                  className="w-full"
                />
              </div>}
            </div>
          </div>
    </>
  )
}
