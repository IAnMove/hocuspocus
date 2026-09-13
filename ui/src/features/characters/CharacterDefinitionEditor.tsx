import { useEffect, useRef, useState } from 'react'
import { fetchCharacterKitLibrary, saveCharacterKit } from '../../api/characters'
import { fetchOutputs, type ApiOutput } from '../../api/client'
import { createCharacterKit, type CharacterKit, type CharacterKitLibrary } from '../../lib/characterKit'
import { useUiTranslation } from '../../i18n'
import { AssetInput } from '../asset-picker/AssetInput'
import type { Scene3DSlot } from '../scene3d/types'
import { sourceRefFromOutput } from '../scene3d/slotSource'
import { characterFromSlot, characterSlotPatch } from '../scene3d/speech/characterBinding'
import { modelDigest } from '../scene3d/speech/profiles'
import { CharacterVoiceFields } from './CharacterVoiceFields'
import type { CharacterVoice } from '../../lib/characterVoice'
import { randomUuid } from '../../lib/uuid'
import { CharacterDefinitionSpeechTools } from './CharacterDefinitionSpeechTools'
import type { CharacterDefinitionDraft } from './characterEditorHandoff'

type Props = { workspace: string; slot?: Scene3DSlot; disabled?: boolean;
  lockIdentity?: boolean; spacious?: boolean; onDirtyChange?: (dirty: boolean) => void;
  initialDraft?: CharacterDefinitionDraft; onDraftChange?: (draft: CharacterDefinitionDraft) => void;
  initialKit?: CharacterKit; onSaved?: (kit: CharacterKit) => void | Promise<void>;
  onApply?: (patch: Partial<Scene3DSlot>) => void; onBusyChange?: (busy: boolean) => void }

function initialDefinition(workspace: string, slot?: Scene3DSlot, kit?: CharacterKit) {
  const character = slot?.character
  if (character) return { id: character.kitRef?.workspace === workspace ? character.kitRef.id : '', name: character.name, voice: character.voice }
  return { id: kit?.id ?? '', name: kit?.name ?? '', voice: kit?.voice }
}
function definitionKit(library: CharacterKitLibrary | undefined, id: string, seed?: CharacterKit) {
  const saved = library?.kits[id]
  if (seed?.id !== id) return saved
  return saved ? { ...saved, base: saved.base ?? seed.base, identityReference: saved.identityReference ?? seed.identityReference } : seed
}
function canSaveDefinition(library: CharacterKitLibrary | undefined, name: string, slot: Scene3DSlot | undefined) {
  if (!library || !name.trim()) return false
  return slot ? Boolean(slot.speech?.face && slot.sourceRef) : true
}
async function definitionForSave(workspace: string, name: string, voice: CharacterVoice | undefined, kit: CharacterKit | undefined, slot: Scene3DSlot | undefined, model: ApiOutput | undefined) {
  const previous = kit ?? { ...createCharacterKit(name), id: randomUuid() }
  let next: CharacterKit = { ...previous, name: name.trim(), voice, updatedAt: new Date().toISOString() }
  if (slot) next = { ...await characterFromSlot(next, { ...slot, character: { id: slot.character?.id ?? slot.id, name, voice } }), voice }
  else if (model) {
    const ref = sourceRefFromOutput(model, workspace), digest = await modelDigest(ref.url)
    next = { ...next, speech3d: { model: ref, digest, settings: digest === kit?.speech3d?.digest ? kit.speech3d.settings : undefined } }
  }
  return next
}
function DefinitionModelInput({ slot, kit, items, model, workspace, onChoose }: { slot?: Scene3DSlot; kit?: CharacterKit; items: ApiOutput[]; model?: ApiOutput; workspace: string; onChoose: (item: ApiOutput | undefined) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  if (slot) return null
  return <details><summary className="cursor-pointer">{t('speech.optionalModel')}</summary><AssetInput label={t('speech.optionalModel')} placeholder={kit?.speech3d?.model.filename ?? t('speech.optionalModel')}
    items={items} value={model} accept=".glb,model/gltf-binary" workspaceId={workspace} constraints={{ kinds: ['model3d'], maxCount: 1, optional: false }}
    onChoose={item => onChoose(item ?? undefined)} /></details>
}
function DefinitionIdentity({ library, initialKit, id, disabled, onSelect }: {
  library?: CharacterKitLibrary; initialKit?: CharacterKit; id: string; disabled?: boolean
  onSelect: (id: string, kit?: CharacterKit) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <label className="block">{t('speech.savedCharacter')}<select data-testid="saved-character" value={id} disabled={disabled}
    className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary px-2"
    onChange={event => onSelect(event.target.value, library?.kits[event.target.value])}>
    <option value="">{t('speech.newCharacter')}</option>
    {initialKit && !library?.kits[initialKit.id] && <option value={initialKit.id}>{initialKit.name}</option>}
    {Object.values(library?.kits ?? {}).map(item => <option key={item.id} value={item.id}>{item.name}{item.speech3d ? ' · 3D' : ' · 2D'}</option>)}
  </select></label>
}
/** One authoritative Character Kit library, shared by Characters and the native 3D inspector. */
export function CharacterDefinitionEditor(props: Props) {
  return <ScopedDefinition key={props.workspace + '/' + (props.slot?.id ?? props.initialKit?.id ?? '')} {...props} />
}
function ScopedDefinition({ workspace, slot, disabled, initialKit, onSaved, onApply, onBusyChange, onDirtyChange, lockIdentity, spacious, initialDraft, onDraftChange }: Props) {
  const { t } = useUiTranslation('scene3dEditor')
  const [library, setLibrary] = useState<CharacterKitLibrary>()
  const initial = { ...initialDefinition(workspace, slot, initialKit), ...initialDraft }
  const [id, setId] = useState(initial.id)
  const [name, setName] = useState(initial.name)
  const [voice, setVoice] = useState(initial.voice)
  const [model, setModel] = useState<ApiOutput | undefined>(initialDraft?.model), [items, setItems] = useState<ApiOutput[]>([])
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState('')
  const [workshopDirty, setWorkshopDirty] = useState(false), [workshopBusy, setWorkshopBusy] = useState(false)
  const alive = useRef(true)
  const hasSlot = Boolean(slot)
  const kit = definitionKit(library, id, initialKit)
  const dirty = Boolean(kit && (name !== kit.name || JSON.stringify(voice) !== JSON.stringify(kit.voice) || model))
  useEffect(() => { onBusyChange?.(busy || workshopBusy); return () => onBusyChange?.(false) }, [busy, workshopBusy, onBusyChange])
  useEffect(() => { onDirtyChange?.(dirty || workshopDirty); return () => onDirtyChange?.(false) }, [dirty, workshopDirty, onDirtyChange])
  useEffect(() => { onDraftChange?.({ name, voice, model }) }, [name, voice, model, onDraftChange])
  useEffect(() => {
    alive.current = true
    void fetchCharacterKitLibrary(workspace).then(result => { if (alive.current) setLibrary(result) })
      .catch(error => { if (alive.current) setNotice(error.message) })
    if (!hasSlot) void fetchOutputs(200, 0, { workspace, mediaType: 'model3d' }).then(result => {
      if (alive.current) setItems(result.outputs.filter(item => item.type === 'model3d'))
    }).catch(error => { if (alive.current) setNotice(error.message) })
    return () => { alive.current = false }
  }, [workspace, hasSlot])
  const run = (task: () => Promise<void>) => {
    setBusy(true); setNotice('')
    void task().catch(error => { if (alive.current) setNotice(error.message) }).finally(() => { if (alive.current) setBusy(false) })
  }
  return <section data-testid="character-definition" className={`rounded-lg border border-cyan-400/30 bg-bg-secondary ${spacious ? 'space-y-6 p-6 text-sm' : 'space-y-2 p-3 text-xs'}`}>
    <h3 className="font-semibold text-text-primary">{t('speech.characterDefinition')}</h3>
    <p className="text-text-muted">{t('speech.definitionHint')}</p>
    <fieldset disabled={disabled || busy || !library} className={spacious ? 'space-y-6' : 'space-y-2'}>
      <DefinitionIdentity library={library} initialKit={initialKit} id={id} disabled={lockIdentity || workshopDirty || workshopBusy}
        onSelect={(nextId, next) => {
          setId(nextId); setNotice('')
          if (!slot) { setName(next?.name ?? ''); setVoice(next?.voice); setModel(undefined) }
        }} />
      {slot && <button data-testid="apply-character" className="min-h-10 rounded border border-border px-3" disabled={!kit?.speech3d}
        onClick={() => run(async () => {
          const patch = await characterSlotPatch(kit!, workspace, library!.revision, slot)
          if (alive.current) { setVoice(kit!.voice); setName(kit!.name); onApply?.(patch); setNotice(t('speech.characterApplied')) }
        })}>{t('speech.useCharacter')}</button>}
      <label className="block">{t('speech.definitionName')}<input data-testid="character-name" maxLength={240}
        className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary px-2" value={name} onChange={e => setName(e.target.value)} /></label>
      <DefinitionModelInput slot={slot} kit={kit} items={items} model={model} workspace={workspace} onChoose={setModel} />
      <CharacterVoiceFields value={voice} onChange={next => {
        setVoice(next)
        if (slot) onApply?.({ character: { id: slot.character?.id ?? slot.id, name: slot.character?.name ?? name, ...slot.character, voice: next } })
      }} />
      <button data-testid="save-character" className="min-h-10 rounded border border-border px-3"
        disabled={workshopDirty || workshopBusy || !canSaveDefinition(library, name, slot)}
        onClick={() => run(async () => {
          const next = await definitionForSave(workspace, name, voice, kit, slot, model)
          if (!alive.current) return
          const saved = await saveCharacterKit(workspace, library!, next)
          if (!alive.current) return
          setLibrary(saved); setId(next.id); setModel(undefined); setNotice(t('speech.characterSaved'))
          await onSaved?.(saved.kits[next.id])
          if (slot) onApply?.({ character: { id: slot.character?.id ?? slot.id, name: next.name, kitRef: { id: next.id, workspace }, libraryRevision: saved.revision, voice } })
        })}>{busy ? t('speech.busy') : t('speech.saveCharacter')}</button>
      <button className="min-h-10 px-2 underline" disabled={workshopDirty || workshopBusy} onClick={() => run(async () => {
        const saved = await fetchCharacterKitLibrary(workspace)
        if (!alive.current) return
        setLibrary(saved); setNotice(t('speech.libraryReloaded'))
        if (lockIdentity) {
          const restored = saved.kits[id] ?? initialKit
          setName(restored?.name ?? ''); setVoice(restored?.voice); setModel(undefined)
        }
      })}>{t('speech.reloadLibrary')}</button>
      {!slot && <CharacterDefinitionSpeechTools workspace={workspace} kit={library?.kits[id]}
        disabled={busy || dirty} onDirtyChange={setWorkshopDirty} onBusyChange={setWorkshopBusy}
        onSaved={saved => run(async () => { setLibrary(saved); await onSaved?.(saved.kits[id]) })} />}
      {!slot && kit?.speech3d && <button data-testid="edit-character-face" className="min-h-10 rounded border border-border px-3" onClick={() => run(async () => {
        const patch = await characterSlotPatch(kit, workspace, library!.revision)
        if (!alive.current) return
        const { buildSpeechProduction } = await import('../scene3d/speech/production')
        const { openSpeechProduction } = await import('../scene3d/speech/prepareProduction')
        const doc = buildSpeechProduction({ kind: 'dialogue', title: kit.name, workspace, duration: 5, offset: 0,
          cast: [{ id: kit.id, name: kit.name, model: kit.speech3d!.model }] })
        doc.slots[0] = { ...doc.slots[0], ...patch }
        if (alive.current) openSpeechProduction(doc)
      })}>{t('speech.editCharacterFace')}</button>}
    </fieldset>
    {notice && <p role="status">{notice}</p>}
  </section>
}
