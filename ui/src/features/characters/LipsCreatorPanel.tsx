import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Plus } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { fetchLipsLibrary, saveLipsPack, LIPS_LIBRARY_UPDATED } from '../../api/lipsCreator'
import { fetchCharacterKitLibrary, saveCharacterKit } from '../../api/characters'
import { createLipsPack, applyLipsPack } from '../../lib/lipsCreator'
import { emptyCharacterKitLibrary, nextCharacterKitId, type CharacterKit, type CharacterKitLibrary } from '../../lib/characterKit'
import { LipsThumbnail } from './LipsThumbnail'
import { LipsPackEditor, type LipsDraft } from './LipsPackEditor'

/** Keep unfinished edits across studio tab changes, scoped to the owning workspace. */
const drafts = new Map<string, LipsDraft>()

export function LipsCreatorPanel({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const workspace = useStore(state => state.activeWorkspace)
  return <LipsCreatorWorkspace key={workspace} workspace={workspace} onBusyChange={onBusyChange} />
}

function LipsCreatorWorkspace({ workspace, onBusyChange }: { workspace: string; onBusyChange?: (busy: boolean) => void }) {
  const { t } = useUiTranslation('characters')
  const [library, setLibrary] = useState<CharacterKitLibrary>()
  const libraryRef = useRef<CharacterKitLibrary | undefined>(undefined)
  const [editorBusy, setEditorBusy] = useState(false)
  const [characters, setCharacters] = useState<CharacterKitLibrary>(emptyCharacterKitLibrary)
  const [error, setError] = useState(''), [version, setVersion] = useState(0)
  const [selected, setSelected] = useState<string>(), [hovered, setHovered] = useState<string>()
  useEffect(() => { onBusyChange?.(editorBusy) }, [editorBusy, onBusyChange])
  useEffect(() => () => onBusyChange?.(false), [onBusyChange])
  useEffect(() => {
    const refresh = (event: Event) => {
      if ((event as CustomEvent<{ workspace: string }>).detail.workspace !== workspace || editorBusy || selected) return
      // A Wizard/MCP save must appear when browsing. Retain unfinished editor drafts.
      for (const [key, draft] of drafts) {
        const saved = libraryRef.current?.kits[draft.kit.id]
        if (key.startsWith(`${workspace}\0`) && saved && JSON.stringify(draft.kit) === JSON.stringify(saved)) drafts.delete(key)
      }
      setVersion(value => value + 1)
    }
    window.addEventListener(LIPS_LIBRARY_UPDATED, refresh)
    return () => window.removeEventListener(LIPS_LIBRARY_UPDATED, refresh)
  }, [workspace, editorBusy, selected])
  useEffect(() => {
    const abort = new AbortController()
    void fetchLipsLibrary(workspace, abort.signal).then(value => {
      if (!abort.signal.aborted) { libraryRef.current = value; setLibrary(value) }
    }).catch(cause => {
      if (!abort.signal.aborted) setError((cause as Error).message)
    })
    void fetchCharacterKitLibrary(workspace).then(value => { if (!abort.signal.aborted) setCharacters(value) }).catch(() => {})
    return () => abort.abort()
  }, [workspace, version])
  const keyFor = (id: string) => `${workspace}\0${id}`
  const open = (id?: string, character?: CharacterKit) => {
    if (!library) return
    const key = id || '@new'
    if (character) {
      const pack = { ...character, id: nextCharacterKitId(character.name, Object.keys(library.kits)), poses: {}, eyes: {},
        provenance: [{ method: 'lips-creator-import', characterId: character.id }], updatedAt: new Date().toISOString() }
      drafts.set(keyFor(key), { kit: pack, candidates: {} })
    } else if (!drafts.has(keyFor(key))) {
      const kit = id ? library.kits[id] : createLipsPack(t('lips.untitled'), Object.keys(library.kits))
      drafts.set(keyFor(key), { kit, candidates: kit.mouthCandidates || {} })
    }
    setSelected(key)
  }
  const save = async (kit: CharacterKit, signal: AbortSignal) => {
    const current = libraryRef.current
    if (!current) throw new Error(t('lips.loading'))
    signal.throwIfAborted()
    const candidates = kit.mouthCandidates ?? drafts.get(keyFor(selected || '@new'))?.candidates ?? {}
    const normalized = { ...kit, mouthCandidates: candidates, name: kit.name.trim(), lookNotes: kit.lookNotes?.replace(/\s+/g, ' ').trim(), updatedAt: new Date().toISOString() }
    const saved = await saveLipsPack(workspace, current, normalized)
    libraryRef.current = saved
    signal.throwIfAborted()
    setLibrary(saved)
    drafts.delete(keyFor(selected || '@new'))
    drafts.set(keyFor(kit.id), { kit: saved.kits[kit.id], candidates })
    setSelected(kit.id)
  }
  const link = async (pack: CharacterKit, id: string) => {
    const fresh = await fetchCharacterKitLibrary(workspace)
    if (!fresh.kits[id]) throw new Error(t('lips.characterUnavailable'))
    setCharacters(await saveCharacterKit(workspace, fresh, applyLipsPack(pack, fresh.kits[id])))
  }
  const draft = selected ? drafts.get(keyFor(selected)) : undefined
  const packs = library ? Object.values(library.kits).sort((a, b) => a.name.localeCompare(b.name)) : []
  const importable = Object.values(characters.kits).filter(kit => Object.keys(kit.mouth).length
    && !packs.some(pack => pack.provenance.some(item => item.method === 'lips-creator-import' && item.characterId === kit.id)))
  return <section data-testid="lips-creator" className="mx-auto w-full max-w-6xl space-y-6 pb-8">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><h2 className="text-xl font-semibold">Lips Creator</h2><p className="mt-1 text-sm text-text-muted">{t(selected ? 'lips.editorHint' : 'lips.collectionHint')}</p></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={editorBusy} title={t('lips.reloadHint')} onClick={() => {
          if (selected) { const id = drafts.get(keyFor(selected))?.kit.id; drafts.delete(keyFor(selected)); if (id) drafts.delete(keyFor(id)) }
          setSelected(undefined); setError(''); setVersion(value => value + 1)
        }} className="min-h-10 rounded-lg border border-border px-3 text-sm disabled:opacity-40">{t('lips.reload')}</button>
        {selected && <button type="button" disabled={editorBusy} onClick={() => setSelected(undefined)} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3 text-sm disabled:opacity-40"><ArrowLeft size={15} />{t('lips.collection')}</button>}
      </div>
    </header>
    {error && <div role="alert" className="flex flex-wrap items-center gap-3 rounded-lg border border-red-300/30 p-3 text-sm text-red-300">{error}
      <button type="button" className="underline" onClick={() => { setError(''); setVersion(value => value + 1) }}>{t('lips.reload')}</button></div>}
    {!library && !error && <p role="status" className="text-text-muted">{t('lips.loading')}</p>}
    {selected && draft && library ? <LipsPackEditor key={draft.kit.id} workspace={workspace} initialDraft={draft}
      characters={Object.values(characters.kits)} onDraftChange={value => {
        drafts.set(keyFor(selected), value); drafts.set(keyFor(value.kit.id), value)
      }} onSave={save} onLink={link} onBusyChange={setEditorBusy} />
      : library && <>
        <div data-testid="lips-collection-grid" className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          <button type="button" onClick={() => open()} className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-cyan-400/40 bg-cyan-400/[.03] p-5 text-cyan-200 transition-colors hover:bg-cyan-400/10">
            <Plus size={35} strokeWidth={1.2} /><span className="text-base font-medium">New</span><span className="text-xs text-text-muted">{t('lips.newHint')}</span>
          </button>
          {packs.map(pack => <button key={pack.id} type="button" onClick={() => open(pack.id)} onMouseEnter={() => setHovered(pack.id)} onMouseLeave={() => setHovered(undefined)} onFocus={() => setHovered(pack.id)} onBlur={() => setHovered(undefined)}
            className="rounded-2xl border border-border bg-bg-secondary p-3 text-left transition-colors hover:border-cyan-400/40 focus-visible:outline-2 focus-visible:outline-cyan-400">
            <LipsThumbnail pack={pack} animate={hovered === pack.id} /><p className="mt-3 truncate text-sm font-medium">{pack.name}</p>
            <p className="mt-1 text-xs text-text-muted">{t('lips.createdCount', { count: new Set([...Object.keys(pack.mouth), ...Object.keys(pack.mouthCandidates || {})]).size })} · {t('lips.mouthCount', { count: Object.values(pack.mouth).filter(asset => asset?.reviewState === 'approved').length })}</p>
          </button>)}
        </div>
        {importable.length > 0 && <div className="space-y-3"><h3 className="text-sm text-text-muted">{t('lips.importFromCharacters')}</h3><div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {importable.map(kit => <button key={kit.id} type="button" onClick={() => open(undefined, kit)} className="rounded-2xl border border-border p-3 text-left hover:border-cyan-400/40">
            <LipsThumbnail pack={kit} /><p className="mt-3 text-sm">{kit.name}</p><p className="mt-1 text-xs text-text-muted">{t('lips.importEdit')}</p>
          </button>)}
        </div></div>}
      </>}
  </section>
}
