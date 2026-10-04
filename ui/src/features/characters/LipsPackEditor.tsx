import { useEffect, useRef, useState } from 'react'
import { Loader2, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { cancelJob, uploadImage } from '../../api/client'
import { cleanCharacterKitFaceOverlay } from '../../api/characters'
import { generateLipsMouth } from '../../lib/lipsGeneration'
import { acceptLipsCandidate, inspectLipsAlpha, missingLipsSounds } from '../../lib/lipsCreator'
import { faceRigAnchorFor } from '../../lib/characterKitFaceRig'
import { characterImageModels, preferredCharacterImageModel } from '../../lib/characterImageModels'
import { CHARACTER_MOUTH_STATES } from '../../lib/characterMouthStates'
import type { CharacterKit, CharacterMouthState } from '../../lib/characterKit'
import { LipsSpeechPreview } from './LipsSpeechPreview'
import {
  LipsAssignments, LipsBatchProgress, LipsCreationSettings, LipsLinkCharacter, LipsMouthDetail, LipsMouthGrid, LipsNameRow, LipsPlacement,
  type LipsDraft,
} from './LipsPackEditorSections'

export type { LipsDraft }
const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'
function plainText(translate: unknown) {
  const call = translate as (key: string, values?: Record<string, string | number>) => string
  return (key: string, values?: Record<string, string | number>) => call(key, values)
}
const touch = (kit: CharacterKit) => ({ ...kit, updatedAt: new Date().toISOString() })
function settingsStartOpen(kit: CharacterKit) {
  return !kit.base && Object.keys(kit.mouth).length === 0
}

export function LipsPackEditor({ initialDraft, workspace, characters, onDraftChange, onSave, onLink, onBusyChange }: {
  initialDraft: LipsDraft; workspace: string; characters: CharacterKit[]
  onDraftChange: (draft: LipsDraft) => void; onSave: (kit: CharacterKit, signal: AbortSignal) => Promise<void>
  onLink: (pack: CharacterKit, id: string) => Promise<void>
  onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('characters')
  const say = plainText(t)
  const [draft, setDraft] = useState(initialDraft), [selected, setSelected] = useState<CharacterMouthState>('closed')
  const [liveState, setLiveState] = useState<CharacterMouthState>(), [model, setModel] = useState('')
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const [canCancel, setCanCancel] = useState(false)
  const [batchProgress, setBatchProgress] = useState<{ index: number; total: number; completed: number }>()
  const [mouthErrors, setMouthErrors] = useState<Partial<Record<CharacterMouthState, string>>>({})
  const [settingsOpen, setSettingsOpen] = useState(settingsStartOpen(initialDraft.kit))
  const [target, setTarget] = useState(''), [referenceCharacter, setReferenceCharacter] = useState('')
  const operation = useRef<AbortController | null>(null), job = useRef<string | null>(null)
  const models = useStore(state => state.models)
  const withReference = draft.kit.mouthGenerationMode ? draft.kit.mouthGenerationMode === 'reference' : Boolean(draft.kit.base)
  const imageModels = characterImageModels(models, withReference)
  const imageModel = imageModels.some(item => item.model_type === model) ? model : preferredCharacterImageModel(imageModels, withReference)
  const isBusy = Boolean(busy)
  useEffect(() => { onBusyChange?.(isBusy) }, [isBusy, onBusyChange])
  useEffect(() => () => onBusyChange?.(false), [onBusyChange])
  useEffect(() => () => {
    operation.current?.abort()
    if (job.current) void cancelJob(job.current).catch(() => {})
  }, [])
  const update = (next: LipsDraft) => { setDraft(next); onDraftChange(next) }
  const updateKit = (kit: CharacterKit) => update({ ...draft, kit: touch(kit) })
  const run = async (label: string, action: (signal: AbortSignal) => Promise<void>, cancellable = false) => {
    if (operation.current) return
    const abort = new AbortController(); operation.current = abort
    setBusy(label); setCanCancel(cancellable); setError(''); setMessage('')
    try { await action(abort.signal) }
    catch (cause) { if (!abort.signal.aborted) setError((cause as Error).message) }
    finally { if (!abort.signal.aborted) { operation.current = null; job.current = null; setBusy(''); setCanCancel(false) } }
  }
  const stop = () => {
    operation.current?.abort(); operation.current = null
    if (job.current) void cancelJob(job.current).catch(() => {})
    job.current = null; setBusy(''); setCanCancel(false); setMessage(t('lips.cancelled'))
  }
  const generate = (states: CharacterMouthState[], saveEach = false) => run(t('lips.generating'), async signal => {
    let next = draft, completed = 0
    const failures: Partial<Record<CharacterMouthState, string>> = {}
    setMouthErrors({}); setBatchProgress({ index: 0, total: states.length, completed: 0 })
    for (const [index, state] of states.entries()) {
      signal.throwIfAborted(); setSelected(state)
      setBatchProgress({ index: index + 1, total: states.length, completed })
      setBusy(t('lips.batchGenerating', { index: index + 1, total: states.length, mouth: t(`faceRig.states.${state}`) }))
      let failedJob = false
      let result: Awaited<ReturnType<typeof generateLipsMouth>>
      try { result = await generateLipsMouth(next.kit, state, imageModel, workspace,
        { signal, onStatus: status => {
            failedJob = status.status === 'failed' || status.status === 'cancelled'
          }, onJobSubmitted: id => {
            if (signal.aborted) { void cancelJob(id).catch(() => {}); return }
            job.current = id
          } }) }
      catch (cause) {
        signal.throwIfAborted()
        // A lost connection can leave a job running. Only advance after a
        // confirmed terminal failure, so two image jobs never overlap.
        if (!failedJob) throw cause
        job.current = null
        failures[state] = (cause as Error).message
        setMouthErrors({ ...failures }); continue
      }
      signal.throwIfAborted(); job.current = null
      const { asset } = result
      next = { kit: touch({ ...next.kit, provenance: [...next.kit.provenance, { method: 'lips-creator-generate', state, source: asset.source,
        jobId: result.jobId, model: asset.model }] }), candidates: { ...next.candidates, [state]: asset } }
      update(next)
      if (saveEach) {
        setBusy(t('lips.batchSaving', { index: index + 1, total: states.length }))
        await onSave({ ...next.kit, mouthCandidates: next.candidates }, signal)
        signal.throwIfAborted()
      }
      completed += 1
      setBatchProgress({ index: index + 1, total: states.length, completed })
    }
    setMessage(Object.keys(failures).length ? t('lips.batchPartial', { count: completed, total: states.length })
      : saveEach ? t('lips.batchComplete', { count: completed }) : t('lips.compareHint'))
  }, true)
  const uploadMouth = (file: File) => run(t('lips.uploading'), async signal => {
    const result = await uploadImage(file); signal.throwIfAborted()
    const source = result.url || `/api/v1/uploads/${encodeURIComponent(result.filename)}`
    const alphaStatus = await inspectLipsAlpha(source); signal.throwIfAborted()
    update({ ...draft, candidates: { ...draft.candidates, [selected]: {
      id: `mouth-${selected}-${Date.now().toString(36)}`, name: `${draft.kit.name} · ${selected}`, source, kind: 'overlay', alphaStatus, reviewState: 'pending', workspace,
    } } })
  })
  const uploadReference = (file: File) => run(t('lips.uploading'), async signal => {
    const result = await uploadImage(file); signal.throwIfAborted()
    updateKit({ ...draft.kit, base: { id: `lips-reference-${Date.now().toString(36)}`, name: file.name, source: result.url || `/api/v1/uploads/${encodeURIComponent(result.filename)}`,
      kind: 'image', alphaStatus: 'unknown', reviewState: 'approved', workspace } })
    setReferenceCharacter('')
  })
  const existing = draft.kit.mouth[selected]
  const candidate = draft.candidates[selected] ?? (existing?.reviewState !== 'approved' ? existing : undefined)
  const previewPack = { ...draft.kit, mouth: { ...draft.kit.mouth, ...draft.candidates } }
  const missing = CHARACTER_MOUTH_STATES.filter(state => (!draft.kit.mouth[state]?.source || draft.kit.mouth[state]?.reviewState === 'rejected') && !draft.candidates[state])
  const ready = !missingLipsSounds(draft.kit).length
  const needsReference = withReference && !draft.kit.base
  const canGenerate = Boolean(imageModel) && !needsReference
  const accept = () => {
    if (!candidate) return
    try {
      const candidates = { ...draft.candidates }; delete candidates[selected]
      update({ kit: acceptLipsCandidate(draft.kit, selected, candidate), candidates }); setMessage(t('lips.accepted'))
    } catch (cause) { setError((cause as Error).message) }
  }
  const isWorking = Boolean(busy)
  const savePack = () => void run(t('lips.saving'), async signal => {
    await onSave({ ...draft.kit, mouthCandidates: draft.candidates }, signal)
    signal.throwIfAborted()
    setMessage(t('lips.saved'))
  })
  const cleanCandidate = () => {
    if (!candidate?.source) return
    void run(t('lips.cleaning'), async signal => {
      const cleaned = await cleanCharacterKitFaceOverlay({ workspace, source: candidate.source })
      signal.throwIfAborted()
      update({ ...draft, candidates: { ...draft.candidates, [selected]: { ...candidate, source: cleaned.source, width: cleaned.width, height: cleaned.height, alphaStatus: cleaned.alpha.status } } })
    })
  }
  const discard = () => {
    const candidates = { ...draft.candidates }
    delete candidates[selected]
    const mouth = { ...draft.kit.mouth }
    if (existing?.reviewState !== 'approved') delete mouth[selected]
    update({ kit: touch({ ...draft.kit, mouth }), candidates })
  }
  const placeAnchor = (field: 'offsetX' | 'offsetY' | 'scale', value: number) => {
    const anchor = faceRigAnchorFor(draft.kit, 'base', selected)
    const group = draft.kit.anchors.base || { mouth: anchor }
    updateKit({ ...draft.kit, anchors: { ...draft.kit.anchors, base: { ...group, mouthStates: { ...group.mouthStates, [selected]: { ...anchor, [field]: value } } } } })
  }
  const placeAll = () => {
    const anchor = faceRigAnchorFor(draft.kit, 'base', selected)
    const mouthStates = Object.fromEntries(CHARACTER_MOUTH_STATES.map(state => [state, { ...anchor }]))
    updateKit({ ...draft.kit, anchors: { ...draft.kit.anchors, base: { ...draft.kit.anchors.base, mouth: anchor, mouthStates } } })
  }
  const layout = () => <div className="space-y-5">
    <LipsNameRow name={draft.kit.name} busy={isWorking} nameLabel={t('lips.name')} saveLabel={t('lips.save')} onName={name => updateKit({ ...draft.kit, name })} onSave={savePack} />
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        <LipsCreationSettings kit={draft.kit} busy={isWorking} withReference={withReference} characters={characters} referenceCharacter={referenceCharacter}
          imageModels={imageModels} imageModel={imageModel} needsReference={needsReference} settingsOpen={settingsOpen} workspace={workspace} text={say}
          onSettingsOpen={setSettingsOpen} onMode={mode => { updateKit({ ...draft.kit, mouthGenerationMode: mode }); setModel('') }}
          onNotes={notes => updateKit({ ...draft.kit, lookNotes: notes })} onModel={setModel} onReferenceFile={file => void uploadReference(file)} onError={setError}
          onReferenceCharacter={id => {
            setReferenceCharacter(id)
            const kit = characters.find(item => item.id === id)
            if (kit?.base) updateKit({ ...draft.kit, base: { ...kit.base, reviewState: 'approved' }, anchors: kit.anchors, voice: kit.voice, voicesByLanguage: kit.voicesByLanguage, style: kit.style, lookNotes: draft.kit.lookNotes || kit.lookNotes })
          }} />
        <button type="button" disabled={isWorking || !canGenerate || !missing.length || !draft.kit.name.trim()} onClick={() => void generate(missing, true)} className={`${control} w-full`}>{t('lips.generateMissing', { count: missing.length })}</button>
        <p className="text-xs text-text-muted">{t('lips.sequenceHint')}</p>
        {batchProgress && <LipsBatchProgress index={batchProgress.index} total={batchProgress.total} completed={batchProgress.completed} errors={mouthErrors} text={say} />}
        <LipsMouthGrid draft={draft} selected={selected} liveState={liveState} busy={isWorking} text={say} onSelect={state => { setSelected(state); setError(''); setMessage('') }} />
        <LipsMouthDetail draft={draft} selected={selected} candidate={candidate} existing={existing} busy={isWorking} canGenerate={canGenerate} text={say}
          onPrompt={prompt => updateKit({ ...draft.kit, mouthPrompts: { ...draft.kit.mouthPrompts, [selected]: prompt } })}
          onGenerate={() => void generate([selected])} onUpload={file => void uploadMouth(file)} onClean={cleanCandidate} onAccept={accept} onDiscard={discard} />
        {draft.kit.base && <LipsPlacement kit={draft.kit} selected={selected} busy={isWorking} text={say} onAnchor={placeAnchor} onPlaceAll={placeAll} />}
      </div>
      <div className="min-w-0 space-y-5">
        <LipsSpeechPreview pack={previewPack} workspace={workspace} onActiveState={setLiveState} />
        <LipsAssignments kit={draft.kit} preview={previewPack} busy={isWorking} text={say} onStandard={() => updateKit({ ...draft.kit, mouthMapping: {} })}
          onAssign={(sound, state) => updateKit({ ...draft.kit, mouthMapping: { ...draft.kit.mouthMapping, [sound]: state } })} />
        <LipsLinkCharacter characters={characters} target={target} busy={isWorking} ready={ready} text={say} onTarget={setTarget}
          onApply={() => void run(t('lips.saving'), async signal => { await onLink(draft.kit, target); signal.throwIfAborted(); setMessage(t('lips.linked')) })} />
      </div>
    </div>
    {busy && <div role="status" className="sticky bottom-3 flex items-center gap-3 rounded-xl border border-cyan-400/30 bg-bg-secondary p-3 text-sm shadow-lg"><Loader2 size={16} className="animate-spin" />{busy}{canCancel && <button type="button" onClick={stop} className="ml-auto inline-flex items-center gap-1 text-text-secondary"><X size={14} />{t('lips.cancel')}</button>}</div>}
    {error && <p role="alert" className="rounded-lg border border-red-300/30 p-3 text-sm text-red-300">{error}</p>}
    {message && <p role="status" className="text-sm text-emerald-200">{message}</p>}
  </div>
  return layout()
}
