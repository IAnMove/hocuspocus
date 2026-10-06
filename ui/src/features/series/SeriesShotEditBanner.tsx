import { useState, type ReactNode } from 'react'
import { ArrowLeft, Film, Loader2, Save, X } from 'lucide-react'
import type { ApiOutput } from '../../api/client'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import {
  exportEditorTake, importExportAsTake, recentExports, returnToShot, setShotEditSession, useShotEditSession, type ShotEditSession,
} from './shotEditSession'
import { saveScene3DPlan } from './inspector/scene3dPlan'

const button = 'inline-flex min-h-9 items-center gap-1.5 rounded border border-border px-3 py-1 text-xs disabled:opacity-40'

type Run = (task: () => Promise<void>) => Promise<void>

/** How the edited result goes back: a 2D take exported as the shot's take, a 3D plan saved to the shot, or a recent export. */
function ResultActions({ session, mediaFilter, busy, run, onChoices, onDone }: {
  session: ShotEditSession; mediaFilter: string; busy: boolean; run: Run; onChoices: (items: ApiOutput[]) => void; onDone: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const spinner = (icon: ReactNode) => busy ? <Loader2 size={13} className="animate-spin" /> : icon
  if (session.target === 'plan') {
    return session.dimension === '3d' && mediaFilter === 'world3d'
      ? <button type="button" className={button} disabled={busy} onClick={() => void run(async () => { await saveScene3DPlan(session) })}>
        {spinner(<Save size={13} />)}{t('approval.editor.savePlan')}</button> : null
  }
  return <>
    {session.dimension === '2d' && mediaFilter === 'scene3d' && <button type="button" className={button} disabled={busy}
      onClick={() => void run(async () => { await exportEditorTake(session); onDone() })}>{spinner(<Film size={13} />)}{t('approval.editor.exportTake')}</button>}
    <button type="button" className={button} disabled={busy} onClick={() => void run(async () => onChoices(await recentExports(session)))}>{t('approval.editor.chooseExport')}</button>
  </>
}

function RecentExports({ session, choices, busy, run, onDone }: { session: ShotEditSession; choices: ApiOutput[]; busy: boolean; run: Run; onDone: () => void }) {
  const { t } = useUiTranslation('seriesLab')
  return <div className="flex w-full flex-wrap gap-2" aria-label={t('approval.editor.recent')}>
    {!choices.length && <p className="text-xs text-text-muted">{t('approval.editor.noExports')}</p>}
    {choices.map(item => <button key={item.name} type="button" className="flex w-40 flex-col gap-1 rounded border border-border p-1 text-left text-[10px] disabled:opacity-40"
      disabled={busy} onClick={() => void run(async () => { await importExportAsTake(session, item); onDone() })}>
      {item.thumbnail_url && <img src={item.thumbnail_url} alt="" className="aspect-video w-full rounded object-cover" />}
      <span className="truncate">{t('approval.editor.useThis', { name: item.name })}</span>
    </button>)}
  </div>
}

/** While a Series shot is open in an editor: send the edited result back to that shot as a take (or a 3D shot's plan), or go back to it. */
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
  return <div role="region" aria-label={t('approval.editor.title', { order: session.order })} className="z-50 flex shrink-0 flex-wrap items-center gap-2 border-b border-violet-500/40 bg-bg-secondary p-2 text-sm">
    <strong className="mr-auto min-w-0 truncate">{t(session.target === 'plan' ? 'approval.editor.planTitle' : 'approval.editor.title', { order: session.order })} · {session.episodeTitle}</strong>
    <ResultActions session={session} mediaFilter={mediaFilter} busy={busy} run={run} onChoices={setChoices} onDone={done} />
    <button type="button" className={button} disabled={busy} onClick={() => returnToShot(session)}><ArrowLeft size={13} />{t('approval.editor.back')}</button>
    <button type="button" className={button} disabled={busy} aria-label={t('approval.editor.discard')} title={t('approval.editor.discard')} onClick={() => setShotEditSession(null)}><X size={13} /></button>
    {choices && <RecentExports session={session} choices={choices} busy={busy} run={run} onDone={done} />}
    {error && <p role="alert" className="w-full text-xs text-red-300">{error}</p>}
  </div>
}
