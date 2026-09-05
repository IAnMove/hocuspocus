import { useState, useEffect } from 'react'
import { Play, AlertTriangle } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { splitPromptSchedule } from '../../lib/promptScheduler'
import { newUserGenerationContext } from '../../features/studio/generationProvenance'

export function GenerateButton() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const jobs = useStore(s => s.jobs)
  const startGeneration = useStore(s => s.startGeneration)
  const setSidebarOpen = useStore(s => s.setSidebarOpen)
  const [cooldown, setCooldown] = useState(false)

  // Check if i2v-only model needs a start image. Video mode only: edit
  // sub-modes supply their own source media (Recast runs the i2v-only
  // SCAIL-2 against a source video + reference image, no start image).
  const generationMode = useStore(s => s.generationMode)
  const isI2vOnly = useStore(s => s.modelOptions?.i2v_class && !s.modelOptions?.t2v_class)
  const isOmniReference = useStore(s => s.modelOptions?.omni_reference === true)
  const hasOmniVisualReference = useStore(s =>
    s.params.minimax_h3_references?.some(
      reference => reference.type === 'image' || reference.type === 'video',
    ) === true,
  )
  const hasStartImage = useStore(s => !!(s.startImage || s.params.image_start))
  const needsImage = generationMode === 'video' && isI2vOnly && !isOmniReference && !hasStartImage
  const needsReference = generationMode === 'video' && isOmniReference
    && !hasOmniVisualReference
  const editSubMode = useStore(s => s.editSubMode)
  const editVideoPath = useStore(s => s.editVideoPath)
  const outpaintVideoBox = useStore(s => s.outpaintVideoBox)
  const isOutpaint = generationMode === 'avatar' && editSubMode === 'outpaint'
  const needsOutpaintSource = isOutpaint && !editVideoPath
  const hasOutpaintArea = (
    outpaintVideoBox.x > 0.0005
    || outpaintVideoBox.y > 0.0005
    || outpaintVideoBox.x + outpaintVideoBox.w < 0.9995
    || outpaintVideoBox.y + outpaintVideoBox.h < 0.9995
  )
  const needsOutpaintArea = isOutpaint && !!editVideoPath && !hasOutpaintArea
  const promptSchedulerEnabled = useStore(s => s.promptSchedulerEnabled)
  const imageMode = useStore(s => s.params.image_mode)
  const prompt = useStore(s => s.params.prompt)
  const schedulerApplies = promptSchedulerEnabled && generationMode === 'video' && imageMode === 0
  const scheduledVideoCount = schedulerApplies ? splitPromptSchedule(prompt).length : 0
  const needsScheduledPrompts = schedulerApplies && scheduledVideoCount === 0
  const blocked = needsImage || needsReference || needsOutpaintSource || needsOutpaintArea || needsScheduledPrompts

  // Brief gray flash after clicking
  useEffect(() => {
    if (!cooldown) return
    const timer = setTimeout(() => setCooldown(false), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const handleClick = () => {
    if (blocked) return
    setCooldown(true)
    startGeneration(undefined, newUserGenerationContext())
    setSidebarOpen(false)
  }

  const queueCount = jobs.length

  if (blocked) {
    const label = needsImage
      ? t('generate.needImage')
      : needsReference
        ? t('generate.needReference')
      : needsOutpaintSource
        ? t('generate.needSource')
      : needsOutpaintArea
        ? t('generate.chooseCanvas')
        : t('generate.addPrompt')
    const title = needsOutpaintArea
      ? t('generate.outpaintAreaHint')
      : needsReference
        ? t('generate.referenceHint')
        : undefined
    return (
      <button
        disabled
        data-wizard-anchor="generate"
        title={title}
        className="px-4 py-2 rounded-lg flex items-center gap-1.5 bg-amber-500/20 text-indicator-warning cursor-not-allowed text-xs font-medium whitespace-nowrap"
      >
        <AlertTriangle size={13} />
        {label}
      </button>
    )
  }

  return (
    <button
      onClick={handleClick}
      data-wizard-anchor="generate"
      disabled={cooldown || needsScheduledPrompts}
      className={`px-4 py-2 rounded-lg flex items-center gap-1.5 font-medium text-xs transition-all whitespace-nowrap ${
        cooldown || needsScheduledPrompts
          ? 'bg-bg-active text-text-muted cursor-not-allowed'
          // Classic theme: bg-cta resolves to a flat accent-green.
          // HocusPocus Blue resolves to the branded blue gradient, while
          // shadow-accent-glow adds the restrained cool bloom.
          : 'bg-cta hover:brightness-110 shadow-accent-glow text-white'
      }`}
    >
      <Play size={13} fill={cooldown || needsScheduledPrompts ? 'currentColor' : 'white'} />
      {needsScheduledPrompts
        ? t('generate.addPrompts')
        : cooldown
          ? scheduledVideoCount > 1 ? t('generate.queuedCount', { count: scheduledVideoCount }) : tCommon('status.queued')
          : scheduledVideoCount > 1
            ? t('generate.queueCount', { count: scheduledVideoCount })
            : queueCount > 0 ? t('generate.goCount', { count: queueCount }) : tCommon('actions.generate')}
    </button>
  )
}
