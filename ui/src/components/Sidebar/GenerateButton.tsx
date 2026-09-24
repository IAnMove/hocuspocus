import { useState, useRef } from 'react'
import { Play, AlertTriangle } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { splitPromptSchedule } from '../../lib/promptScheduler'
import { newUserGenerationContext } from '../../features/studio/generationProvenance'
import { useViggleGenerationGuard } from '../../lib/useViggleGenerationGuard'
import { isGenerationJobActive } from '../../lib/generationJobState'
import { usePlatformCapabilities } from '../../lib/usePlatformCapabilities'
import { generateBlockedCopy, hasOutpaintArea, isRemoteMiniMaxImage } from '../../lib/generateButtonGate'
import { imageStudioInputRequirement, supportsImageIntent } from '../../features/studio/imageStudioIntent'
import { imageBatchPairs, MAX_IMAGE_BATCH_JOBS } from '../../features/studio/imageBatch'

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
  const imageRequirement = useStore(s => s.generationMode === 'image'
    ? imageStudioInputRequirement(s.imageStudioIntent, s.imageStudioIntent === 'edit' && s.imageBatch?.enabled ? s.imageBatch.sources[0]?.url : s.params.image_guide, s.imageRefs.length || s.params.image_refs?.length || 0)
    : null)
  const incompatibleImage = useStore(s => s.generationMode === 'image' && !supportsImageIntent(s.imageStudioIntent, s.modelOptions))
  const needsImage = (generationMode === 'video' && isI2vOnly && !isOmniReference && !hasStartImage)
    || imageRequirement === 'source'
  const needsReference = (generationMode === 'video' && isOmniReference
    && !hasOmniVisualReference) || imageRequirement === 'reference'
  const editSubMode = useStore(s => s.editSubMode)
  const editVideoPath = useStore(s => s.editVideoPath)
  const outpaintVideoBox = useStore(s => s.outpaintVideoBox)
  const isOutpaint = generationMode === 'avatar' && editSubMode === 'outpaint'
  const needsOutpaintSource = isOutpaint && !editVideoPath
  const needsOutpaintArea = isOutpaint && !!editVideoPath && !hasOutpaintArea(outpaintVideoBox)
  const promptSchedulerEnabled = useStore(s => s.promptSchedulerEnabled)
  const imageMode = useStore(s => s.params.image_mode)
  const prompt = useStore(s => s.params.prompt)
  const imageBatch = useStore(s => s.imageBatch)
  const imageIntent = useStore(s => s.imageStudioIntent)
  const imageMask = useStore(s => s.params.image_mask)
  const batching = generationMode === 'image' && (imageBatch?.perLine || (imageIntent === 'edit' && imageBatch?.enabled))
  const batchCount = batching ? imageBatchPairs(String(prompt || ''), imageBatch, imageIntent === 'edit').length : 0
  const invalidBatch = batching && (!batchCount || batchCount > MAX_IMAGE_BATCH_JOBS || (imageBatch?.enabled && imageIntent === 'edit' && Boolean(imageMask)))
  const schedulerApplies = promptSchedulerEnabled && generationMode === 'video' && imageMode === 0
  const scheduledVideoCount = schedulerApplies ? splitPromptSchedule(prompt).length : 0
  const needsScheduledPrompts = schedulerApplies && scheduledVideoCount === 0
  const needsPrompt = generationMode === 'image' && !String(prompt || '').trim()
  const modelType = useStore(s => s.params.model_type)
  const imageProvider = useStore(s => s.productionProfile?.image?.provider)
  const localUnavailable = usePlatformCapabilities()?.capabilities.wangp_local?.state === 'hidden'
    && !isRemoteMiniMaxImage(generationMode, modelType, imageProvider)
  const blocked = incompatibleImage || localUnavailable || needsImage || needsReference || needsOutpaintSource
    || needsOutpaintArea || needsScheduledPrompts || needsPrompt || invalidBatch

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
      incompatibleImage, localUnavailable, needsImage, needsReference, needsOutpaintSource, needsOutpaintArea,
      needsPrompt, needsScheduledPrompts, t,
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
          : scheduledVideoCount > 1 || batching
            ? t('generate.queueCount', { count: batching ? batchCount : scheduledVideoCount })
            : tCommon('actions.generate')}
    </button>
    {queueCount > 0 ? <p className="mt-1 text-right text-[10px] text-text-muted">{t('generate.activeCount', { count: queueCount })}</p> : null}
  </div>
}
