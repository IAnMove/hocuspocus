import { useState, useRef } from 'react'
import { Play, AlertTriangle } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { splitPromptSchedule } from '../../lib/promptScheduler'
import { newUserGenerationContext } from '../../features/studio/generationProvenance'
import { useViggleGenerationGuard } from '../../lib/useViggleGenerationGuard'
import { isGenerationJobActive } from '../../lib/generationJobState'
import { usePlatformCapabilities } from '../../lib/usePlatformCapabilities'
import { generateBlockedCopy, isRemoteMiniMaxImage } from '../../lib/generateButtonGate'

export function GenerateButton() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const jobs = useStore(s => s.jobs)
  const startGeneration = useStore(s => s.startGeneration)
  const [submitting, setSubmitting] = useState(false)
  const [submissionError, setSubmissionError] = useState('')
  const submissionPending = useRef(false)
  const { checkingFrame, frameError, checkBeforeGenerate } = useViggleGenerationGuard()

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
  const modelType = useStore(s => s.params.model_type)
  const imageProvider = useStore(s => s.productionProfile?.image?.provider)
  const localUnavailable = usePlatformCapabilities()?.capabilities.wangp_local?.state === 'hidden'
    && !isRemoteMiniMaxImage(generationMode, modelType, imageProvider)
  const blocked = localUnavailable || needsImage || needsReference || needsOutpaintSource || needsOutpaintArea || needsScheduledPrompts

  const handleClick = async () => {
    if (blocked || submissionPending.current) return
    submissionPending.current = true
    setSubmitting(true)
    setSubmissionError('')
    try {
      if (!await checkBeforeGenerate()) return
      // Keep the visible command panel mounted through preparation/admission.
      // A click or a resolved legacy return value is not a queue receipt.
      await startGeneration(undefined, newUserGenerationContext())
    } catch (error) {
      setSubmissionError(error instanceof Error ? error.message : tCommon('status.failed'))
    } finally {
      submissionPending.current = false
      setSubmitting(false)
    }
  }

  const queueCount = jobs.filter(job => isGenerationJobActive(job.status)).length

  if (blocked) {
    const { label, title } = generateBlockedCopy({
      localUnavailable, needsImage, needsReference, needsOutpaintSource, needsOutpaintArea, t,
    })
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

  return <div>
    {frameError && <p role="alert" className="mb-1 max-w-xs text-xs text-red-300">{frameError}</p>}
    {submissionError && <p role="alert" className="mb-1 max-w-xs text-xs text-red-300">{submissionError}</p>}
    <button
      onClick={handleClick}
      data-wizard-anchor="generate"
      disabled={submitting || checkingFrame}
      className={`px-4 py-2 rounded-lg flex items-center gap-1.5 font-medium text-xs transition-all whitespace-nowrap ${
        submitting || checkingFrame
          ? 'bg-bg-active text-text-muted cursor-not-allowed'
          // Classic theme: bg-cta resolves to a flat accent-green.
          // HocusPocus Blue resolves to the branded blue gradient, while
          // shadow-accent-glow adds the restrained cool bloom.
          : 'bg-cta hover:brightness-110 shadow-accent-glow text-white'
      }`}
    >
      <Play size={13} fill={submitting ? 'currentColor' : 'white'} />
      {checkingFrame ? t('wangp.checkingFrame') : submitting
          ? t('generate.submitting')
          : scheduledVideoCount > 1
            ? t('generate.queueCount', { count: scheduledVideoCount })
            : queueCount > 0 ? t('generate.goCount', { count: queueCount }) : tCommon('actions.generate')}
    </button>
  </div>
}
