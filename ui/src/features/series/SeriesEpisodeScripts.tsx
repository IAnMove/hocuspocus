import { useEffect, useState } from 'react'
import { Download, Eye, EyeOff, RotateCcw } from 'lucide-react'
import { SeriesRequestError } from '../../api/series'
import {
  getSeriesEpisodeScript, listSeriesEpisodeScripts, rewriteSeriesEpisodeFromScript, seriesEpisodeScriptDownloadUrl,
  type SeriesScriptRecord, type SeriesScriptRevision,
} from '../../api/seriesScripts'
import { ConfirmDialog } from '../../components/common/ConfirmDialog'
import { useUiTranslation } from '../../i18n'
import { formatAppTimestamp } from '../../lib/locale'
import { Pill, SectionCard } from './components'
import { secondaryButton } from './styles'
import type { SeriesEpisode, SeriesProject } from './types'

const AUTHORS = new Set(['user', 'agent', 'wizard', 'server'])

function problemsOf(cause: unknown): string[] {
  const detail = cause instanceof SeriesRequestError ? cause.detail as { problems?: unknown } | undefined : undefined
  return Array.isArray(detail?.problems) ? detail.problems.filter((item): item is string => typeof item === 'string') : []
}

/**
 * The scripts an agent (or anyone) wrote this episode from with `series.episode.from_script`, exactly as they were
 * sent: who and when, view, download, and write the episode again from one. Nothing shows until there is one.
 */
export function SeriesEpisodeScripts({ workspace, series, episode, saveNow, reload }: {
  workspace: string; series: SeriesProject; episode: SeriesEpisode
  saveNow: () => Promise<unknown>; reload: () => Promise<void>
}) {
  const { t } = useUiTranslation('seriesLab')
  const [revisions, setRevisions] = useState<SeriesScriptRevision[]>([])
  const [shown, setShown] = useState<SeriesScriptRecord | null>(null)
  const [confirming, setConfirming] = useState<number | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [message, setMessage] = useState('')
  const [problems, setProblems] = useState<string[]>([])
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const abort = new AbortController()
    listSeriesEpisodeScripts(workspace, series.id, episode.id, abort.signal)
      .then(found => { if (!abort.signal.aborted) setRevisions(found) })
      .catch(cause => { if (!abort.signal.aborted && (cause as Error).name !== 'AbortError') setError((cause as Error).message) })
    return () => abort.abort()
  }, [workspace, series.id, episode.id, tick])
  useEffect(() => { setShown(null); setMessage(''); setError(''); setProblems([]) }, [episode.id])

  const act = async (task: () => Promise<void>) => {
    setBusy(true); setError(''); setMessage(''); setProblems([])
    try { await task() } catch (cause) { setError((cause as Error).message); setProblems(problemsOf(cause)) } finally { setBusy(false) }
  }
  const toggle = (revision: number) => shown?.revision === revision ? setShown(null)
    : void act(async () => setShown(await getSeriesEpisodeScript(workspace, series.id, episode.id, revision)))
  const rewrite = (revision: number) => act(async () => {
    setConfirming(null)
    await saveNow()
    await rewriteSeriesEpisodeFromScript(workspace, series.id, episode.id, revision, true)
    const reply = await rewriteSeriesEpisodeFromScript(workspace, series.id, episode.id, revision)
    await reload()
    setTick(value => value + 1)
    setMessage(t('scripts.rewritten', { revision, current: reply.scriptRevision ?? revision }))
  })

  if (!revisions.length && !error) return null
  return <SectionCard title={t('scripts.title')} description={t('scripts.description')}>
    <ul className="space-y-2" data-testid="series-episode-scripts">
      {revisions.map(item => <ScriptRow key={item.revision} item={item} open={shown?.revision === item.revision} busy={busy}
        downloadUrl={seriesEpisodeScriptDownloadUrl(workspace, series.id, episode.id, item.revision)}
        onToggle={() => toggle(item.revision)} onRewrite={() => setConfirming(item.revision)} />)}
    </ul>
    {shown && <pre data-testid="series-script-viewer" aria-label={t('scripts.viewerLabel', { revision: shown.revision })}
      className="mt-3 max-h-96 overflow-auto rounded-lg border border-border bg-bg-primary p-3 text-[11px] leading-relaxed text-text-secondary">
      {JSON.stringify(shown.script, null, 2)}</pre>}
    {message && <p role="status" className="mt-2 text-xs text-emerald-200">{message}</p>}
    {error && <div role="alert" className="mt-2 text-xs text-red-300"><p>{error}</p>
      {problems.length > 0 && <ul className="mt-1 list-disc pl-4">{problems.map(problem => <li key={problem}>{problem}</li>)}</ul>}</div>}
    {confirming !== null && <ConfirmDialog title={t('scripts.confirmTitle', { revision: confirming })} message={t('scripts.confirmMessage')}
      confirmLabel={t('scripts.confirm')} onCancel={() => setConfirming(null)} onConfirm={() => void rewrite(confirming)} />}
  </SectionCard>
}

function ScriptRow({ item, open, busy, downloadUrl, onToggle, onRewrite }: {
  item: SeriesScriptRevision; open: boolean; busy: boolean; downloadUrl: string; onToggle: () => void; onRewrite: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const by = AUTHORS.has(item.by) ? item.by : 'user'
  return <li data-testid={`series-script-${item.revision}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-bg-primary p-2 text-xs">
    <span className="font-medium text-text-primary">{t('scripts.revision', { revision: item.revision })}</span>
    <Pill tone={by === 'user' ? 'blue' : 'violet'}><span data-script-by={by}>{t(`scripts.by.${by}`)}</span></Pill>
    <span className="text-text-muted">{formatAppTimestamp(Date.parse(item.submittedAt)) || item.submittedAt}</span>
    <span className="text-text-secondary">{t('scripts.shots', { count: item.shots })}{item.languages.length ? ` · ${item.languages.join(' · ')}` : ''}</span>
    {item.restoredFrom ? <span className="text-text-muted">{t('scripts.restoredFrom', { revision: item.restoredFrom })}</span> : null}
    {item.created ? <span className="text-text-muted">{t('scripts.created')}</span> : null}
    {item.applied > 1 ? <span className="text-text-muted">{t('scripts.applied', { count: item.applied })}</span> : null}
    <span className="ml-auto flex flex-wrap gap-1">
      <button type="button" className={secondaryButton} disabled={busy} aria-pressed={open} onClick={onToggle}>
        {open ? <EyeOff size={13} /> : <Eye size={13} />}{t(open ? 'scripts.hide' : 'scripts.view')}</button>
      <a className={secondaryButton} href={downloadUrl} download><Download size={13} />{t('scripts.download')}</a>
      <button type="button" className={secondaryButton} disabled={busy} onClick={onRewrite}><RotateCcw size={13} />{t('scripts.rewrite')}</button>
    </span>
  </li>
}
