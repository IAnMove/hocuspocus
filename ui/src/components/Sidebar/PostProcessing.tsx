import { useFieldIds } from '../common/fieldIds'
import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Mic } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import * as api from '../../api/client'
import type { ApiOutput } from '../../api/outputs'
import { catalogItemToOutput, voiceRefFromOutput } from '../../features/asset-picker'
import { useWangpProcessors } from './useWangpProcessors'
import { WangpProcessorOptions } from './WangpProcessorOptions'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'

const baseOptions = [
  { value: '', label: 'None' },
  { value: 'lanczos1.5', label: 'Lanczos 1.5x' },
  { value: 'lanczos2', label: 'Lanczos 2x' },
]

const vaeOptions = [
  { value: 'vae1', label: 'VAE 1x (Refine)' },
  { value: 'vae2', label: 'VAE 2x' },
]

// FlashVSR (DiT super-resolution) spatial upsampling — ported from upstream
// Wan2GP. These values route to the FlashVSR bridge in wgp.py's
// perform_spatial_upsampling(); the model auto-downloads (~GB) on first use.
// "Two Pass" = higher quality, ~2x slower.
const flashvsrOptions = [
  { value: 'flashvsr2', label: 'FlashVSR 2x' },
  { value: 'flashvsr3', label: 'FlashVSR 3x' },
  { value: 'flashvsr4', label: 'FlashVSR 4x' },
  { value: 'flashvsr2pass2', label: 'FlashVSR Two Pass 2x' },
  { value: 'flashvsr2pass4', label: 'FlashVSR Two Pass 4x' },
]

export function PostProcessing() {
  const fieldIds = useFieldIds()

  const { t } = useUiTranslation('studio')
  const [open, setOpen] = useState(false)
  const processors = useWangpProcessors()
  const temporal = useStore(s => s.params.temporal_upsampling || '')
  const setParam = useStore(s => s.setParam)
  const spatialUpsampling = useStore(s => s.spatialUpsampling)
  const setSpatialUpsampling = useStore(s => s.setSpatialUpsampling)
  const filmGrainIntensity = useStore(s => s.filmGrainIntensity)
  const setFilmGrainIntensity = useStore(s => s.setFilmGrainIntensity)
  const filmGrainSaturation = useStore(s => s.filmGrainSaturation)
  const setFilmGrainSaturation = useStore(s => s.setFilmGrainSaturation)
  // Voice clone (SeedVC) — postprocessing voice replacement on the
  // finished video. Only shown for video generation modes (the audio-only
  // generation modes have their own voice cloning paths built into the
  // model handlers themselves, e.g. Scenema's per-character voice refs).
  const voiceCloneEnabled = useStore(s => s.voiceCloneEnabled)
  const setVoiceCloneEnabled = useStore(s => s.setVoiceCloneEnabled)
  const voiceCloneMode = useStore(s => s.voiceCloneMode)
  const setVoiceCloneMode = useStore(s => s.setVoiceCloneMode)
  const voiceCloneRefs = useStore(s => s.voiceCloneRefs)
  const setVoiceCloneRef = useStore(s => s.setVoiceCloneRef)
  const generationMode = useStore(s => s.generationMode)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const showVoiceClone = generationMode === 'video' || generationMode === 'avatar'
  const [voiceItems, setVoiceItems] = useState<ApiOutput[]>([])

  useEffect(() => {
    if (!showVoiceClone || !voiceCloneEnabled) return
    const controller = new AbortController()
    api.fetchAssets({ workspace: activeWorkspace, limit: 100, signal: controller.signal })
      .then(result => {
        if (controller.signal.aborted) return
        setVoiceItems(
          result.assets
            .filter(asset => asset.kind === 'audio' || asset.kind === 'video')
            .map(asset => catalogItemToOutput(asset, activeWorkspace))
            .filter((item): item is ApiOutput => Boolean(item)),
        )
      })
      .catch(error => {
        if (!controller.signal.aborted) console.error('Voice catalog failed:', error)
      })
    return () => controller.abort()
  }, [showVoiceClone, voiceCloneEnabled, activeWorkspace])
  // Compute showVae as a primitive boolean directly in the selector to avoid
  // unstable array references that cause infinite re-renders (React error #185)
  const showVae = useStore(s => {
    const modes = s.modelOptions?.vae_upsampler_modes
    if (!modes?.length) return false
    const effectiveMode = s.generationMode === 'image' ? 1 : s.params.image_mode
    return modes.includes(effectiveMode)
  })

  const upsamplingOptions = useMemo(
    () => [...baseOptions, ...flashvsrOptions, ...(showVae ? vaeOptions : [])],
    [showVae],
  )

  const hasVoiceClone = voiceCloneEnabled && voiceCloneRefs.some(r => r && r.path)
  const hasAny = spatialUpsampling !== '' || temporal !== '' || filmGrainIntensity > 0 || hasVoiceClone

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-[11px] text-text-muted uppercase tracking-wider w-full hover:text-text-primary transition-colors"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <span className="flex-1 text-left">{t('post.title')}</span>
        {hasAny && <span className="w-1.5 h-1.5 rounded-full bg-accent-blue" />}
      </button>

      {open && (
        <div className="mt-3 space-y-4">
          {generationMode !== 'image' && <label className="block text-xs">{t('wangp.interpolation')}
            <select aria-label={t('wangp.interpolation')} className="w-full bg-bg-tertiary rounded-lg p-2" value={temporal} onChange={event => setParam('temporal_upsampling', event.target.value)}>
              <option value="">{t('chrome.none')}</option>
              {processors.filter(option => option.kind === 'temporal').map(option => <option key={option.value} value={option.value} disabled={!option.enabled}>{option.label}{option.reason ? ` (${option.reason})` : ''}</option>)}
            </select>
          </label>}
          {/* Spatial Upsampling */}
          <div>
            <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
              {t('post.spatial')}
            </label>
            <select aria-label={t('post.spatial')} id={fieldIds('f0')}
              value={spatialUpsampling}
              onChange={e => setSpatialUpsampling(e.target.value)}
              className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
            >
              {processors.filter(option => option.kind === 'spatial' && option.media.includes(generationMode === 'image' ? 'image' : 'video')).map(option => <option key={option.value} value={option.value} disabled={!option.enabled}>{option.label}{option.reason ? ` (${option.reason})` : ''}</option>)}
              {upsamplingOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.value === '' ? t('chrome.none') : opt.label}</option>
              ))}
            </select>
          </div>

          <WangpProcessorOptions processor={processors.find(option => option.value === spatialUpsampling)} />
          {/* Film Grain Intensity */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label htmlFor={fieldIds('f1')} className="text-[11px] text-text-muted uppercase tracking-wider">{t('post.grainIntensity')}</label>
              <span className="text-xs text-text-secondary">{filmGrainIntensity.toFixed(2)}</span>
            </div>
            <input aria-label={t('post.grainIntensity')} id={fieldIds('f1')}
              type="range"
              min={0}
              max={1}
              step={0.01}
              value={filmGrainIntensity}
              onChange={e => setFilmGrainIntensity(parseFloat(e.target.value))}
            />
          </div>

          {/* Film Grain Saturation */}
          {filmGrainIntensity > 0 && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label htmlFor={fieldIds('f2')} className="text-[11px] text-text-muted uppercase tracking-wider">{t('post.grainSaturation')}</label>
                <span className="text-xs text-text-secondary">{filmGrainSaturation.toFixed(2)}</span>
              </div>
              <input aria-label={t('post.grainSaturation')} id={fieldIds('f2')}
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={filmGrainSaturation}
                onChange={e => setFilmGrainSaturation(parseFloat(e.target.value))}
              />
            </div>
          )}

          {/* Voice Clone (SeedVC) — only for video / avatar modes.
              Replaces 1 or 2 voices in the generated video's audio
              with user-supplied reference voice(s). Backend pipeline:
              app/postprocessing/voice_clone.py. */}
          {showVoiceClone && (
            <div className="border-t border-border pt-3 space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-[11px] text-text-muted uppercase tracking-wider flex items-center gap-1.5">
                  <Mic size={11} /> {t('post.voiceClone')}
                </label>
                <button
                  onClick={() => setVoiceCloneEnabled(!voiceCloneEnabled)}
                  className={`relative w-9 h-5 rounded-full transition-colors ${
                    voiceCloneEnabled ? 'bg-accent-blue' : 'bg-bg-tertiary border border-border'
                  }`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white border border-border transition-transform ${
                    voiceCloneEnabled ? 'translate-x-4' : ''
                  }`} />
                </button>
              </div>
              {voiceCloneEnabled && (
                <>
                  {/* Mode selector */}
                  <div className="flex gap-1.5 text-xs">
                    <button
                      onClick={() => setVoiceCloneMode('single')}
                      className={`flex-1 py-1.5 rounded-md border transition-colors ${
                        voiceCloneMode === 'single'
                          ? 'bg-accent-blue/10 border-accent-blue text-text-primary'
                          : 'bg-bg-tertiary border-border text-text-secondary hover:text-text-primary'
                      }`}
                    >
                      {t('tools.singleVoice')}
                    </button>
                    <button
                      onClick={() => setVoiceCloneMode('two')}
                      className={`flex-1 py-1.5 rounded-md border transition-colors ${
                        voiceCloneMode === 'two'
                          ? 'bg-accent-blue/10 border-accent-blue text-text-primary'
                          : 'bg-bg-tertiary border-border text-text-secondary hover:text-text-primary'
                      }`}
                    >
                      {t('tools.twoVoices')}
                    </button>
                  </div>
                  <p className="text-[10px] text-text-muted leading-snug">
                    {voiceCloneMode === 'single'
                      ? t('post.singleHint')
                      : t('post.twoHint')}
                  </p>

                  {/* Voice reference upload(s) */}
                  {[0, ...(voiceCloneMode === 'two' ? [1] : [])].map(idx => {
                    const ref = voiceCloneRefs[idx]
                    const label = voiceCloneMode === 'two' ? (idx === 0 ? t('tools.voiceA') : t('tools.voiceB')) : t('tools.referenceVoice')
                    const value = ref?.path
                      ? { name: ref.filename, type: 'audio' as const, mode: null, size: 0, created_at: 0, url: '', thumbnail_url: '' }
                      : undefined
                    return (
                      <div key={idx}>
                        <AssetInput
                          label={label}
                          placeholder={t('tools.uploadSample', { label: label.toLowerCase() })}
                          items={voiceItems}
                          value={value}
                          accept="audio/*,video/*"
                          optional
                          constraints={{ kinds: ['audio', 'video'], maxCount: 1, optional: true }}
                          onChoose={item => setVoiceCloneRef(idx, item ? voiceRefFromOutput(item, activeWorkspace) : null)}
                        />
                        {ref?.path && (
                          <div className="mt-1 flex items-center gap-2 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5">
                            <Mic size={12} className="text-accent-blue shrink-0" />
                            <span className="flex-1 min-w-0 truncate text-[11px] text-text-primary">{ref.filename}</span>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
