import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import type { CharacterKit } from '../../lib/characterKit'
import type { CharacterKitRef } from '../../lib/characterVoice'
import { speechPreparationReadiness } from '../../lib/characterSpeechPreparation'
import { CharacterKitLink } from '../characters/CharacterKitLink'
import { useCharacterKitLibrary } from '../characters/useCharacterKitLibrary'
import { openSeriesCharacterEditor } from './seriesCharacterEditor'
import type { SeriesCharacter, SeriesProject } from './types'
import { secondaryButton } from './styles'

export function SeriesCharacterSpeech({ workspace, series, character, onPatch, saveNow }: {
  workspace: string; series: SeriesProject; character: SeriesCharacter
  onPatch: (patch: Record<string, unknown>) => void; saveNow: () => Promise<unknown>
}) {
  const { t } = useUiTranslation('seriesLab')
  const { kits, error: libraryError } = useCharacterKitLibrary(workspace)
  const ref = character.voiceProfile?.characterKitRef
  const kit = ref?.workspace === workspace ? kits.find(item => item.id === ref.id) : undefined
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
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
      await openSeriesCharacterEditor(workspace, series.id, character.id)
    } catch (cause) { if (alive.current) setError((cause as Error).message) }
    finally { operation.current = false; if (alive.current) setBusy(false) }
  }
  return <section aria-label={t('speech.characterTitle', { name: character.name })} className="mt-3 space-y-2 rounded-lg border border-cyan-500/30 p-3">
    <h4 className="text-xs font-semibold">{t('speech.title')}</h4>
    <CharacterSpeechStatus kit={kit} />
    <button type="button" className={secondaryButton} disabled={busy}
      onClick={() => void configure()}>{t('speech.openCreator')}</button>
    <div className="space-y-1"><p className="text-xs text-text-muted">{t('speech.linkExisting')}</p>
      <CharacterKitLink workspace={workspace} value={ref} kits={kits} error={libraryError} disabled={busy}
        onChange={next => { void link(next).catch(cause => setError(cause.message)) }} />
    </div>
    <p className="text-[11px] text-text-muted">{t('speech.reuseHint')}</p>
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
