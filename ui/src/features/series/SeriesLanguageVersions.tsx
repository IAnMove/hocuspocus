import { useMemo, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import {
  deleteSeriesLanguageVersion, saveSeriesLanguageVersion, startSeriesEpisodeAssembly, translateSeriesLanguageVersion,
} from '../../api/series'
import { SPOKEN_LANGUAGES, spokenLanguage, type SpokenLanguage } from '../../lib/speechLanguage'
import { checkedWrite, episodeCards, machineMarks, type EpisodeCard, type MachineMarks, type VersionCardText } from './languageVersionMarks'
import { SeriesServerRender } from './SeriesServerRender'
import { useSeriesStore } from './store'
import { primaryButton, secondaryButton } from './styles'
import type { SeriesEpisode, SeriesLanguageVersion, SeriesProject } from './types'

type Line = { id: string; shotId: string; speaker: string; text: string }
type Step = 'translate' | 'create' | 'save' | 'check' | 'assemble' | 'remove'
type VersionWrite = { title?: string; dialogue?: Record<string, string>; cards?: Record<string, VersionCardText> }
const languageKeys = (versions: Record<string, unknown>) => Object.keys(versions) as SpokenLanguage[]
const field = 'w-full rounded border border-border bg-bg-primary p-1'
type Requester = 'user' | 'agent' | 'wizard' | 'server'
const REQUESTERS: readonly string[] = ['user', 'agent', 'wizard', 'server'] satisfies Requester[]

/** What Save lines sends: the edited lines, and the cards and title only when they were edited. */
function draftWrite(drafts: Record<string, string>, cards: Record<string, VersionCardText>, title: string | null): VersionWrite {
  return { dialogue: drafts, ...(Object.keys(cards).length ? { cards } : {}), ...(title === null ? {} : { title }) }
}

function missingLines(lines: Line[], version: SeriesLanguageVersion | undefined, drafts: Record<string, string>): number {
  return version ? lines.filter(line => !(drafts[line.id] ?? version.dialogue[line.id])?.trim()).length : 0
}

function episodeLines(episode: SeriesEpisode): Line[] {
  return episode.shots.flatMap(shot => shot.dialogueBeats.filter(beat => beat.text.trim())
    .map(beat => ({ id: beat.id, shotId: shot.id, speaker: beat.characterId, text: beat.text })))
}

/** Dub an episode: same shots and line ids, its own lines, voices, takes and cut per language. Machine translations
 *  are marked until a person edits them or marks them checked. */
export function SeriesLanguageVersions({ workspace, series, episode }: { workspace: string; series: SeriesProject; episode: SeriesEpisode }) {
  const { t } = useUiTranslation('seriesLab')
  const reload = useSeriesStore(state => state.reload)
  const original = spokenLanguage(series.spokenLanguage || series.language)
  const versions = episode.languageVersions ?? {}
  const [selected, setSelected] = useState<SpokenLanguage | ''>(languageKeys(versions)[0] ?? '')
  const [adding, setAdding] = useState<SpokenLanguage | ''>('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [cardDrafts, setCardDrafts] = useState<Record<string, VersionCardText>>({})
  const [titleDraft, setTitleDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState<Step | ''>(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const lines = useMemo(() => episodeLines(episode), [episode])
  const cards = useMemo(() => episodeCards(episode), [episode])
  const version = selected ? versions[selected] : undefined
  const marks = machineMarks(version)
  const missing = missingLines(lines, version, drafts)
  const patch = draftWrite(drafts, cardDrafts, titleDraft)
  const edited = Object.keys(drafts).length + Object.keys(cardDrafts).length + Number('title' in patch)

  const clearDrafts = () => { setDrafts({}); setCardDrafts({}); setTitleDraft(null) }
  const run = async (label: Step, task: () => Promise<void>) => {
    setBusy(label); setError(''); setMessage('')
    try { await task(); await reload() } catch (cause) { setError((cause as Error).message) } finally { setBusy('') }
  }
  const create = (translate: boolean) => adding && run(translate ? 'translate' : 'create', async () => {
    const reply = translate
      ? await translateSeriesLanguageVersion(workspace, series.id, episode.id, adding)
      : await saveSeriesLanguageVersion(workspace, series.id, episode.id, adding, { title: episode.title })
    setSelected(adding); setAdding(''); clearDrafts()
    setMessage(t('languages.created', { missing: reply.missingLines.length }))
  })
  // A person's write clears the machine-translation mark of each text it sends (the server decides who wrote it).
  const write = (label: 'save' | 'check', patch: VersionWrite) => run(label, async () => {
    const reply = await saveSeriesLanguageVersion(workspace, series.id, episode.id, selected, patch)
    clearDrafts()
    setMessage(label === 'check' ? t('languages.machine.checked') : t('languages.saved', { missing: reply.missingLines.length }))
  })
  const save = () => write('save', patch)
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
        aria-pressed={language === selected} onClick={() => { setSelected(language); clearDrafts() }}>{t(`languages.names.${language}`)}</button>)}
      {available.length > 0 && <AddLanguage available={available} adding={adding} blocked={blocked} onChoose={setAdding} onCreate={translate => void create(translate)} />}
    </div>
    {version && <div className="space-y-2">
      <MachineSummary marks={marks} blocked={blocked} onCheckAll={() => void write('check', checkedWrite(version, marks))} />
      <VersionTitle version={version} draft={titleDraft} marked={marks.title} blocked={blocked} onChange={setTitleDraft}
        onCheck={() => void write('check', { title: version.title ?? '' })} />
      <table className="w-full text-xs"><tbody>
        {lines.map(line => <tr key={line.id} className="align-top">
          <td className="w-20 py-1 font-mono text-text-muted">{line.shotId}</td>
          <td className="w-1/3 py-1 pr-2 text-text-secondary"><span className="font-semibold">{line.speaker}:</span> {line.text}</td>
          <td className="py-1"><textarea aria-label={t('languages.lineLabel', { id: line.id })} rows={2} disabled={blocked} className={field}
            value={drafts[line.id] ?? version.dialogue[line.id] ?? ''} onChange={event => setDrafts(current => ({ ...current, [line.id]: event.target.value }))} />
            <MachineMark marked={marks.lines.has(line.id) && drafts[line.id] === undefined} blocked={blocked} label={line.id}
              onCheck={() => void write('check', { dialogue: { [line.id]: version.dialogue[line.id] } })} /></td>
        </tr>)}
      </tbody></table>
      <VersionCards cards={cards} version={version} drafts={cardDrafts} marks={marks} blocked={blocked}
        onChange={(shotId, text) => setCardDrafts(current => ({ ...current, [shotId]: text }))}
        onCheck={shotId => void write('check', { cards: { [shotId]: version.cards[shotId] } })} />
      <p className="text-xs">{t('languages.missing', { count: missing })}</p>
      <div className="flex flex-wrap gap-2">
        <button className={primaryButton} disabled={blocked || !edited} onClick={() => void save()}>{t('languages.save')}</button>
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

/** How many texts are still machine translations, and who asked for them; checking all is a person's decision. */
function MachineSummary({ marks, blocked, onCheckAll }: { marks: MachineMarks; blocked: boolean; onCheckAll: () => void }) {
  const { t } = useUiTranslation('seriesLab')
  if (!marks.count) return null
  const by = (REQUESTERS.includes(marks.requestedBy) ? marks.requestedBy : 'user') as Requester
  return <div role="note" data-testid="series-machine-translation" className="flex flex-wrap items-center gap-2 rounded border border-amber-400/30 bg-amber-400/10 p-2 text-xs text-amber-100">
    <span className="mr-auto">{t('languages.machine.summary', { count: marks.count, by: t(`languages.machine.by.${by}`) })}</span>
    <button type="button" className={secondaryButton} disabled={blocked} onClick={onCheckAll}>{t('languages.machine.checkAll')}</button>
  </div>
}

/** The badge of one machine-translated text, with the button that marks it checked as it is. */
function MachineMark({ marked, blocked, label, onCheck }: { marked: boolean; blocked: boolean; label: string; onCheck: () => void }) {
  const { t } = useUiTranslation('seriesLab')
  if (!marked) return null
  return <span className="mt-1 flex flex-wrap items-center gap-2" data-machine-translated={label}>
    <span title={t('languages.machine.badgeTitle')} className="rounded border border-amber-400/40 bg-amber-400/10 px-1 text-[10px] text-amber-200">
      {t('languages.machine.badge')}</span>
    <button type="button" className="text-[10px] text-text-secondary underline hover:text-text-primary disabled:opacity-40" disabled={blocked}
      aria-label={t('languages.machine.checkLabel', { id: label })} onClick={onCheck}>{t('languages.machine.check')}</button>
  </span>
}

function VersionTitle({ version, draft, marked, blocked, onChange, onCheck }: {
  version: SeriesLanguageVersion; draft: string | null; marked: boolean; blocked: boolean
  onChange: (title: string) => void; onCheck: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  return <div className="text-xs">
    <label className="block">{t('languages.versionTitle')}
      <input className={`mt-1 ${field}`} disabled={blocked} value={draft ?? version.title ?? ''} onChange={event => onChange(event.target.value)} /></label>
    <MachineMark marked={marked && draft === null} blocked={blocked} label="title" onCheck={onCheck} />
  </div>
}

/** The title and end cards: the original's text beside the version's, each with its machine-translation mark. */
function VersionCards({ cards, version, drafts, marks, blocked, onChange, onCheck }: {
  cards: EpisodeCard[]; version: SeriesLanguageVersion; drafts: Record<string, VersionCardText>; marks: MachineMarks; blocked: boolean
  onChange: (shotId: string, text: VersionCardText) => void; onCheck: (shotId: string) => void
}) {
  const { t } = useUiTranslation('seriesLab')
  if (!cards.length) return null
  return <div className="space-y-2" data-testid="series-version-cards">
    <h4 className="text-xs font-semibold">{t('languages.cards')}</h4>
    {cards.map(card => {
      const text = drafts[card.shotId] ?? version.cards[card.shotId] ?? { title: '', body: '' }
      return <div key={card.shotId} className="grid gap-2 text-xs md:grid-cols-[5rem_1fr_1fr]">
        <span className="font-mono text-text-muted">{card.shotId}</span>
        <span className="text-text-secondary">{[card.title, card.body].filter(Boolean).join(' · ')}</span>
        <span className="space-y-1">
          <input aria-label={t('languages.cardTitleLabel', { id: card.shotId })} className={field} disabled={blocked} value={text.title}
            onChange={event => onChange(card.shotId, { ...text, title: event.target.value })} />
          <input aria-label={t('languages.cardBodyLabel', { id: card.shotId })} className={field} disabled={blocked} value={text.body}
            onChange={event => onChange(card.shotId, { ...text, body: event.target.value })} />
          <MachineMark marked={marks.cards.has(card.shotId) && !drafts[card.shotId]} blocked={blocked} label={card.shotId}
            onCheck={() => onCheck(card.shotId)} />
        </span>
      </div>
    })}
  </div>
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
