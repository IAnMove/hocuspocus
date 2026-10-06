import { useState } from 'react'
import { ArrowLeft, Film, Loader2, X } from 'lucide-react'
import type { ApiOutput } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import {
  exportEditorTake, importExportAsTake, recentExports, returnToShot, setShotEditSession, useShotEditSession,
} from './shotEditSession'

const button = 'inline-flex min-h-9 items-center gap-1.5 rounded border border-border px-3 py-1 text-xs disabled:opacity-40'

/** While a Series shot is open in an editor: send the edited result back to that shot as a take, or go back to it. */
export function SeriesShotEditBanner() {
  const { t } = useUiTranslation('seriesLab')
  const session = useShotEditSession(state => state.session)
  const mediaFilter = useStore(state => state.mediaFilter)
  const workspace = useStore(state => state.activeWorkspace)
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const [choices, setChoices] = useState<ApiOutput[] | null>(null)
  if (!session || session.workspace !== workspace || mediaFilter === 'series') return null
  const run = async (task: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await task() } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  const done = () => { setChoices(null); returnToShot(session) }
  const inEditor = session.dimension === '2d' && mediaFilter === 'scene3d'
  return <div role="region" aria-label={t('approval.editor.title', { order: session.order })} className="z-50 flex shrink-0 flex-wrap items-center gap-2 border-b border-violet-500/40 bg-bg-secondary p-2 text-sm">
    <strong className="mr-auto min-w-0 truncate">{t('approval.editor.title', { order: session.order })} · {session.episodeTitle}</strong>
    {inEditor && <button type="button" className={button} disabled={busy} onClick={() => void run(async () => { await exportEditorTake(session); done() })}>
      {busy ? <Loader2 size={13} className="animate-spin" /> : <Film size={13} />}{t('approval.editor.exportTake')}</button>}
    <button type="button" className={button} disabled={busy} onClick={() => void run(async () => setChoices(await recentExports(session)))}>{t('approval.editor.chooseExport')}</button>
    <button type="button" className={button} disabled={busy} onClick={() => returnToShot(session)}><ArrowLeft size={13} />{t('approval.editor.back')}</button>
    <button type="button" className={button} disabled={busy} aria-label={t('approval.editor.discard')} title={t('approval.editor.discard')} onClick={() => setShotEditSession(null)}><X size={13} /></button>
    {choices && <div className="flex w-full flex-wrap gap-2" aria-label={t('approval.editor.recent')}>
      {!choices.length && <p className="text-xs text-text-muted">{t('approval.editor.noExports')}</p>}
      {choices.map(item => <button key={item.name} type="button" className="flex w-40 flex-col gap-1 rounded border border-border p-1 text-left text-[10px] disabled:opacity-40"
        disabled={busy} onClick={() => void run(async () => { await importExportAsTake(session, item); done() })}>
        {item.thumbnail_url && <img src={item.thumbnail_url} alt="" className="aspect-video w-full rounded object-cover" />}
        <span className="truncate">{t('approval.editor.useThis', { name: item.name })}</span>
      </button>)}
    </div>}
    {error && <p role="alert" className="w-full text-xs text-red-300">{error}</p>}
  </div>
}
