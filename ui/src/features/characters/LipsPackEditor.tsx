import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, Save, Upload, WandSparkles, X } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { cancelJob, uploadImage } from '../../api/client'
import { cleanCharacterKitFaceOverlay } from '../../api/characters'
import { generateLipsMouth } from '../../lib/lipsGeneration'
import { LabsLibraryPick } from '../../lib/LabsLibraryPick'
import { acceptLipsCandidate, inspectLipsAlpha, missingLipsSounds } from '../../lib/lipsCreator'
import { faceRigAnchorFor } from '../../lib/characterKitFaceRig'
import { characterImageModels, preferredCharacterImageModel } from '../../lib/characterImageModels'
import { CHARACTER_MOUTH_STATES, MOUTH_SOUND_GROUPS, mouthStateForSound } from '../../lib/characterMouthStates'
import type { CharacterKit, CharacterKitAsset, CharacterMouthState } from '../../lib/characterKit'
import { LipsSpeechPreview } from './LipsSpeechPreview'

export type LipsDraft = { kit: CharacterKit; candidates: Partial<Record<CharacterMouthState, CharacterKitAsset>> }
const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'
const touch = (kit: CharacterKit) => ({ ...kit, updatedAt: new Date().toISOString() })

export function LipsPackEditor({ initialDraft, workspace, characters, onDraftChange, onSave, onLink, onBusyChange }: {
  initialDraft: LipsDraft; workspace: string; characters: CharacterKit[]
  onDraftChange: (draft: LipsDraft) => void; onSave: (kit: CharacterKit, signal: AbortSignal) => Promise<void>
  onLink: (pack: CharacterKit, id: string) => Promise<void>
  onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useUiTranslation('characters')
  const [draft, setDraft] = useState(initialDraft), [selected, setSelected] = useState<CharacterMouthState>('closed')
  const [liveState, setLiveState] = useState<CharacterMouthState>(), [model, setModel] = useState('')
  const [busy, setBusy] = useState(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const [canCancel, setCanCancel] = useState(false)
  const [batchProgress, setBatchProgress] = useState<{ index: number; total: number; completed: number }>()
  const [mouthErrors, setMouthErrors] = useState<Partial<Record<CharacterMouthState, string>>>({})
  const [settingsOpen, setSettingsOpen] = useState(!initialDraft.kit.base && !Object.keys(initialDraft.kit.mouth).length)
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
  const anchor = faceRigAnchorFor(draft.kit, 'base', selected)
  return <div className="space-y-5">
    <div className="flex flex-wrap items-center gap-3">
      <input aria-label={t('lips.name')} value={draft.kit.name} maxLength={80} disabled={Boolean(busy)} onChange={event => updateKit({ ...draft.kit, name: event.target.value })}
        className={`${control} min-w-0 flex-1 font-medium`} />
      <button type="button" disabled={Boolean(busy) || !draft.kit.name.trim()} onClick={() => void run(t('lips.saving'), async signal => { await onSave({ ...draft.kit, mouthCandidates: draft.candidates }, signal); signal.throwIfAborted(); setMessage(t('lips.saved')) })}
        className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-black disabled:opacity-40"><Save size={15} />{t('lips.save')}</button>
    </div>
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
      <div className="min-w-0 space-y-5">
        <details open={settingsOpen} onToggle={event => setSettingsOpen(event.currentTarget.open)} className="rounded-xl border border-border p-4">
          <summary className="cursor-pointer text-sm font-medium">{t('lips.creationSettings')}</summary>
          <div className="mt-4 space-y-3">
            <fieldset disabled={Boolean(busy)} className="flex flex-wrap gap-4 text-sm">
              <legend className="mb-2 text-xs text-text-secondary">{t('lips.createFrom')}</legend>
              <label className="inline-flex items-center gap-2"><input type="radio" name={`lips-source-${draft.kit.id}`} checked={!withReference} onChange={() => { updateKit({ ...draft.kit, mouthGenerationMode: 'description' }); setModel('') }} />{t('lips.descriptionOnly')}</label>
              <label className="inline-flex items-center gap-2"><input type="radio" name={`lips-source-${draft.kit.id}`} checked={withReference} onChange={() => { updateKit({ ...draft.kit, mouthGenerationMode: 'reference' }); setModel('') }} />{t('lips.withReference')}</label>
            </fieldset>
            <label className="block text-xs text-text-secondary">{t('lips.style')}<textarea rows={2} maxLength={1500} value={draft.kit.lookNotes || ''} disabled={Boolean(busy)} onChange={event => updateKit({ ...draft.kit, lookNotes: event.target.value })} placeholder={t('lips.styleHint')} className="mt-2 w-full rounded-lg border border-border bg-bg-primary p-2 text-sm" /></label>
            <label className="block text-xs text-text-secondary">{t('lips.imageModel')}<select value={imageModel} disabled={Boolean(busy)} onChange={event => setModel(event.target.value)} className={`${control} mt-2 w-full`}>
              {!imageModels.length && <option value="">{t('lips.noImageModel')}</option>}{imageModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
            </select></label>
            {withReference ? <><label className="block text-xs text-text-secondary">{t('lips.referenceCharacter')}<select value={referenceCharacter} disabled={Boolean(busy)} className={`${control} mt-2 w-full`} onChange={event => {
              setReferenceCharacter(event.target.value)
              const kit = characters.find(kit => kit.id === event.target.value)
              if (kit?.base) updateKit({ ...draft.kit, base: { ...kit.base, reviewState: 'approved' }, anchors: kit.anchors, voice: kit.voice, style: kit.style, lookNotes: draft.kit.lookNotes || kit.lookNotes })
            }}><option value="">{t('lips.chooseCharacter')}</option>{characters.filter(kit => kit.base).map(kit => <option key={kit.id} value={kit.id}>{kit.name}</option>)}</select></label>
            <label className="block text-xs text-text-secondary">{t('lips.uploadReference')}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={Boolean(busy)} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void uploadReference(file) }} className="mt-2 block w-full text-xs" /></label>
            <LabsLibraryPick workspace={workspace} disabled={Boolean(busy)} onFile={file => void uploadReference(file)} onError={setError} />
            {draft.kit.base && <img src={draft.kit.base.source} alt={t('lips.reference')} className="h-24 max-w-full rounded-lg border border-border object-contain" />}
            </> : <p className="text-xs text-text-muted">{t('lips.descriptionHint')}</p>}
            {needsReference && <p className="text-xs text-amber-200">{t('lips.needsReference')}</p>}
          </div>
        </details>
        <button type="button" disabled={Boolean(busy) || !canGenerate || !missing.length || !draft.kit.name.trim()} onClick={() => void generate(missing, true)} className={`${control} w-full`}>{t('lips.generateMissing', { count: missing.length })}</button>
        <p className="text-xs text-text-muted">{t('lips.sequenceHint')}</p>
        {batchProgress && <div data-testid="lips-batch-progress" className="space-y-2 rounded-lg border border-border p-3 text-sm">
          <p>{t('lips.batchProgress', { index: batchProgress.index, total: batchProgress.total, count: batchProgress.completed })}</p>
          <progress aria-label={t('lips.batchProgressLabel')} value={batchProgress.completed + Object.keys(mouthErrors).length} max={batchProgress.total} className="h-2 w-full accent-cyan-400" />
          {Object.entries(mouthErrors).map(([state, detail]) => <p key={state} className="text-xs text-amber-200">{t('lips.batchMouthFailed', { mouth: t(`faceRig.states.${state as CharacterMouthState}`), error: detail })}</p>)}
        </div>}
        <div className="grid grid-cols-3 gap-2">
          {CHARACTER_MOUTH_STATES.map(state => {
            const asset = draft.candidates[state] ?? draft.kit.mouth[state]
            const sounds = MOUTH_SOUND_GROUPS.filter(sound => mouthStateForSound(sound, draft.kit.mouthMapping) === state)
            return <button type="button" key={state} aria-pressed={selected === state} disabled={Boolean(busy)} onClick={() => { setSelected(state); setError(''); setMessage('') }}
              className={`relative rounded-xl border p-2 text-left transition-colors disabled:opacity-60 ${selected === state ? 'border-cyan-400 bg-cyan-400/5' : liveState === state ? 'border-amber-300' : 'border-border bg-bg-secondary'}`}>
              <div className="flex h-14 items-center justify-center overflow-hidden rounded bg-bg-primary">{asset ? <img src={asset.source} alt="" className="max-h-12 max-w-[85%] object-contain" /> : <PlusMouth />}</div>
              <span className="mt-2 block truncate text-xs font-medium">{t(`faceRig.states.${state}`)}</span>
              <span className="mt-1 block min-h-4 truncate text-[10px] text-text-muted">{sounds.map(sound => t(`lips.sounds.${sound}`)).join(' · ') || '—'}</span>
              {asset?.reviewState === 'approved' && !draft.candidates[state] && <Check size={12} className="absolute right-2 top-2 text-emerald-300" />}
              {draft.candidates[state] && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-amber-300" />}
            </button>
          })}
        </div>
        <section className="space-y-3 rounded-xl border border-border bg-bg-secondary p-4">
          <h3 className="font-medium">{t(`faceRig.states.${selected}`)}</h3>
          <div className={`grid gap-3 ${candidate && existing?.reviewState === 'approved' ? 'grid-cols-2' : 'grid-cols-1'}`}>
            {candidate && existing?.reviewState === 'approved' && <div><p className="mb-2 text-xs text-text-muted">{t('lips.current')}</p><MouthImage source={existing.source} /></div>}
            <div><p className="mb-2 text-xs text-text-muted">{t(candidate ? 'lips.candidate' : 'lips.current')}</p><MouthImage source={(candidate ?? existing)?.source} /></div>
          </div>
          <input aria-label={t('lips.mouthInstruction')} placeholder={t('lips.mouthInstructionHint')} disabled={Boolean(busy)} maxLength={500} value={draft.kit.mouthPrompts?.[selected] || ''}
            onChange={event => updateKit({ ...draft.kit, mouthPrompts: { ...draft.kit.mouthPrompts, [selected]: event.target.value } })} className={`${control} w-full`} />
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={Boolean(busy) || !canGenerate} onClick={() => void generate([selected])} className={`${control} inline-flex items-center gap-2`}><WandSparkles size={14} />{t(existing || candidate ? 'lips.regenerate' : 'lips.generateMouth')}</button>
            <label className={`${control} inline-flex cursor-pointer items-center gap-2 ${busy ? 'opacity-40' : ''}`}><Upload size={14} />{t('lips.uploadMouth')}<input type="file" accept="image/png,image/webp,image/jpeg" className="sr-only" disabled={Boolean(busy)} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void uploadMouth(file) }} /></label>
          </div>
          {candidate && <div className="space-y-2">
            {candidate.alphaStatus !== 'transparent' && !candidate.facePatch && <button type="button" disabled={Boolean(busy)} onClick={() => void run(t('lips.cleaning'), async signal => {
              const cleaned = await cleanCharacterKitFaceOverlay({ workspace, source: candidate.source }); signal.throwIfAborted()
              update({ ...draft, candidates: { ...draft.candidates, [selected]: { ...candidate, source: cleaned.source, width: cleaned.width, height: cleaned.height, alphaStatus: cleaned.alpha.status } } })
            })} className={`${control} w-full`}>{t('lips.removeBackground')}</button>}
            <div className="flex gap-2"><button type="button" disabled={Boolean(busy) || (candidate.alphaStatus !== 'transparent' && !candidate.facePatch)} onClick={accept} className="min-h-10 flex-1 rounded-lg bg-emerald-400/15 px-3 text-sm text-emerald-200 disabled:opacity-40">{t('lips.accept')}</button>
              <button type="button" disabled={Boolean(busy)} onClick={() => {
                const candidates = { ...draft.candidates }; delete candidates[selected]
                const mouth = { ...draft.kit.mouth }; if (existing?.reviewState !== 'approved') delete mouth[selected]
                update({ kit: touch({ ...draft.kit, mouth }), candidates })
              }} className={control}>{t('lips.discard')}</button></div>
          </div>}
        </section>
        {draft.kit.base && <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm">{t('lips.placement')}</summary>
          <div className="mt-3 space-y-3">{(['offsetX', 'offsetY', 'scale'] as const).map(field => <label key={field} className="block text-xs text-text-secondary">{t(`lips.anchor.${field}`)}
            <input type="range" aria-label={t(`lips.anchor.${field}`)} min={field === 'scale' ? .01 : -45} max={field === 'scale' ? .5 : 45} step={field === 'scale' ? .001 : .5} value={anchor[field]} disabled={Boolean(busy)} className="mt-2 w-full" onChange={event => {
              const group = draft.kit.anchors.base || { mouth: anchor }
              updateKit({ ...draft.kit, anchors: { ...draft.kit.anchors, base: { ...group, mouthStates: { ...group.mouthStates, [selected]: { ...anchor, [field]: Number(event.target.value) } } } } })
            }} /></label>)}
            <button type="button" disabled={Boolean(busy)} className={control} onClick={() => updateKit({ ...draft.kit, anchors: { ...draft.kit.anchors, base: { ...draft.kit.anchors.base, mouth: anchor, mouthStates: Object.fromEntries(CHARACTER_MOUTH_STATES.map(state => [state, { ...anchor }])) } } })}>{t('lips.placeAll')}</button>
          </div>
        </details>}
      </div>
      <div className="min-w-0 space-y-5">
        <LipsSpeechPreview pack={previewPack} workspace={workspace} onActiveState={setLiveState} />
        <section className="space-y-3 rounded-xl border border-border bg-bg-secondary p-4"><div className="flex items-center justify-between gap-3"><h3 className="font-medium">{t('lips.assignments')}</h3>
          <button type="button" disabled={Boolean(busy)} onClick={() => updateKit({ ...draft.kit, mouthMapping: {} })} className="text-xs text-cyan-300">{t('lips.standard')}</button></div>
          <p className="text-xs text-text-muted">{t('lips.assignmentsHint')}</p>
          <div className="space-y-2">{MOUTH_SOUND_GROUPS.map(sound => {
            const state = mouthStateForSound(sound, draft.kit.mouthMapping), asset = previewPack.mouth[state]
            return <label key={sound} className="flex items-center gap-3 text-sm"><span className="w-16 shrink-0">{t(`lips.sounds.${sound}`)}</span>
              <span className="flex h-8 w-9 shrink-0 items-center justify-center rounded bg-bg-primary">{asset && <img src={asset.source} alt="" className="max-h-7 max-w-8 object-contain" />}</span>
              <select aria-label={t('lips.assignSound', { sound: t(`lips.sounds.${sound}`) })} value={state} disabled={Boolean(busy)} className={`${control} min-w-0 flex-1`} onChange={event => updateKit({ ...draft.kit, mouthMapping: { ...draft.kit.mouthMapping, [sound]: event.target.value as CharacterMouthState } })}>
                {CHARACTER_MOUTH_STATES.map(state => <option key={state} value={state}>{t(`faceRig.states.${state}`)}</option>)}
              </select></label>
          })}</div>
        </section>
        <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm font-medium">{t('lips.linkCharacter')}</summary>
          <div className="mt-3 space-y-3"><p className="text-xs text-text-muted">{t('lips.linkHint')}</p>
            <select aria-label={t('lips.targetCharacter')} value={target} disabled={Boolean(busy)} onChange={event => setTarget(event.target.value)} className={`${control} w-full`}><option value="">{t('lips.chooseCharacter')}</option>{characters.filter(kit => kit.base).map(kit => <option key={kit.id} value={kit.id}>{kit.name}</option>)}</select>
            <button type="button" disabled={Boolean(busy) || !target || !ready} className={`${control} w-full`} onClick={() => void run(t('lips.saving'), async signal => { await onLink(draft.kit, target); signal.throwIfAborted(); setMessage(t('lips.linked')) })}>{t('lips.apply')}</button>
            {!ready && <p className="text-xs text-amber-200">{t('lips.approveBeforeLink')}</p>}
          </div>
        </details>
      </div>
    </div>
    {busy && <div role="status" className="sticky bottom-3 flex items-center gap-3 rounded-xl border border-cyan-400/30 bg-bg-secondary p-3 text-sm shadow-lg"><Loader2 size={16} className="animate-spin" />{busy}{canCancel && <button type="button" onClick={stop} className="ml-auto inline-flex items-center gap-1 text-text-secondary"><X size={14} />{t('lips.cancel')}</button>}</div>}
    {error && <p role="alert" className="rounded-lg border border-red-300/30 p-3 text-sm text-red-300">{error}</p>}
    {message && <p role="status" className="text-sm text-emerald-200">{message}</p>}
  </div>
}

function MouthImage({ source }: { source?: string }) {
  return <div className="flex h-32 items-center justify-center overflow-hidden rounded-xl bg-bg-primary p-4">{source ? <img src={source} alt="" className="max-h-full max-w-full object-contain" /> : <PlusMouth />}</div>
}
function PlusMouth() { return <span className="text-xl font-light text-text-muted">+</span> }
