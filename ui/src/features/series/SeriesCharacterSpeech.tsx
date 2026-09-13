import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { fetchCharacterKitLibrary } from '../../api/characters'
import type { CharacterKit } from '../../lib/characterKit'
import type { CharacterKitRef } from '../../lib/characterVoice'
import { speechPreparationReadiness } from '../../lib/characterSpeechPreparation'
import { CharacterKitLink } from '../characters/CharacterKitLink'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'
import { seriesCharacterKit } from './seriesCharacterKit'
import type { SeriesCharacter, SeriesProject } from './types'
import { secondaryButton } from './styles'

const Definition = lazy(() => import('../characters/CharacterDefinitionEditor').then(module => ({ default: module.CharacterDefinitionEditor })))

export function SeriesCharacterSpeech({ workspace, series, character, onPatch, saveNow }: {
  workspace: string; series: SeriesProject; character: SeriesCharacter
  onPatch: (patch: Record<string, unknown>) => void; saveNow: () => Promise<unknown>
}) {
  const { t } = useUiTranslation('seriesLab')
  const { kits, error: libraryError, reload } = useCharacterKitLibrary(workspace)
  const ref = character.voiceProfile?.characterKitRef
  const kit = ref?.workspace === workspace ? kits.find(item => item.id === ref.id) : undefined
  const [editing, setEditing] = useState<CharacterKit>(), [busy, setBusy] = useState(false), [error, setError] = useState('')
  const alive = useRef(true), operation = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const link = async (next: CharacterKitRef | undefined) => {
    onPatch({ characterKitRef: next })
    await saveNow()
  }
  const configure = async () => {
    if (operation.current) return
    operation.current = true; setBusy(true); setError('')
    try {
      await saveNow()
      const library = await fetchCharacterKitLibrary(workspace)
      if (ref && (ref.workspace !== workspace || !library.kits[ref.id])) throw new Error(t('speech.missingLink'))
      const selected = seriesCharacterKit(workspace, series, character, ref ? library.kits[ref.id] : undefined)
      if (alive.current) setEditing(selected)
    } catch (cause) { if (alive.current) setError((cause as Error).message) }
    finally { operation.current = false; if (alive.current) setBusy(false) }
  }
  return <section aria-label={t('speech.characterTitle', { name: character.name })} className="mt-3 space-y-2 rounded-lg border border-cyan-500/30 p-3">
    <h4 className="text-xs font-semibold">{t('speech.title')}</h4>
    <CharacterSpeechStatus kit={kit} />
    <button type="button" className={secondaryButton} disabled={busy} aria-expanded={Boolean(editing)}
      onClick={() => { if (editing) { setEditing(undefined); reload() } else void configure() }}>{t(editing ? 'speech.close' : kit ? 'speech.edit' : 'speech.configure')}</button>
    <details><summary className="cursor-pointer text-xs text-text-muted">{t('speech.linkExisting')}</summary>
      <CharacterKitLink workspace={workspace} value={ref} kits={kits} error={libraryError} disabled={busy || Boolean(editing)}
        onChange={next => { void link(next).catch(cause => setError(cause.message)) }} />
    </details>
    <p className="text-[11px] text-text-muted">{t('speech.reuseHint')}</p>
    {editing && <Suspense fallback={<p role="status">{t('speech.loading')}</p>}><Definition workspace={workspace} initialKit={editing}
      onBusyChange={setBusy} onSaved={async saved => { if (!alive.current) return; await link({ workspace, id: saved.id }); reload() }} /></Suspense>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </section>
}

function CharacterSpeechStatus({ kit }: { kit?: CharacterKit }) {
  const { t } = useUiTranslation('seriesLab')
  const ready2d = kit && speechPreparationReadiness(kit, 'base').complete
  return <ul className="flex flex-wrap gap-3 text-xs">
    <li>{t('speech.voice')}: {kit?.voice?.voiceId || t('speech.pending')}</li>
    <li>{t('speech.lipsync2d')}: {t(ready2d ? 'speech.ready' : 'speech.pending')}</li>
    <li>{t('speech.lipsync3d')}: {t(kit?.speech3d?.settings?.face ? 'speech.ready' : 'speech.pending')}</li>
  </ul>
}
