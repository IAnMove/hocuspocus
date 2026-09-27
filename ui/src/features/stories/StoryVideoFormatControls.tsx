import { AspectRatioGrid } from '../../components/Sidebar/AspectRatioGrid'
import { ResolutionPresets } from '../../components/Sidebar/ResolutionPresets'
import { resolveResolution } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { AspectRatio, ModelOptions, ResolutionPreset } from '../../types'
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
  const aspectLabel = aspectRatio === '9:16' ? t('videoFormat.portrait') : t('videoFormat.landscape')

  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2 sm:col-span-2">
      {/* The same selectors as Studio; this is Story Lab's shared format. */}
      <ResolutionPresets
        value={resolution}
        onChange={preset => onChange(preset, aspectRatio)}
        options={options}
        presets={visiblePresets}
        disabled={disabled}
      />
      <AspectRatioGrid
        value={aspectRatio}
        onChange={ratio => onChange(resolution, ratio)}
        ratios={STORY_VIDEO_ASPECTS.map(option => option.value)}
        disabled={disabled}
      />
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
    </div>
  )
}
