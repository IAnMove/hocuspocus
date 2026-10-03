import { Check, Save, Upload, WandSparkles } from 'lucide-react'
import { LabsLibraryPick } from '../../lib/LabsLibraryPick'
import { faceRigAnchorFor } from '../../lib/characterKitFaceRig'
import { CHARACTER_MOUTH_STATES, MOUTH_SOUND_GROUPS, mouthStateForSound } from '../../lib/characterMouthStates'
import type { CharacterKit, CharacterKitAsset, CharacterMouthState } from '../../lib/characterKit'

export type LipsDraft = { kit: CharacterKit; candidates: Partial<Record<CharacterMouthState, CharacterKitAsset>> }

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'

export function LipsNameRow({ name, busy, onName, onSave, saveLabel, nameLabel }: {
  name: string; busy: boolean; onName: (name: string) => void; onSave: () => void; saveLabel: string; nameLabel: string
}) {
  return <div className="flex flex-wrap items-center gap-3">
    <input aria-label={nameLabel} value={name} maxLength={80} disabled={busy} onChange={event => onName(event.target.value)}
      className={`${control} min-w-0 flex-1 font-medium`} />
    <button type="button" disabled={busy || !name.trim()} onClick={onSave}
      className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-cyan-500 px-4 text-sm font-medium text-black disabled:opacity-40"><Save size={15} />{saveLabel}</button>
  </div>
}

export function LipsCreationSettings({ kit, busy, withReference, characters, referenceCharacter, imageModels, imageModel, needsReference, settingsOpen, onSettingsOpen, onMode, onNotes, onModel, onReferenceCharacter, onReferenceFile, workspace, onError, text }: {
  kit: CharacterKit; busy: boolean; withReference: boolean; characters: CharacterKit[]; referenceCharacter: string
  imageModels: { model_type: string; name: string }[]; imageModel: string; needsReference: boolean; settingsOpen: boolean
  onSettingsOpen: (open: boolean) => void; onMode: (mode: 'description' | 'reference') => void; onNotes: (notes: string) => void
  onModel: (model: string) => void; onReferenceCharacter: (id: string) => void; onReferenceFile: (file: File) => void
  workspace: string; onError: (message: string) => void
  text: (key: string) => string
}) {
  return <details open={settingsOpen} onToggle={event => onSettingsOpen(event.currentTarget.open)} className="rounded-xl border border-border p-4">
    <summary className="cursor-pointer text-sm font-medium">{text('lips.creationSettings')}</summary>
    <div className="mt-4 space-y-3">
      <fieldset disabled={busy} className="flex flex-wrap gap-4 text-sm">
        <legend className="mb-2 text-xs text-text-secondary">{text('lips.createFrom')}</legend>
        <label className="inline-flex items-center gap-2"><input type="radio" name={`lips-source-${kit.id}`} checked={!withReference} onChange={() => onMode('description')} />{text('lips.descriptionOnly')}</label>
        <label className="inline-flex items-center gap-2"><input type="radio" name={`lips-source-${kit.id}`} checked={withReference} onChange={() => onMode('reference')} />{text('lips.withReference')}</label>
      </fieldset>
      <label className="block text-xs text-text-secondary">{text('lips.style')}<textarea rows={2} maxLength={1500} value={kit.lookNotes || ''} disabled={busy} onChange={event => onNotes(event.target.value)} placeholder={text('lips.styleHint')} className="mt-2 w-full rounded-lg border border-border bg-bg-primary p-2 text-sm" /></label>
      <label className="block text-xs text-text-secondary">{text('lips.imageModel')}<select value={imageModel} disabled={busy} onChange={event => onModel(event.target.value)} className={`${control} mt-2 w-full`}>
        <LipsModelOptions models={imageModels} empty={text('lips.noImageModel')} />
      </select></label>
      {withReference ? <LipsReferenceFields kit={kit} busy={busy} characters={characters} referenceCharacter={referenceCharacter} workspace={workspace} onReferenceCharacter={onReferenceCharacter} onReferenceFile={onReferenceFile} onError={onError} text={text} /> : <p className="text-xs text-text-muted">{text('lips.descriptionHint')}</p>}
      {needsReference && <p className="text-xs text-amber-200">{text('lips.needsReference')}</p>}
    </div>
  </details>
}

function LipsModelOptions({ models, empty }: { models: { model_type: string; name: string }[]; empty: string }) {
  return <>
    {!models.length && <option value="">{empty}</option>}
    {models.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
  </>
}

function LipsReferenceFields({ kit, busy, characters, referenceCharacter, workspace, onReferenceCharacter, onReferenceFile, onError, text }: {
  kit: CharacterKit; busy: boolean; characters: CharacterKit[]; referenceCharacter: string; workspace: string
  onReferenceCharacter: (id: string) => void; onReferenceFile: (file: File) => void; onError: (message: string) => void
  text: (key: string) => string
}) {
  return <>
    <label className="block text-xs text-text-secondary">{text('lips.referenceCharacter')}<select value={referenceCharacter} disabled={busy} className={`${control} mt-2 w-full`} onChange={event => onReferenceCharacter(event.target.value)}>
      <option value="">{text('lips.chooseCharacter')}</option>
      {characters.filter(item => item.base).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </select></label>
    <label className="block text-xs text-text-secondary">{text('lips.uploadReference')}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onReferenceFile(file) }} className="mt-2 block w-full text-xs" /></label>
    <LabsLibraryPick workspace={workspace} disabled={busy} onFile={file => onReferenceFile(file)} onError={onError} />
    {kit.base && <img src={kit.base.source} alt={text('lips.reference')} className="h-24 max-w-full rounded-lg border border-border object-contain" />}
  </>
}

export function LipsBatchProgress({ index, total, completed, errors, text }: {
  index: number; total: number; completed: number; errors: Partial<Record<CharacterMouthState, string>>
  text: (key: string, values?: Record<string, string | number>) => string
}) {
  return <div data-testid="lips-batch-progress" className="space-y-2 rounded-lg border border-border p-3 text-sm">
    <p>{text('lips.batchProgress', { index, total, count: completed })}</p>
    <progress aria-label={text('lips.batchProgressLabel')} value={completed + Object.keys(errors).length} max={total} className="h-2 w-full accent-cyan-400" />
    {Object.entries(errors).map(([state, detail]) => <p key={state} className="text-xs text-amber-200">{text('lips.batchMouthFailed', { mouth: text(`faceRig.states.${state}`), error: detail || '' })}</p>)}
  </div>
}

export function LipsMouthGrid({ draft, selected, liveState, busy, onSelect, text }: {
  draft: LipsDraft; selected: CharacterMouthState; liveState: CharacterMouthState | undefined; busy: boolean
  onSelect: (state: CharacterMouthState) => void; text: (key: string) => string
}) {
  return <div className="grid grid-cols-3 gap-2">
    {CHARACTER_MOUTH_STATES.map(state => <MouthTile key={state} draft={draft} state={state} selected={selected === state} live={liveState === state} busy={busy} onSelect={onSelect} text={text} />)}
  </div>
}

function MouthTile({ draft, state, selected, live, busy, onSelect, text }: {
  draft: LipsDraft; state: CharacterMouthState; selected: boolean; live: boolean; busy: boolean
  onSelect: (state: CharacterMouthState) => void; text: (key: string) => string
}) {
  const asset = draft.candidates[state] ?? draft.kit.mouth[state]
  const sounds = MOUTH_SOUND_GROUPS.filter(sound => mouthStateForSound(sound, draft.kit.mouthMapping) === state)
  const border = selected ? 'border-cyan-400 bg-cyan-400/5' : live ? 'border-amber-300' : 'border-border bg-bg-secondary'
  return <button type="button" aria-pressed={selected} disabled={busy} onClick={() => onSelect(state)}
    className={`relative rounded-xl border p-2 text-left transition-colors disabled:opacity-60 ${border}`}>
    <div className="flex h-14 items-center justify-center overflow-hidden rounded bg-bg-primary">{asset ? <img src={asset.source} alt="" className="max-h-12 max-w-[85%] object-contain" /> : <PlusMouth />}</div>
    <span className="mt-2 block truncate text-xs font-medium">{text(`faceRig.states.${state}`)}</span>
    <span className="mt-1 block min-h-4 truncate text-[10px] text-text-muted">{sounds.map(sound => text(`lips.sounds.${sound}`)).join(' · ') || '—'}</span>
    {asset?.reviewState === 'approved' && !draft.candidates[state] && <Check size={12} className="absolute right-2 top-2 text-emerald-300" />}
    {draft.candidates[state] && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-amber-300" />}
  </button>
}

export function LipsMouthDetail({ draft, selected, candidate, existing, busy, canGenerate, onPrompt, onGenerate, onUpload, onClean, onAccept, onDiscard, text }: {
  draft: LipsDraft; selected: CharacterMouthState; candidate: CharacterKitAsset | undefined; existing: CharacterKitAsset | undefined
  busy: boolean; canGenerate: boolean; onPrompt: (prompt: string) => void; onGenerate: () => void; onUpload: (file: File) => void
  onClean: () => void; onAccept: () => void; onDiscard: () => void; text: (key: string) => string
}) {
  const comparing = Boolean(candidate && existing?.reviewState === 'approved')
  return <section className="space-y-3 rounded-xl border border-border bg-bg-secondary p-4">
    <h3 className="font-medium">{text(`faceRig.states.${selected}`)}</h3>
    <div className={`grid gap-3 ${comparing ? 'grid-cols-2' : 'grid-cols-1'}`}>
      {comparing && existing && <div><p className="mb-2 text-xs text-text-muted">{text('lips.current')}</p><MouthImage source={existing.source} /></div>}
      <div><p className="mb-2 text-xs text-text-muted">{text(candidate ? 'lips.candidate' : 'lips.current')}</p><MouthImage source={(candidate ?? existing)?.source} /></div>
    </div>
    <input aria-label={text('lips.mouthInstruction')} placeholder={text('lips.mouthInstructionHint')} disabled={busy} maxLength={500} value={draft.kit.mouthPrompts?.[selected] || ''}
      onChange={event => onPrompt(event.target.value)} className={`${control} w-full`} />
    <MouthActions busy={busy} canGenerate={canGenerate} replace={Boolean(existing || candidate)} onGenerate={onGenerate} onUpload={onUpload} text={text} />
    {candidate && <LipsCandidateActions candidate={candidate} busy={busy} onClean={onClean} onAccept={onAccept} onDiscard={onDiscard} text={text} />}
  </section>
}

function MouthActions({ busy, canGenerate, replace, onGenerate, onUpload, text }: {
  busy: boolean; canGenerate: boolean; replace: boolean; onGenerate: () => void; onUpload: (file: File) => void; text: (key: string) => string
}) {
  const label = replace ? 'lips.regenerate' : 'lips.generateMouth'
  return <div className="flex flex-wrap gap-2">
    <button type="button" disabled={busy || !canGenerate} onClick={onGenerate} className={`${control} inline-flex items-center gap-2`}><WandSparkles size={14} />{text(label)}</button>
    <label className={`${control} inline-flex cursor-pointer items-center gap-2 ${busy ? 'opacity-40' : ''}`}><Upload size={14} />{text('lips.uploadMouth')}<input type="file" accept="image/png,image/webp,image/jpeg" className="sr-only" disabled={busy} onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onUpload(file) }} /></label>
  </div>
}

function LipsCandidateActions({ candidate, busy, onClean, onAccept, onDiscard, text }: {
  candidate: CharacterKitAsset; busy: boolean; onClean: () => void; onAccept: () => void; onDiscard: () => void; text: (key: string) => string
}) {
  const opaque = candidate.alphaStatus !== 'transparent' && !candidate.facePatch
  return <div className="space-y-2">
    {opaque && <button type="button" disabled={busy} onClick={onClean} className={`${control} w-full`}>{text('lips.removeBackground')}</button>}
    <div className="flex gap-2">
      <button type="button" disabled={busy || opaque} onClick={onAccept} className="min-h-10 flex-1 rounded-lg bg-emerald-400/15 px-3 text-sm text-emerald-200 disabled:opacity-40">{text('lips.accept')}</button>
      <button type="button" disabled={busy} onClick={onDiscard} className={control}>{text('lips.discard')}</button>
    </div>
  </div>
}

export function LipsPlacement({ kit, selected, busy, onAnchor, onPlaceAll, text }: {
  kit: CharacterKit; selected: CharacterMouthState; busy: boolean
  onAnchor: (field: 'offsetX' | 'offsetY' | 'scale', value: number) => void
  onPlaceAll: () => void; text: (key: string) => string
}) {
  const anchor = faceRigAnchorFor(kit, 'base', selected)
  return <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm">{text('lips.placement')}</summary>
    <div className="mt-3 space-y-3">{(['offsetX', 'offsetY', 'scale'] as const).map(field => <label key={field} className="block text-xs text-text-secondary">{text(`lips.anchor.${field}`)}
      <input type="range" aria-label={text(`lips.anchor.${field}`)} min={field === 'scale' ? .01 : -45} max={field === 'scale' ? .5 : 45} step={field === 'scale' ? .001 : .5} value={anchor[field]} disabled={busy} className="mt-2 w-full" onChange={event => onAnchor(field, Number(event.target.value))} />
    </label>)}
      <button type="button" disabled={busy} className={control} onClick={onPlaceAll}>{text('lips.placeAll')}</button>
    </div>
  </details>
}

export function LipsAssignments({ kit, preview, busy, onStandard, onAssign, text }: {
  kit: CharacterKit; preview: CharacterKit; busy: boolean
  onStandard: () => void; onAssign: (sound: string, state: CharacterMouthState) => void
  text: (key: string, values?: Record<string, string>) => string
}) {
  return <section className="space-y-3 rounded-xl border border-border bg-bg-secondary p-4">
    <div className="flex items-center justify-between gap-3"><h3 className="font-medium">{text('lips.assignments')}</h3>
      <button type="button" disabled={busy} onClick={onStandard} className="text-xs text-cyan-300">{text('lips.standard')}</button></div>
    <p className="text-xs text-text-muted">{text('lips.assignmentsHint')}</p>
    <div className="space-y-2">{MOUTH_SOUND_GROUPS.map(sound => <SoundAssignment key={sound} sound={sound} kit={kit} preview={preview} busy={busy} onAssign={onAssign} text={text} />)}</div>
  </section>
}

function SoundAssignment({ sound, kit, preview, busy, onAssign, text }: {
  sound: string; kit: CharacterKit; preview: CharacterKit; busy: boolean
  onAssign: (sound: string, state: CharacterMouthState) => void
  text: (key: string, values?: Record<string, string>) => string
}) {
  const state = mouthStateForSound(sound, kit.mouthMapping)
  const asset = preview.mouth[state]
  const label = text('lips.assignSound', { sound: text(`lips.sounds.${sound}`) })
  return <label className="flex items-center gap-3 text-sm"><span className="w-16 shrink-0">{text(`lips.sounds.${sound}`)}</span>
    <span className="flex h-8 w-9 shrink-0 items-center justify-center rounded bg-bg-primary">{asset && <img src={asset.source} alt="" className="max-h-7 max-w-8 object-contain" />}</span>
    <select aria-label={label} value={state} disabled={busy} className={`${control} min-w-0 flex-1`} onChange={event => onAssign(sound, event.target.value as CharacterMouthState)}>
      {CHARACTER_MOUTH_STATES.map(item => <option key={item} value={item}>{text(`faceRig.states.${item}`)}</option>)}
    </select></label>
}

export function LipsLinkCharacter({ characters, target, busy, ready, onTarget, onApply, text }: {
  characters: CharacterKit[]; target: string; busy: boolean; ready: boolean
  onTarget: (id: string) => void; onApply: () => void; text: (key: string) => string
}) {
  return <details className="rounded-xl border border-border p-4"><summary className="cursor-pointer text-sm font-medium">{text('lips.linkCharacter')}</summary>
    <div className="mt-3 space-y-3"><p className="text-xs text-text-muted">{text('lips.linkHint')}</p>
      <select aria-label={text('lips.targetCharacter')} value={target} disabled={busy} onChange={event => onTarget(event.target.value)} className={`${control} w-full`}>
        <option value="">{text('lips.chooseCharacter')}</option>
        {characters.filter(kit => kit.base).map(kit => <option key={kit.id} value={kit.id}>{kit.name}</option>)}
      </select>
      <button type="button" disabled={busy || !target || !ready} className={`${control} w-full`} onClick={onApply}>{text('lips.apply')}</button>
      {!ready && <p className="text-xs text-amber-200">{text('lips.approveBeforeLink')}</p>}
    </div>
  </details>
}

function MouthImage({ source }: { source?: string }) {
  return <div className="flex h-32 items-center justify-center overflow-hidden rounded-xl bg-bg-primary p-4">{source ? <img src={source} alt="" className="max-h-full max-w-full object-contain" /> : <PlusMouth />}</div>
}

function PlusMouth() { return <span className="text-xl font-light text-text-muted">+</span> }
