import { Check } from 'lucide-react'
import { resolveResolution } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { AspectRatio, ModelOptions, ResolutionPreset } from '../../types'
import { button, input } from './storyLabChrome'
import { STORY_VIDEO_ASPECTS, STORY_VIDEO_RESOLUTIONS } from './storyLabVideoFormat'

export function StoryVideoFormatControls({
  videoModel,
  resolution,
  aspectRatio,
  options,
  disabled,
  inherited,
  adjusted,
  onChange,
}: {
  videoModel: string
  resolution: ResolutionPreset
  aspectRatio: AspectRatio
  options: ModelOptions | null
  disabled: boolean
  inherited: boolean
  adjusted: boolean
  onChange: (resolution: ResolutionPreset, aspectRatio: AspectRatio) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const modelOrder = (options?.resolution_preset_order || [])
    .filter(preset => preset !== 'auto' && (preset !== '768p' || videoModel === 'minimax_h3_legacy'))
  const availablePresets = modelOrder.length > 0
    ? modelOrder
    : STORY_VIDEO_RESOLUTIONS
  const visiblePresets = availablePresets.includes(resolution)
    ? availablePresets
    : [resolution, ...availablePresets].filter(preset => preset !== 'auto')
  const outputSize = resolveResolution(options, resolution, aspectRatio)
  const selectedConfig = options?.resolution_presets?.[resolution]
  const aspectLabel = aspectRatio === '9:16' ? t('videoFormat.portrait') : t('videoFormat.landscape')

  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2 sm:col-span-2">
      <div className="grid gap-2 sm:grid-cols-2">
        <label className="block text-[10px] text-text-muted">{t('videoFormat.resolution')}
          <select
            className={`${input} mt-1`}
            value={resolution}
            disabled={disabled}
            onChange={event => onChange(event.target.value as ResolutionPreset, aspectRatio)}
          >
            {visiblePresets.map(preset => (
              <option key={preset} value={preset}>
                {options?.resolution_presets?.[preset]?.label || preset}
              </option>
            ))}
          </select>
        </label>
        <div>
          <span className="block text-[10px] text-text-muted">{t('videoFormat.screenFormat')}</span>
          <div className="mt-1 grid grid-cols-2 gap-1.5">
            {STORY_VIDEO_ASPECTS.map(option => (
              <button
                key={option.value}
                type="button"
                disabled={disabled}
                aria-pressed={aspectRatio === option.value}
                onClick={() => onChange(resolution, option.value)}
                className={`${button} min-h-12 flex-col ${aspectRatio === option.value ? 'border-2 border-accent-blue bg-accent-blue/15 text-text-primary ring-1 ring-accent-blue/30' : ''}`}
              >
                <span className="flex items-center gap-1">{aspectRatio === option.value && <Check size={11} />} {option.value === '9:16' ? t('videoFormat.portrait') : t('videoFormat.landscape')}</span>
                <span className="text-[9px] text-text-muted">{option.value === '9:16' ? t('videoFormat.portraitDetail') : t('videoFormat.landscapeDetail')}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="rounded-md border border-accent-blue/35 bg-accent-blue/10 px-2.5 py-2">
        <p className="text-[9px] uppercase tracking-wide text-accent-blue">{t('videoFormat.selected')}</p>
        <p className="mt-0.5 text-[11px] font-semibold text-text-primary">
          {aspectLabel} · {aspectRatio} · {resolution} · {outputSize}
        </p>
      </div>
      {inherited ? (
        <p className="text-[9px] leading-relaxed text-emerald-300">
          {t('videoFormat.inherited')}
        </p>
      ) : disabled ? (
        <p className="text-[9px] leading-relaxed text-text-muted">
          {t('videoFormat.checking')}
        </p>
      ) : null}
      {adjusted && (
        <p className="text-[9px] leading-relaxed text-amber-300">
          {t('videoFormat.adjusted')}
        </p>
      )}
      {selectedConfig?.hint && (
        <p className={`text-[9px] leading-relaxed ${selectedConfig.experimental ? 'text-amber-300' : 'text-text-muted'}`}>
          {selectedConfig.hint}
        </p>
      )}
    </div>
  )
}
