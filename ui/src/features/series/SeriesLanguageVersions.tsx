import { useMemo, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import {
  deleteSeriesLanguageVersion, saveSeriesLanguageVersion, startSeriesEpisodeAssembly, translateSeriesLanguageVersion,
} from '../../api/series'
import { SPOKEN_LANGUAGES, spokenLanguage, type SpokenLanguage } from '../../lib/speechLanguage'
import { SeriesServerRender } from './SeriesServerRender'
import { useSeriesStore } from './store'
import { primaryButton, secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

type Line = { id: string; shotId: string; speaker: string; text: string }
type Step = 'translate' | 'create' | 'save' | 'assemble' | 'remove'
const languageKeys = (versions: Record<string, unknown>) => Object.keys(versions) as SpokenLanguage[]

function episodeLines(episode: SeriesEpisode): Line[] {
  return episode.shots.flatMap(shot => shot.dialogueBeats.filter(beat => beat.text.trim())
    .map(beat => ({ id: beat.id, shotId: shot.id, speaker: beat.characterId, text: beat.text })))
}

/** Dub an episode: same shots and line ids, its own lines, voices, takes and cut per language. */
export function SeriesLanguageVersions({ workspace, series, episode }: { workspace: string; series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const reload = useSeriesStore(state => state.reload)
  const original = spokenLanguage(series.spokenLanguage || series.language)
  const versions = episode.languageVersions ?? {}
  const [selected, setSelected] = useState<SpokenLanguage | ''>(languageKeys(versions)[0] ?? '')
  const [adding, setAdding] = useState<SpokenLanguage | ''>('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState<Step | ''>(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const lines = useMemo(() => episodeLines(episode), [episode])
  const version = selected ? versions[selected] : undefined
  const missing = version ? lines.filter(line => !(drafts[line.id] ?? version.dialogue[line.id])?.trim()).length : 0

  const run = async (label: Step, task: () => Promise<void>) => {
    setBusy(label); setError(''); setMessage('')
    try { await task(); await reload() } catch (cause) { setError((cause as Error).message) } finally { setBusy('') }
  }
  const create = (translate: boolean) => adding && run(translate ? 'translate' : 'create', async () => {
    const reply = translate
      ? await translateSeriesLanguageVersion(workspace, series.id, episode.id, adding)
      : await saveSeriesLanguageVersion(workspace, series.id, episode.id, adding, { title: episode.title })
    setSelected(adding); setAdding(''); setDrafts({})
    setMessage(t('languages.created', { missing: reply.missingLines.length }))
  })
  const save = () => run('save', async () => {
    const reply = await saveSeriesLanguageVersion(workspace, series.id, episode.id, selected, { dialogue: drafts })
    setDrafts({}); setMessage(t('languages.saved', { missing: reply.missingLines.length }))
  })
  const assemble = () => run('assemble', async () => {
    await startSeriesEpisodeAssembly(workspace, series.id, episode.id, { language: selected, burnSubtitles: true })
    setMessage(t('languages.assembling'))
  })
  const remove = () => run('remove', async () => {
    await deleteSeriesLanguageVersion(workspace, series.id, episode.id, selected)
    setSelected('')
  })

  const available = SPOKEN_LANGUAGES.filter(language => language !== original && !versions[language])
  const blocked = Boolean(busy)
  return <section aria-label={t('languages.title')} className="space-y-3 rounded-lg border border-border p-3" data-testid="series-language-versions">
    <h3 className="text-sm font-semibold">{t('languages.title')}</h3>
    <p className="text-xs text-text-secondary">{t('languages.hint', { original: original ? t(`languages.names.${original}`) : series.spokenLanguage })}</p>
    <div className="flex flex-wrap items-end gap-2">
      {languageKeys(versions).map(language => <button key={language} className={language === selected ? primaryButton : secondaryButton}
        aria-pressed={language === selected} onClick={() => { setSelected(language); setDrafts({}) }}>{t(`languages.names.${language}`)}</button>)}
      {available.length > 0 && <AddLanguage available={available} adding={adding} blocked={blocked} onChoose={setAdding} onCreate={translate => void create(translate)} />}
    </div>
    {version && <div className="space-y-2">
      <table className="w-full text-xs"><tbody>
        {lines.map(line => <tr key={line.id} className="align-top">
          <td className="w-20 py-1 font-mono text-text-muted">{line.shotId}</td>
          <td className="w-1/3 py-1 pr-2 text-text-secondary"><span className="font-semibold">{line.speaker}:</span> {line.text}</td>
          <td className="py-1"><textarea aria-label={t('languages.lineLabel', { id: line.id })} rows={2} disabled={blocked}
            className="w-full rounded border border-border bg-bg-primary p-1"
            value={drafts[line.id] ?? version.dialogue[line.id] ?? ''} onChange={event => setDrafts(current => ({ ...current, [line.id]: event.target.value }))} /></td>
        </tr>)}
      </tbody></table>
      <p className="text-xs">{t('languages.missing', { count: missing })}</p>
      <div className="flex flex-wrap gap-2">
        <button className={primaryButton} disabled={blocked || !Object.keys(drafts).length} onClick={() => void save()}>{t('languages.save')}</button>
        <button className={secondaryButton} disabled={blocked} onClick={() => void assemble()}>{t('languages.assemble')}</button>
        <button className={secondaryButton} disabled={blocked} onClick={() => void remove()}>{t('languages.remove')}</button>
      </div>
      {missing === 0 && <SeriesServerRender key={`server-${selected}`} workspace={workspace} series={series} episode={episode} language={selected} />}
    </div>}
    {busy && <p role="status" className="text-xs">{t(`languages.busy.${busy}`)}</p>}
    {message && <p role="status" className="text-xs text-emerald-200">{message}</p>}
    {error && <p role="alert" className="text-xs text-red-300">{error}</p>}
  </section>
}

function AddLanguage({ available, adding, blocked, onChoose, onCreate }: {
  available: SpokenLanguage[]; adding: SpokenLanguage | ''; blocked: boolean
  onChoose: (language: SpokenLanguage | '') => void; onCreate: (translate: boolean) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  return <>
    <label className="text-xs">{t('languages.add')}
      <select className="ml-1 min-h-10 rounded border border-border bg-bg-primary px-2" value={adding} disabled={blocked}
        onChange={event => onChoose(event.target.value as SpokenLanguage | '')}>
        <option value="">{t('languages.choose')}</option>
        {available.map(language => <option key={language} value={language}>{t(`languages.names.${language}`)}</option>)}
      </select></label>
    <button className={secondaryButton} disabled={!adding || blocked} onClick={() => onCreate(true)}>{t('languages.translate')}</button>
    <button className={secondaryButton} disabled={!adding || blocked} onClick={() => onCreate(false)}>{t('languages.empty')}</button>
  </>
}
