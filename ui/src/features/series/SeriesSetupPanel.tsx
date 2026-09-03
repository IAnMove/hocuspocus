import { useEffect, useRef, useState } from 'react'
import { Check, CheckCircle2, ImagePlus, Loader2, Sparkles, Square } from 'lucide-react'
import * as api from '../../api/client'
import { generateImageAsset } from '../../lib/imageGeneration'
import { useStore } from '../../stores/useStore'
import { SeriesField, SectionCard, seriesStatusLabel } from './components'
import { greenButton, inputClass, primaryButton, secondaryButton, selectClass, textareaClass } from './styles'
import type { SeriesJobStatus, SeriesProject } from './types'
import { useUiTranslation } from '../../i18n'
import { SpokenLanguageOptions } from '../../i18n/SpokenLanguageOptions'
import { seriesContentLanguagePatch, seriesSpokenLanguagePatch } from './languageIntent'

export function SeriesSetupPanel({
  workspace, series, update, saveNow, replaceSeries, job, setJob,
}: {
  workspace: string
  series: SeriesProject
  update: (updater: (series: SeriesProject) => SeriesProject) => void
  saveNow: () => Promise<unknown>
  replaceSeries: (series: SeriesProject) => void
  job: SeriesJobStatus | null
  setJob: (job: SeriesJobStatus | null) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const productionProfile = useStore(state => state.productionProfile)
  const [instruction, setInstruction] = useState('')
  const [knownSeriesRequest, setKnownSeriesRequest] = useState('')
  const [imageMode, setImageMode] = useState(false)
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState<string | null>(null)
  const adoptedKnownSeriesJob = useRef('')
  const patch = (value: Partial<SeriesProject>) => update(current => ({ ...current, ...value }))
  const patchProvider = (value: Partial<SeriesProject['provider']>) => update(current => ({
    ...current, provider: { ...current.provider, ...value },
  }))
  const patchVideo = (value: Partial<SeriesProject['provider']['videoSettings']>) => update(current => ({
    ...current,
    provider: {
      ...current.provider,
      videoSettings: { ...current.provider.videoSettings, ...value },
    },
  }))
  const complete = Boolean(series.title.trim() && series.premise.trim() && series.visualStyle.trim())
  const jobBusy = Boolean(job && ['queued', 'running', 'cancelling'].includes(job.status))
  const useGlobalProfile = () => patchProvider({
    useGlobalProfile: true,
    writingProvider: productionProfile.text.provider === 'local' || productionProfile.text.provider === 'anthropic'
      ? 'maestro'
      : productionProfile.text.provider === 'remote' ? 'openai-compatible' : productionProfile.text.provider as SeriesProject['provider']['writingProvider'],
    writingModel: productionProfile.text.model,
    writingBaseUrl: productionProfile.text.base_url || (
      productionProfile.text.provider === 'minimax' ? 'https://api.minimax.io/v1'
        : productionProfile.text.provider === 'grok' ? 'https://api.x.ai/v1'
          : productionProfile.text.provider === 'ollama' ? 'http://127.0.0.1:11434'
            : ''
    ),
    imageProvider: productionProfile.image.provider === 'minimax' ? 'minimax' : 'maestro',
    imageModel: productionProfile.image.model,
    videoModel: productionProfile.video.model,
    videoSettings: {
      ...series.provider.videoSettings,
      resolution: productionProfile.video.settings.resolution,
      orientation: productionProfile.video.settings.aspectRatio === '9:16' || productionProfile.video.settings.aspectRatio === '3:4'
        ? 'portrait' : 'landscape',
      numInferenceSteps: productionProfile.video.settings.steps,
      flowShift: productionProfile.video.settings.flowShift,
      audioShift: productionProfile.video.settings.audioShift,
      modelProfile: productionProfile.video.settings.profile,
    },
  })
  useEffect(() => {
    if (job?.jobType === 'canon') setImageMode(job.generateImages === true)
    if (!job || job.jobType !== 'canon' || !['queued', 'running', 'cancelling'].includes(job.status)) return
    let active = true
    const timer = window.setInterval(() => {
      void api.fetchSeriesPlanJob(job.jobId).then(value => { if (active) setJob(value) })
        .catch(reason => { if (active) setError((reason as Error).message) })
    }, 1000)
    return () => { active = false; window.clearInterval(timer) }
  }, [job, setJob])
  useEffect(() => {
    if (
      !job?.bootstrapKnownSeries || job.status !== 'completed' || !job.autoApplied ||
      adoptedKnownSeriesJob.current === job.jobId
    ) return
    adoptedKnownSeriesJob.current = job.jobId
    void api.fetchSeriesProject(workspace, series.id).then(replaceSeries).catch(reason => {
      adoptedKnownSeriesJob.current = ''
      setError((reason as Error).message)
    })
  }, [job, replaceSeries, series.id, workspace])
  const startKnownSeries = async () => {
    const request = knownSeriesRequest.trim()
    if (request.length < 3) return
    const hasAuthoredContent = Boolean(
      series.characters.length || series.locations.length || series.props.length ||
      series.premise.trim() || series.visualStyle.trim() ||
      (series.title.trim() && series.title.trim().toLowerCase() !== 'untitled series'),
    )
    if (hasAuthoredContent && !window.confirm(t('setup.replaceConfirm'))) return
    setBusy(true); setError(null); setImageMode(false)
    try {
      await saveNow()
      setJob(await api.startSeriesCanonPreparation(workspace, series.id, {
        instruction: request,
        writingProvider: series.provider.writingProvider,
        writingModel: series.provider.writingModel,
        writingBaseUrl: series.provider.writingBaseUrl,
        generateImages: false,
        bootstrapKnownSeries: true,
        autoApply: true,
      }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const startCanon = async (withImages: boolean) => {
    setBusy(true); setError(null); setImageMode(withImages)
    try {
      await saveNow()
      setJob(await api.startSeriesCanonPreparation(workspace, series.id, {
        instruction,
        writingProvider: series.provider.writingProvider,
        writingModel: series.provider.writingModel,
        writingBaseUrl: series.provider.writingBaseUrl,
        generateImages: withImages,
      }))
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const generateCanonImages = async (applied: SeriesProject) => {
    let current = applied
    const targets = [
      ...applied.characters.filter(item => !item.referenceAssetIds.length).map(item => ({
        ownerType: 'character' as const, ownerId: item.id, name: item.name,
        prompt: [applied.visualStyle, applied.characterVisualStyle, item.identityLock, item.appearance, 'One character identity portrait, clear face, no text, no contact sheet.'].filter(Boolean).join(' '),
        referenceRole: 'primary_portrait', kind: 'character' as const,
      })),
      ...applied.locations.filter(item => !item.referenceAssetIds.length).map(item => ({
        ownerType: 'location' as const, ownerId: item.id, name: item.name,
        prompt: [applied.visualStyle, item.description, 'One canonical establishing image, no people unless explicitly required, no text, no contact sheet.'].filter(Boolean).join(' '),
        referenceRole: 'location_reference', kind: 'location' as const,
      })),
    ]
    for (let index = 0; index < targets.length; index += 1) {
      const target = targets[index]
      setProgress(t('setup.generatingImage', { current: index + 1, total: targets.length, name: target.name }))
      const generated = await generateImageAsset(
        applied.provider.imageProvider === 'minimax' ? 'minimax' : 'maestro',
        target.prompt, applied.provider.imageModel, undefined, '',
        { panelId: `series-${applied.id}-${target.ownerId}`, aspectRatio: '1:1' },
      )
      const response = await fetch(generated.source)
      if (!response.ok) throw new Error(t('setup.imageUnavailable', { name: target.name }))
      const blob = await response.blob()
      const upload = await api.uploadImage(new File(
        [blob], generated.name || `${target.ownerId}.png`, { type: blob.type || 'image/png' },
      ))
      const imported = await api.importSeriesAsset(workspace, applied.id, {
        uploadPath: upload.path, name: generated.name || target.name,
        ownerType: target.ownerType, ownerId: target.ownerId, kind: target.kind,
        referenceRole: target.referenceRole,
        metadata: {
          prompt: target.prompt, model: generated.model,
          provider: applied.provider.imageProvider, createdAt: generated.createdAt,
        },
      })
      current = imported.series
      replaceSeries(current)
    }
    return current
  }
  const applyCanon = async () => {
    if (!job) return
    setBusy(true); setError(null); setProgress(t('setup.applying'))
    try {
      const applied = await api.applySeriesCanonPlanJob(job.jobId)
      replaceSeries(applied)
      if (imageMode) await generateCanonImages(applied)
      setProgress('')
      setJob(null)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const jobLine = job
    ? t('setup.jobProgress', { status: seriesStatusLabel(t, job.status), message: job.message })
    : ''
  const protagonist = series.characters.find(item => item.id === series.protagonistCharacterId)
  const protagonistReady = Boolean(
    protagonist?.primaryReferenceAssetId
    && series.assets[protagonist.primaryReferenceAssetId]
    && protagonist.approval === 'approved',
  )
  return (
    <div className="space-y-4 pb-10">
      <div className={`rounded-xl border px-4 py-3 ${complete ? 'border-green-500/30 bg-green-500/10' : 'border-violet-500/30 bg-violet-500/10'}`}>
        <div className="flex items-center gap-2 text-xs font-semibold text-text-primary">
          <CheckCircle2 size={15} className={complete ? 'text-green-400' : 'text-violet-400'} />
          {complete ? t('setup.ready') : t('setup.incomplete')}
        </div>
      </div>
      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}

      <SectionCard title={t('setup.knownTitle')} description={t('setup.knownDescription')}>
        <textarea
          className={textareaClass}
          value={knownSeriesRequest}
          onChange={event => setKnownSeriesRequest(event.target.value)}
          placeholder={t('setup.knownPlaceholder')}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            className={greenButton}
            disabled={knownSeriesRequest.trim().length < 3 || busy || jobBusy}
            onClick={() => void startKnownSeries()}
          ><Sparkles size={13} />{t('setup.knownBuild')}</button>
          {job?.bootstrapKnownSeries && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesPlanJob(job.jobId).then(setJob)}><Square size={13} />{t('setup.cancelJob')}</button>}
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-amber-200">{t('setup.knownDisclaimer')}</p>
        {job?.bootstrapKnownSeries && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3">
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            {['queued', 'running', 'cancelling'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}
            <span>{jobLine}</span><span className="ml-auto">{job.current}/{job.total}</span>
          </div>
          {job.error && <p className="mt-2 text-[10px] text-red-300">{job.error}</p>}
          {job.applyError && <p className="mt-2 text-[10px] text-amber-300">{job.applyError} {t('setup.applyErrorHint')}</p>}
          {job.status === 'completed' && job.autoApplied && job.seriesResult && <div className="mt-3 rounded-lg border border-green-500/30 bg-green-500/5 p-3">
            <p className="text-[11px] text-green-200">{t('setup.draftFilled', {
              characters: job.seriesResult.characters.length,
              locations: job.seriesResult.locations.length,
              relationships: job.seriesResult.relationships.length,
              props: job.seriesResult.props?.length || 0,
            })}</p>
            <p className="mt-1 text-[10px] text-text-muted">{t('setup.draftReview')}</p>
            <details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">{t('setup.inspectGenerated')}</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify(job.seriesResult, null, 2)}</pre></details>
          </div>}
          {(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-3 ${secondaryButton}`} onClick={() => void api.resumeSeriesPlanJob(job.jobId).then(setJob)}>{t('setup.resumeKnown')}</button>}
        </div>}
      </SectionCard>

      <SectionCard title={t('setup.prepareTitle')} description={t('setup.prepareDescription')}>
        <textarea className={textareaClass} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder={t('setup.preparePlaceholder')} />
        <div className="mt-3 flex flex-wrap gap-2"><button className={primaryButton} disabled={!complete || busy || jobBusy} onClick={() => void startCanon(false)}><Sparkles size={13} />{t('setup.prepareText')}</button><button className={greenButton} disabled={!complete || busy || (series.provider.imageProvider === 'maestro' && !series.provider.imageModel) || jobBusy} onClick={() => void startCanon(true)}><ImagePlus size={13} />{t('setup.prepareImages')}</button>{job && ['queued', 'running'].includes(job.status) && <button className={secondaryButton} onClick={() => void api.cancelSeriesPlanJob(job.jobId).then(setJob)}><Square size={13} />{t('setup.cancelJob')}</button>}</div>
        {series.provider.imageProvider === 'maestro' && !series.provider.imageModel && <p className="mt-2 text-[10px] text-amber-300">{t('setup.needImageModel')}</p>}
        {progress && <p className="mt-2 flex items-center gap-2 text-[11px] text-violet-200"><Loader2 size={12} className="animate-spin" />{progress}</p>}
        {job && !job.bootstrapKnownSeries && <div className="mt-3 rounded-lg border border-border bg-bg-primary p-3"><div className="flex items-center gap-2 text-xs text-text-secondary">{['queued', 'running', 'cancelling'].includes(job.status) && <Loader2 size={13} className="animate-spin" />}<span>{jobLine}</span><span className="ml-auto">{job.current}/{job.total}</span></div>{job.error && <p className="mt-2 text-[10px] text-red-300">{job.error}</p>}{job.status === 'completed' && job.seriesResult && <div className="mt-3 rounded-lg border border-green-500/30 bg-green-500/5 p-3"><p className="text-[11px] text-green-200">{t('setup.proposalSummary', { characters: job.seriesResult.characters.length, locations: job.seriesResult.locations.length, rules: job.seriesResult.canon.immutableRules.length })}</p><details className="mt-2 text-[10px] text-text-muted"><summary className="cursor-pointer">{t('setup.inspectProposal')}</summary><pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded bg-bg-tertiary p-2">{JSON.stringify(job.seriesResult, null, 2)}</pre></details><button className={`mt-3 ${greenButton}`} disabled={busy} onClick={() => void applyCanon()}><Check size={13} />{imageMode ? t('setup.applyCanonImages') : t('setup.applyCanon')}</button></div>}{(job.status === 'failed' || job.status === 'cancelled') && <button className={`mt-3 ${secondaryButton}`} onClick={() => void api.resumeSeriesPlanJob(job.jobId).then(setJob)}>{t('setup.resumeCanon')}</button>}</div>}
      </SectionCard>

      <SectionCard title={t('identity.title')} description={t('identity.description')}>
        <div className="grid gap-3 lg:grid-cols-2">
          <SeriesField label={t('identity.titleField')} required><input className={inputClass} value={series.title} onChange={event => patch({ title: event.target.value })} /></SeriesField>
          <SeriesField label={t('identity.format')}><select className={selectClass} value={series.format} onChange={event => patch({ format: event.target.value as SeriesProject['format'] })}>
            <option value="episodic">{t('format.episodic')}</option><option value="serial">{t('format.serial')}</option><option value="hybrid">{t('format.hybrid')}</option>
          </select></SeriesField>
          <SeriesField label={t('identity.premise')} required><textarea className={textareaClass} value={series.premise} onChange={event => patch({ premise: event.target.value })} /></SeriesField>
          <SeriesField label={t('identity.logline')}><textarea className={textareaClass} value={series.logline} onChange={event => patch({ logline: event.target.value })} /></SeriesField>
          <SeriesField label={t('identity.language')}><input className={inputClass} value={series.language} onChange={event => patch(seriesContentLanguagePatch(series, event.target.value))} /></SeriesField>
          <SeriesField label={t('library.spoken')} hint={t('library.spokenHint')}><select className={selectClass} value={series.spokenLanguage} onChange={event => patch(seriesSpokenLanguagePatch(series, event.target.value))}><SpokenLanguageOptions /></select></SeriesField>
          <SeriesField label={t('identity.duration')} hint={t('identity.durationHint')}><input className={inputClass} type="number" min={15} max={3600} value={series.defaultEpisodeDurationSeconds} onChange={event => patch({ defaultEpisodeDurationSeconds: Number(event.target.value) })} /></SeriesField>
          <SeriesField label={t('identity.genre')}><input className={inputClass} value={series.genre} onChange={event => patch({ genre: event.target.value })} /></SeriesField>
          <SeriesField label={t('identity.tone')}><input className={inputClass} value={series.tone} onChange={event => patch({ tone: event.target.value })} /></SeriesField>
          <SeriesField label={t('identity.audience')}><input className={inputClass} value={series.audience} onChange={event => patch({ audience: event.target.value })} /></SeriesField>
        </div>
      </SectionCard>

      <SectionCard title={t('visual.title')} description={t('visual.description')}>
        <div className="grid gap-3 lg:grid-cols-2">
          <SeriesField label={t('visual.visualStyle')} required><textarea className={textareaClass} value={series.visualStyle} onChange={event => patch({ visualStyle: event.target.value })} /></SeriesField>
          <SeriesField label={t('visual.characterVisualStyle')}><textarea className={textareaClass} value={series.characterVisualStyle} onChange={event => patch({ characterVisualStyle: event.target.value })} /></SeriesField>
          <SeriesField label={t('visual.cameraLanguage')}><textarea className={textareaClass} value={series.cameraLanguage} onChange={event => patch({ cameraLanguage: event.target.value })} /></SeriesField>
          <SeriesField label={t('visual.textPolicy')} hint={t('visual.textPolicyHint')}>
            <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={series.allowClipText} onChange={event => patch({ allowClipText: event.target.checked })} />{t('visual.allowText')}</label>
          </SeriesField>
          <SeriesField label={t('visual.nativeDialogue')} hint={t('visual.nativeDialogueHint')}>
            <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={series.bestEffortLipSyncAcknowledged} onChange={event => patch({ bestEffortLipSyncAcknowledged: event.target.checked })} />{t('visual.lipSync')}</label>
          </SeriesField>
          <SeriesField label={t('visual.protagonist')} hint={t('visual.protagonistHint')}>
            <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={series.protagonistConsistency} onChange={event => patch({ protagonistConsistency: event.target.checked, protagonistCharacterId: event.target.checked ? (series.protagonistCharacterId || series.characters[0]?.id || '') : series.protagonistCharacterId })} />{t('visual.protagonistFirst')}</label>
            {series.protagonistConsistency && <select className={`${selectClass} mt-2`} value={series.protagonistCharacterId} onChange={event => patch({ protagonistCharacterId: event.target.value })}><option value="">{t('visual.chooseProtagonist')}</option>{series.characters.map(character => <option key={character.id} value={character.id}>{character.name || t('visual.unnamedCharacter')}</option>)}</select>}
            {series.protagonistConsistency && <p className={`mt-1 text-[10px] ${protagonistReady ? 'text-emerald-200' : 'text-amber-300'}`}>{protagonistReady ? t('visual.identityReady') : t('visual.identityMissing')}</p>}
          </SeriesField>
        </div>
      </SectionCard>

      <SectionCard title={t('source.title')} description={t('source.description')}>
        <div className="grid gap-3 lg:grid-cols-2">
          <SeriesField label={t('source.mode')}><select className={selectClass} value={series.sourceMode} onChange={event => patch({ sourceMode: event.target.value as SeriesProject['sourceMode'] })}>
            <option value="original">{t('source.original')}</option><option value="known_universe_experimental">{t('source.knownUniverse')}</option><option value="hybrid">{t('source.hybrid')}</option>
          </select></SeriesField>
          <SeriesField label={t('source.rights')} hint={t('source.rightsHint')}><textarea className={textareaClass} value={series.rightsNote} onChange={event => patch({ rightsNote: event.target.value })} /></SeriesField>
          {series.sourceMode !== 'original' && <div className="lg:col-span-2"><SeriesField label={t('source.masterPrompt')} required><textarea className={textareaClass} value={series.masterUniversePrompt} onChange={event => patch({ masterUniversePrompt: event.target.value })} /></SeriesField></div>}
          {series.sourceMode !== 'original' && <p className="lg:col-span-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-[10px] leading-relaxed text-amber-200">{t('source.experimentalWarning')}</p>}
        </div>
      </SectionCard>

      <SectionCard title={t('providers.title')} description={t('providers.description')}>
        <div className="mb-3 grid max-w-xl grid-cols-2 gap-2">
          <button type="button" className={`${secondaryButton} ${series.provider.useGlobalProfile ? 'border-violet-400 text-violet-200' : ''}`} onClick={useGlobalProfile}>{t('providers.useGlobal')}</button>
          <button type="button" className={`${secondaryButton} ${!series.provider.useGlobalProfile ? 'border-violet-400 text-violet-200' : ''}`} onClick={() => patchProvider({ useGlobalProfile: false })}>{t('providers.override')}</button>
        </div>
        {series.provider.useGlobalProfile && <p className="mb-3 text-[10px] text-green-300">{t('providers.globalSummary', { text: productionProfile.text.model, image: productionProfile.image.model, video: productionProfile.video.model })}</p>}
        <fieldset disabled={series.provider.useGlobalProfile} className="disabled:opacity-50">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <SeriesField label={t('providers.writingProvider')}><select className={selectClass} value={series.provider.writingProvider} onChange={event => patchProvider({ writingProvider: event.target.value as SeriesProject['provider']['writingProvider'] })}>
            <option value="maestro">{t('providers.maestro')}</option><option value="deepseek">{t('providers.deepseek')}</option><option value="minimax">{t('providers.minimax')}</option><option value="openai">{t('providers.openai')}</option><option value="openai-compatible">{t('providers.compatible')}</option>
          </select></SeriesField>
          <SeriesField label={t('providers.writingModel')}><input className={inputClass} value={series.provider.writingModel} onChange={event => patchProvider({ writingModel: event.target.value })} placeholder={t('providers.writingModelPlaceholder')} /></SeriesField>
          <SeriesField label={t('providers.imageProvider')}><select className={selectClass} value={series.provider.imageProvider} onChange={event => patchProvider({ imageProvider: event.target.value })}><option value="maestro">{t('providers.imageLocal')}</option><option value="minimax">{t('providers.imageMinimax')}</option></select></SeriesField>
          <SeriesField label={t('providers.imageModel')}><input className={inputClass} value={series.provider.imageModel} disabled={series.provider.imageProvider === 'minimax'} onChange={event => patchProvider({ imageModel: event.target.value })} placeholder={series.provider.imageProvider === 'minimax' ? t('providers.imageModelMinimax') : t('providers.imageModelLocal')} /></SeriesField>
          <SeriesField label={t('providers.videoModel')}><select className={selectClass} value={series.provider.videoModel} onChange={event => patchProvider({ videoModel: event.target.value })}>
            <option value="minimax_h3_legacy">{t('providers.h3Legacy')}</option><option value="minimax_h3">{t('providers.h3Pruned')}</option><option value="minimax_h3_full">{t('providers.h3Full')}</option>
          </select></SeriesField>
          <SeriesField label={t('providers.resolution')}><select className={selectClass} value={String(series.provider.videoSettings.resolution || '480p')} onChange={event => patchVideo({ resolution: event.target.value })}>
            <option value="480p">{t('providers.res480')}</option><option value="540p">{t('providers.res540')}</option><option value="720p">{t('providers.res720')}</option><option value="768p">{t('providers.res768')}</option>
          </select></SeriesField>
          <SeriesField label={t('providers.orientation')}><select className={selectClass} value={String(series.provider.videoSettings.orientation || 'landscape')} onChange={event => patchVideo({ orientation: event.target.value as 'landscape' | 'portrait' })}>
            <option value="landscape">{t('providers.landscape')}</option><option value="portrait">{t('providers.portrait')}</option>
          </select></SeriesField>
          <SeriesField label={t('providers.steps')}><input className={inputClass} type="number" min={1} max={50} value={Number(series.provider.videoSettings.numInferenceSteps || 20)} onChange={event => patchVideo({ numInferenceSteps: Number(event.target.value) })} /></SeriesField>
        </div>
        </fieldset>
      </SectionCard>
    </div>
  )
}
