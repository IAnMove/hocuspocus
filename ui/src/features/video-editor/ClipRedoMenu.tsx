import { useEffect, useState } from 'react'
import { Clapperboard, Pencil, RefreshCw, Replace } from 'lucide-react'
import { getMontageShots, regenerateShot, selectShotTake, type MontageShotBoard, type ShotProvenance } from '../../api/montages'
import { useUiTranslation } from '../../i18n'
import { controlReason } from '../../i18n/controlLabel'
import { randomUuid } from '../../lib/uuid'
import { RegenerateForm, TakeChip } from './ShotBoard'
import { hasPendingTakes, shortPrompt } from './shotBoardModel'
import { creationOutputs } from './comicEdits'
import type { ClipRemake } from './comicRemake'

const action = 'inline-flex items-center gap-1 rounded border border-black/20 bg-white px-1.5 py-0.5 text-[10px] text-black hover:bg-black/5 disabled:opacity-50'

/** How one clip was made, and the ways to remake it that this origin allows: a new take of the same
 * generation, the full settings in Video creation, its Video 2D/3D scene, or another video. Every way
 * comes back to this clip. */
export function ClipRedoMenu({ workspace, file, clipId, onChanged, onError, onRemake }: {
  workspace: string
  file: string
  clipId: string
  onChanged: (adoptedClipId?: string) => Promise<void>
  onError: (message: string | null) => void
  onRemake: (request: ClipRemake) => void
}) {
  const { t } = useUiTranslation('videoEditor')
  const [board, setBoard] = useState<MontageShotBoard | null>(null)
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  useEffect(() => {
    let live = true
    const read = () => getMontageShots(workspace, file).then(
      next => { if (live) setBoard(next) },
      error => { if (live) onError((error as Error).message) },
    )
    void read()
    return () => { live = false }
  }, [workspace, file, onError])
  useEffect(() => {
    if (!board || !hasPendingTakes(board)) return
    const timer = window.setInterval(() => {
      void getMontageShots(workspace, file).then(setBoard, error => onError((error as Error).message))
    }, 8000)
    return () => window.clearInterval(timer)
  }, [board, workspace, file, onError])
  if (!board) return <p className="text-[10px] text-black/60">{t('shots.loading')}</p>
  const shot = board.shots.find(item => item.id === clipId)
  const gallery = <button type="button" className={action} onClick={() => onRemake({ kind: 'gallery' })}><Replace size={11} /> {t('comic.redo.gallery')}</button>
  if (!shot) return <div className="space-y-1">{gallery}<p className="text-[10px] text-black/60">{t('comic.redo.unsaved')}</p></div>
  const run = (work: () => Promise<unknown>, adoptedClipId?: string) => {
    setBusy(true)
    onError(null)
    void work().then(() => onChanged(adoptedClipId)).then(() => getMontageShots(workspace, file)).then(setBoard)
      .catch(error => onError((error as Error).message)).finally(() => setBusy(false))
  }
  const origin = shot.provenance
  const scene = origin.scene
  const kind = t(`shots.origin.${origin.kind}`, { defaultValue: origin.kind })
  const hint = origin.canRegenerate ? t('comic.redo.hintGenerated') : scene ? t('comic.redo.hintScene') : t('comic.redo.hintUpload')
  return <div className="space-y-1">
    <p className="text-[10px] text-black/70" title={origin.prompt}>{originLine(origin, kind, t('shots.seed'))}</p>
    {shot.takes.length > 0 && <div className="flex flex-wrap gap-1">{shot.takes.map(take => <TakeChip key={take.id} take={take} busy={busy}
      onSelect={() => run(() => selectShotTake(workspace, file, shot.id, take.id, board.revision), shot.id)} />)}</div>}
    <div className="flex flex-wrap gap-1">
      {origin.canRegenerate && !editing && <button type="button" className={action} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={() => setEditing(true)}><RefreshCw size={11} /> {t('comic.redo.here')}</button>}
      {origin.canRegenerate && <button type="button" className={action} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={() => onRemake({ kind: 'creation', outputs: creationOutputs(origin) })}><Clapperboard size={11} /> {t('comic.redo.creation')}</button>}
      {scene && <button type="button" className={action} disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')} onClick={() => onRemake({ kind: 'scene', scene })}><Pencil size={11} /> {t('comic.redo.scene')}</button>}
      {gallery}
    </div>
    {editing && <RegenerateForm shot={shot} busy={busy} onCancel={() => setEditing(false)} onSubmit={(prompt, seed) => {
      setEditing(false)
      run(() => regenerateShot(workspace, file, shot.id, { intentId: `shot-${randomUuid()}`, expectedRevision: board.revision, prompt, seed }))
    }} />}
    <p className="text-[10px] text-black/60">{hint}</p>
  </div>
}

function originLine(origin: ShotProvenance, kind: string, seed: string): string {
  const parts = [kind]
  if (origin.model) parts.push(origin.model)
  if (origin.seed !== undefined) parts.push(`${seed} ${origin.seed}`)
  if (origin.scene) parts.push(origin.scene)
  else if (origin.prompt) parts.push(shortPrompt(origin.prompt, 70))
  return parts.join(' · ')
}
