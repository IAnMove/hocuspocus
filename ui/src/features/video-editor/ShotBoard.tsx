import { useCallback, useEffect, useState } from 'react'
import { Check, Film, Loader2, Pencil, RefreshCw, Sparkles, X } from 'lucide-react'
import { getMontageShots, regenerateShot, selectShotTake, type MontageShot, type MontageShotBoard, type ShotTake } from '../../api/montages'
import { useUiTranslation } from '../../i18n'
import { openSceneOutput } from '../../lib/sceneOutput'
import { randomUuid } from '../../lib/uuid'
import { formatSlot, hasPendingTakes, sceneOutput, shortPrompt } from './shotBoardModel'

interface Props {
  workspace: string
  file: string
  /** Reload the montage into the editor after the server saved a new revision. */
  onChanged: () => Promise<void>
  onError: (message: string | null) => void
}

const button = 'inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-bg-hover disabled:opacity-50'

function TakeChip({ take, busy, onSelect }: { take: ShotTake; busy: boolean; onSelect: () => void }) {
  const { t } = useUiTranslation('videoEditor')
  const done = take.status === 'completed' && take.url
  return <div className="flex items-center gap-1.5 rounded border border-border bg-bg-tertiary/50 px-1.5 py-1 text-[11px]">
    {done ? <a href={take.url} target="_blank" rel="noreferrer" className="text-accent-blue hover:underline" title={take.provenance?.prompt}>{take.note || take.id}</a>
      : <span className="text-text-muted">{take.note || take.id}</span>}
    <span className={take.status === 'failed' ? 'text-red-300' : 'text-text-muted'}>{t(`shots.status.${take.status}`, { defaultValue: take.status })}</span>
    {done && <button type="button" className={button} disabled={busy} onClick={onSelect}><Check size={11} /> {t('shots.use')}</button>}
  </div>
}

function RegenerateForm({ shot, busy, onSubmit, onCancel }: {
  shot: MontageShot; busy: boolean; onSubmit: (prompt: string, seed?: number) => void; onCancel: () => void
}) {
  const { t } = useUiTranslation('videoEditor')
  const [prompt, setPrompt] = useState(shot.provenance.prompt ?? '')
  const [seed, setSeed] = useState('')
  return <div className="mt-2 space-y-2">
    <label className="block text-[11px] text-text-muted">{t('shots.prompt')}
      <textarea value={prompt} maxLength={4000} rows={4} onChange={event => setPrompt(event.target.value)}
        className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2 text-xs text-text-primary" />
    </label>
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-[11px] text-text-muted">{t('shots.seed')}
        <input type="number" min={0} value={seed} placeholder={t('shots.seedAuto')} onChange={event => setSeed(event.target.value)}
          className="ml-2 w-32 rounded border border-border bg-bg-tertiary px-2 py-1 text-xs" />
      </label>
      <button type="button" className={button} disabled={busy || !prompt.trim()}
        onClick={() => onSubmit(prompt.trim(), seed.trim() ? Number(seed) : undefined)}><Sparkles size={11} /> {t('shots.queue')}</button>
      <button type="button" className={button} onClick={onCancel}><X size={11} /> {t('shots.cancel')}</button>
    </div>
    <p className="text-[10px] text-text-muted">{t('shots.queueHint')}</p>
  </div>
}

function ShotCard({ shot, busy, onRegenerate, onSelect, onOpenScene }: {
  shot: MontageShot; busy: boolean; onRegenerate: (prompt: string, seed?: number) => void; onSelect: (take: ShotTake) => void
  onOpenScene: (scene: string) => void
}) {
  const { t } = useUiTranslation('videoEditor')
  const [editing, setEditing] = useState(false)
  const origin = shot.provenance
  return <article className="rounded-lg border border-border bg-bg-secondary p-2 text-xs">
    <video src={shot.url} muted preload="metadata" playsInline className="aspect-video w-full rounded bg-black object-cover"
      onMouseEnter={event => { void event.currentTarget.play().catch(() => undefined) }} onMouseLeave={event => event.currentTarget.pause()} />
    <div className="mt-1.5 flex items-baseline justify-between gap-2">
      <span className="font-medium text-text-primary">{shot.index + 1}. {shot.name}</span>
      <span className="font-mono text-[10px] text-text-muted">{formatSlot(shot.start, shot.end)}</span>
    </div>
    {shot.lyric && <p className="mt-0.5 italic text-text-secondary">“{shot.lyric}”</p>}
    <p className="mt-1 text-[11px] text-text-muted">
      {t(`shots.origin.${origin.kind}`, { defaultValue: origin.kind })}
      {origin.model ? ` · ${origin.model}` : ''}{origin.seed !== undefined ? ` · ${t('shots.seed')} ${origin.seed}` : ''}
      {origin.scene ? ` · ${origin.scene}` : ''}
    </p>
    {origin.prompt && <p className="mt-0.5 text-[11px] text-text-secondary" title={origin.prompt}>{shortPrompt(origin.prompt)}</p>}
    {origin.startImage && <a href={origin.startImage.url} target="_blank" rel="noreferrer" className="mt-0.5 block truncate text-[11px] text-accent-blue hover:underline">{t('shots.startImage')}</a>}
    {shot.takes.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{shot.takes.map(take => <TakeChip key={take.id} take={take} busy={busy} onSelect={() => onSelect(take)} />)}</div>}
    {origin.scene && <button type="button" className={`${button} mt-2`} disabled={busy} onClick={() => onOpenScene(origin.scene as string)}><Pencil size={11} /> {t('shots.openScene')}</button>}
    {origin.canRegenerate && !editing && <button type="button" className={`${button} mt-2`} disabled={busy} onClick={() => setEditing(true)}><RefreshCw size={11} /> {t('shots.regenerate')}</button>}
    {!origin.canRegenerate && <p className="mt-1.5 text-[10px] text-text-muted">{t(origin.scene ? 'shots.sceneHint' : 'shots.notRegenerable')}</p>}
    {editing && <RegenerateForm shot={shot} busy={busy} onCancel={() => setEditing(false)}
      onSubmit={(prompt, seed) => { setEditing(false); onRegenerate(prompt, seed) }} />}
  </article>
}

/** Shot-by-shot view of the open montage: provenance, takes, regenerate and pick a take. */
export function ShotBoard({ workspace, file, onChanged, onError }: Props) {
  const { t } = useUiTranslation('videoEditor')
  const [board, setBoard] = useState<MontageShotBoard | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try { setBoard(await getMontageShots(workspace, file)) } catch (error) { onError((error as Error).message) }
  }, [workspace, file, onError])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!board || !hasPendingTakes(board)) return
    const timer = window.setInterval(() => { void load() }, 8000)
    return () => window.clearInterval(timer)
  }, [board, load])

  const run = async (action: () => Promise<unknown>, reload: boolean) => {
    if (!board) return
    setBusy(true)
    onError(null)
    try {
      await action()
      if (reload) await onChanged()
      await load()
    } catch (error) { onError((error as Error).message) } finally { setBusy(false) }
  }
  const regenerate = (shot: MontageShot, prompt: string, seed?: number) => void run(() => regenerateShot(workspace, file, shot.id, {
    intentId: `shot-${randomUuid()}`, expectedRevision: board!.revision, prompt, seed,
  }), true)
  const select = (shot: MontageShot, take: ShotTake) => void run(() => selectShotTake(workspace, file, shot.id, take.id, board!.revision), true)

  if (!board) return <div className="flex items-center gap-2 p-3 text-xs text-text-muted"><Loader2 size={13} className="animate-spin" /> {t('shots.loading')}</div>
  return <section className="border-b border-border bg-bg-tertiary/30 px-3 py-2" aria-label={t('shots.title')}>
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
      <span className="flex items-center gap-1.5 font-medium text-text-primary"><Film size={13} /> {t('shots.summary', { count: board.shots.length, revision: board.revision })}</span>
      <span className="text-[11px] text-text-muted">{t('shots.hint')}</span>
    </div>
    <div className="grid max-h-[60vh] grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2 xl:grid-cols-4">
      {board.shots.map(shot => <ShotCard key={shot.id} shot={shot} busy={busy}
        onRegenerate={(prompt, seed) => regenerate(shot, prompt, seed)} onSelect={take => select(shot, take)}
        onOpenScene={scene => void run(() => openSceneOutput(sceneOutput(workspace, scene)), false)} />)}
    </div>
  </section>
}
