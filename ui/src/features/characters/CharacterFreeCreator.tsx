import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Loader2, RotateCcw, Save, WandSparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { CharacterKitAsset } from '../../lib/characterKit'
import { useCreatorSession, type CharacterCreatorSession, type CreatorView } from './characterCreatorSession'

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'

type Props = {
  workspace: string; model: string; modelPicker: (disabled: boolean) => ReactNode; disabled?: boolean
  onPictures: () => void; onCreateMouths: () => void
  onUseReference: (asset: CharacterKitAsset, description: string, signal: AbortSignal) => Promise<void>
}

/** The name, the description, the model and what to do next (generate, cancel, start over). */
function FreeForm({ session, view, model, modelPicker, blocked, onPictures }: {
  session: CharacterCreatorSession; view: CreatorView; model: string; modelPicker: Props['modelPicker']; blocked: boolean; onPictures: () => void
}) {
  const { t } = useUiTranslation('characters')
  const { name, description, draft, saved } = view.free
  return <div className="space-y-3">
    <label className="block text-xs text-text-secondary">{t('imageCreator.name')}<input value={name} maxLength={80} disabled={blocked || saved} onChange={event => session.editFree({ name: event.target.value })} className={`${control} mt-1 w-full`} /></label>
    <label className="block text-xs text-text-secondary">{t('imageCreator.description')}<textarea value={description} maxLength={2000} rows={3} disabled={blocked} onChange={event => session.editFree({ description: event.target.value })} placeholder={t('imageCreator.placeholder')} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-3 text-sm" /></label>
    {modelPicker(blocked)}
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={blocked || !model || !name.trim() || !description.trim()} onClick={() => void session.generateFree({ model, onPictures })} className={`${control} inline-flex items-center gap-2 text-cyan-200`}>
        {view.busy === 'generate' ? <Loader2 size={15} className="animate-spin" /> : <WandSparkles size={15} />}{t(draft ? 'imageCreator.regenerate' : 'imageCreator.generate')}</button>
      {view.busy === 'generate' && <button type="button" onClick={() => session.cancel()} className={control}>{t('lips.cancel')}</button>}
      {!blocked && (draft || name || description) && <button type="button" onClick={() => session.resetFree()} className={`${control} inline-flex items-center gap-2`}><RotateCcw size={14} />{t('styleCreator.startOver')}</button>}
    </div>
  </div>
}

/** The generated image and what can be done with it: save, make its mouths, use it as a reference. */
function FreeResult({ session, view, blocked, onCreateMouths, onReference }: {
  session: CharacterCreatorSession; view: CreatorView; blocked: boolean; onCreateMouths: () => void; onReference: () => void
}) {
  const { t } = useUiTranslation('characters')
  const { name, draft, saved } = view.free
  if (!draft?.base) return <div className="flex min-h-36 items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-text-muted">{t('imageCreator.empty')}</div>
  return <div className="space-y-3">
    <img src={draft.base.source} alt={draft.name} className="aspect-square w-full rounded-lg border border-border object-contain" />
    <button type="button" disabled={blocked || saved || !name.trim()} onClick={() => void session.saveFree()} className={`${control} inline-flex w-full items-center justify-center gap-2`}><Save size={15} />{t('imageCreator.save')}</button>
    {saved && <button type="button" disabled={blocked} onClick={onCreateMouths} className={`${control} w-full text-cyan-200`}>{t('imageCreator.createMouths')}</button>}
    <button type="button" disabled={blocked} onClick={onReference} className={`${control} w-full`}>{t('imageCreator.useReference')}</button>
  </div>
}

function FreeStatus({ view, working, message, error }: { view: CreatorView; working: boolean; message: string; error: string }) {
  const { t } = useUiTranslation('characters')
  const noticed = view.message === 'imageCreator.review' || view.message === 'imageCreator.saved' || view.message === 'imageCreator.cancelled'
  return <>
    {working && <p role="status" className="text-sm text-text-muted">{t(view.busy === 'generate' ? 'imageCreator.generating' : 'lips.saving')}</p>}
    {noticed && view.message && <p role="status" className="text-sm text-emerald-200">{t(view.message)}</p>}
    {message && <p role="status" className="text-sm text-emerald-200">{message}</p>}
    {(view.error || error) && <p role="alert" className="text-sm text-red-300">{view.error || error}</p>}
  </>
}

/** A character with no style: describe it, review the one image, save it. Like the styled one, the work belongs to the session: it
 * goes on when the screen is left and is kept for the next visit. */
export function CharacterFreeCreator({ workspace, model, modelPicker, disabled, onPictures, onCreateMouths, onUseReference }: Props) {
  const { t } = useUiTranslation('characters')
  const { session, view } = useCreatorSession(workspace)
  const { draft } = view.free
  const [referencing, setReferencing] = useState(false), [message, setMessage] = useState(''), [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const blocked = Boolean(view.busy) || referencing || Boolean(disabled)
  const sendReference = async () => {
    if (!draft?.base || blocked) return
    const operation = new AbortController(); controller.current = operation
    setReferencing(true); setError(''); setMessage('')
    try { await onUseReference(draft.base, draft.lookNotes || view.free.description, operation.signal); operation.signal.throwIfAborted(); setMessage(t('imageCreator.referenceReady')) }
    catch (cause) { if (!operation.signal.aborted) setError((cause as Error).message) }
    finally { if (!operation.signal.aborted) setReferencing(false) }
  }
  return <>
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_15rem]">
      <FreeForm session={session} view={view} model={model} modelPicker={modelPicker} blocked={blocked} onPictures={onPictures} />
      <FreeResult session={session} view={view} blocked={blocked} onCreateMouths={onCreateMouths} onReference={() => void sendReference()} />
    </div>
    <FreeStatus view={view} working={view.busy === 'generate' || view.busy === 'save' || referencing} message={message} error={error} />
  </>
}
