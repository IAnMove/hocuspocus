import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../../i18n'
import { useStore } from '../../../stores/useStore'
import { fetchOutputs, type ApiOutput } from '../../../api/client'
import { AssetInput } from '../../asset-picker/AssetInput'
import { sourceRefFromOutput } from '../slotSource'
import type { Scene3DSourceRef } from '../types'
import type { SpeechProductionInput } from './production'
import { speechInput, SpeechNumber } from './FaceControls'
import { CharacterKitLink } from '../../characters/CharacterKitLink'
import { useCharacterKitLibrary } from '../../characters/useCharacterKitLibrary'
import { fetchCharacterKitLibrary } from '../../../api/characters'
import type { CharacterKitRef } from '../../../lib/characterVoice'
import { characterSlotPatch, speechCastIsReady } from './characterBinding'

type ProductionEntryProps = {
  kind: SpeechProductionInput['kind']; title: string; sourceId?: string; audio?: Scene3DSourceRef
  cast?: { id: string; name: string; characterKitRef?: CharacterKitRef }[]; lines?: SpeechProductionInput['lines']; workspace?: string
  castOptions?: { id: string; name: string; characterKitRef?: CharacterKitRef }[]
  onConfigureCharacter?: (id: string) => void
}
export function SpeechProductionEntry(props: ProductionEntryProps) {
  const active = useStore(s => s.activeWorkspace), workspace = props.workspace ?? active
  return <ScopedSpeechProductionEntry key={workspace + '/' + (props.sourceId ?? props.title)} {...props} workspace={workspace} />
}
function ScopedSpeechProductionEntry({ kind, title, sourceId, audio, cast: initialCast = [{ id: 'speaker', name: '' }], castOptions, lines, workspace, onConfigureCharacter }: ProductionEntryProps & { workspace: string }) {
  const { t } = useUiTranslation('scene3dEditor')
  const { kits: speech3dKits } = useCharacterKitLibrary(workspace, true)
  const [open, setOpen] = useState(false), [items, setItems] = useState<ApiOutput[]>([])
  const [models, setModels] = useState<Record<string, ApiOutput | undefined>>({})
  const [links, setLinks] = useState<Record<string, CharacterKitRef | undefined>>({})
  const [storyCharacter, setStoryCharacter] = useState('')
  const chosen = castOptions?.find(character => character.id === storyCharacter)
  const cast = chosen ? [chosen] : initialCast
  const [voice, setVoice] = useState<ApiOutput | undefined>()
  const [offset, setOffset] = useState(0), [duration, setDuration] = useState(8)
  const [phonetic, setPhonetic] = useState(true), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const job = useRef<AbortController | null>(null)
  useEffect(() => {
    let live = true
    if (open) void Promise.all([fetchOutputs(200, 0, { mediaType: 'model3d', workspace }), fetchOutputs(200, 0, { mediaType: 'audio', workspace })])
      .then(results => { if (live) setItems(results.flatMap(r => r.outputs)) }).catch(() => {})
    return () => { live = false; job.current?.abort() }
  }, [workspace, open])
  const source = voice ? sourceRefFromOutput(voice, workspace) : audio
  const value = voice ?? audioOutput(audio)
  return <details className="my-3 rounded-xl border border-border bg-bg-secondary p-3" onToggle={e => {
    setOpen(e.currentTarget.open)
    if (!e.currentTarget.open) { job.current?.abort(); setBusy(false) }
  }}>
    <summary className="cursor-pointer text-sm font-medium text-text-primary">{t('speech.productionEntry')}</summary>
    {open && <fieldset disabled={busy} className="mt-3 space-y-3 text-xs">
      <p>{t('speech.productionHint')}</p>
      <ProductionCharacterSelect options={castOptions} value={storyCharacter}
        onChange={id => { setStoryCharacter(id); setLinks({}); setModels({}) }} />
      {cast.length > 2 ? <p role="alert">{t('speech.twoSpeakers')}</p> : cast.map(character => <div key={character.id} className="space-y-2">
        {onConfigureCharacter && <button type="button" className="min-h-10 rounded border border-border px-3" onClick={() => onConfigureCharacter(character.id)}>{t('speech.configureLibraryCharacter', { name: character.name })}</button>}
        <CharacterKitLink workspace={workspace} requireSpeech3d value={Object.hasOwn(links, character.id) ? links[character.id] : character.characterKitRef}
          disabled={busy} onChange={ref => { setLinks(previous => ({ ...previous, [character.id]: ref })); setModels(previous => ({ ...previous, [character.id]: undefined })) }} />
        <AssetInput
        label={character.name || t('speech.character')} placeholder={t('speech.chooseModel')} items={items.filter(i => i.type === 'model3d')} value={models[character.id]}
        accept=".glb,model/gltf-binary" workspaceId={workspace} disabled={busy} constraints={{ kinds: ['model3d'], maxCount: 1, optional: false }}
        onChoose={item => { setModels(previous => ({ ...previous, [character.id]: item ?? undefined })); if (item) setLinks(previous => ({ ...previous, [character.id]: undefined })) }} /></div>)}
      <AssetInput label={t('speech.voice')} placeholder={t('speech.pickVoice')} items={items.filter(i => i.type === 'audio')} value={value} accept="audio/*"
        workspaceId={workspace} disabled={busy} constraints={{ kinds: ['audio'], maxCount: 1, optional: false }} onChoose={item => setVoice(item ?? undefined)} />
      <SpeechNumber label={t('speech.offset')} value={offset} min={0} max={599} step={.1} onChange={setOffset} />
      <SpeechNumber label={t('duration')} value={duration} min={.1} max={90} step={.1} onChange={setDuration} />
      <label className="flex items-center gap-2"><input type="checkbox" checked={phonetic} onChange={e => setPhonetic(e.target.checked)} />{t('speech.analyze')}</label>
      <p className="text-text-muted">{t('speech.phoneticHint')}</p>
      {!phonetic && <p className="text-amber-200">{t('speech.amplitudeHint')}</p>}
      {!source && <p className="text-text-muted">{t('speech.textOnlyProduction')}</p>}
      <button type="button" className={speechInput} disabled={busy || !speechCastIsReady(cast, models, links, speech3dKits)}
        onClick={() => {
          setBusy(true); setError(''); job.current = new AbortController()
          const captured = job.current
          void import('./prepareProduction').then(async ({ prepareSpeechProduction, openSpeechProduction }) => {
            const resolved = await Promise.all(cast.map(async c => {
              const ref = Object.hasOwn(links, c.id) ? links[c.id] : c.characterKitRef
              if (!ref) return { ...c, model: sourceRefFromOutput(models[c.id]!, workspace) }
              const library = await fetchCharacterKitLibrary(ref.workspace), kit = library.kits[ref.id]
              if (!kit) throw new Error(t('speech.missingCharacter'))
              const patch = await characterSlotPatch(kit, ref.workspace, library.revision)
              return { ...c, model: patch.sourceRef!, character: patch.character, settings: patch.speech }
            }))
            captured.signal.throwIfAborted()
            const document = await prepareSpeechProduction({ kind, title, sourceId, workspace, audio: source, duration, offset, lines,
              cast: resolved }, phonetic, captured.signal)
            if (!captured.signal.aborted) openSpeechProduction(document)
          }).catch(reason => { if (!captured.signal.aborted) setError(reason.message) }).finally(() => { if (!captured.signal.aborted) setBusy(false) })
        }}>{busy ? t('speech.busy') : t('speech.openProduction')}</button>
      {error && <p role="alert" className="text-red-300">{error}</p>}
    </fieldset>}
  </details>
}

function audioOutput(audio?: Scene3DSourceRef): ApiOutput | undefined {
  return audio ? { name: audio.filename, url: audio.url, type: 'audio', mode: null, size: 0, created_at: 0, thumbnail_url: '', workspace_id: audio.workspaceId } : undefined
}
function ProductionCharacterSelect({ options, value, onChange }: { options: ProductionEntryProps['castOptions']; value: string; onChange: (id: string) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!options?.length) return null
  return <label className="block">{t('speech.sourceCharacter')}<select className={speechInput + ' w-full'} value={value} onChange={e => onChange(e.target.value)}>
    <option value="">{t('speech.manualCharacter')}</option>
    {options.map(character => <option key={character.id} value={character.id}>{character.name}</option>)}
  </select></label>
}
