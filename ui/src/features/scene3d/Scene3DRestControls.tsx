import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { controlReason } from '../../i18n/controlLabel'
import { arrangeWorld3DDocument } from '../../api/world3dWorkspace'
import { parseScene3DDocument } from './document'
import type { Scene3DDocument, Scene3DSlot } from './types.ts'

const fieldClass = 'ml-2 min-h-10 rounded border border-border bg-bg-tertiary px-2 text-xs'
/** The arrange reply's contact and placing warnings: the ones this control's choices cause or fix. */
const PLACING = /^(seated_without_seat|floats_above_seat|sunk_into_seat|seat_height_unusual|limb_through_object|inside_object|at_height_unusual|at_out_of_reach|at_not_in_front|furniture_size_unusual|seat_surface_guessed|no_seat_surface|rest_|beside_)/

/** "Sit on…", "at the table…" and "Real height" for a 3D model. They send the same bindings an agent sends to
 *  ``world3d.scene.patch`` (``rest``, ``height``) to the server, which places the sitter on the seat with its feet on the
 *  floor and a held seated clip, and returns the scene with plain numbers the editor keeps editing. */
export function Scene3DRestControls({ slot, document, workspace, locked: panelLocked, onArranged }: {
  slot: Scene3DSlot
  document: Scene3DDocument
  workspace: string
  locked: boolean
  onArranged: (next: Scene3DDocument) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [busy, setBusy] = useState(false)
  const [notes, setNotes] = useState<string[]>([])
  const [height, setHeight] = useState('')
  if (slot.media !== 'model3d' || !slot.sourceUrl) return null
  const others = document.slots.filter(item => item.id !== slot.id && item.media === 'model3d' && item.sourceUrl)
  const rest = slot.rest
  const drawn = Math.round(1.7 * slot.scale * 100) / 100
  const run = async (binding: Record<string, unknown>) => {
    setBusy(true)
    try {
      const reply = await arrangeWorld3DDocument(workspace, document, [{ object_id: slot.id, ...binding }])
      const next = parseScene3DDocument(reply.document)
      if (!next) throw new Error('invalid_world3d_document')
      onArranged(next)
      setNotes(reply.warnings.filter(line => PLACING.test(line)))
      setHeight('')
    } catch (error) {
      setNotes([error instanceof Error ? error.message : String(error)])
    } finally {
      setBusy(false)
    }
  }
  const locked = panelLocked || busy
  const why = controlReason(locked, busy ? 'disabled.actionInProgress' : 'disabled.panelLocked')
  const label = (item: Scene3DSlot) => item.character?.name || item.furniture?.kind && `${item.id} (${item.furniture.kind})` || item.id
  return <div className="mt-3 space-y-2" aria-busy={busy}>
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-xs">{t('restSitOn')}
        <select aria-label={`${t('restSitOn')} ${slot.id}`} disabled={locked || (!rest && !others.length)} title={why} value={rest?.on ?? ''} className={fieldClass}
          onChange={event => void run({ rest: event.target.value ? { pose: 'sit', on: event.target.value, ...(rest?.at ? { at: rest.at } : {}) } : null })}>
          <option value="">{t('restStanding')}</option>
          {others.map(item => <option key={item.id} value={item.id}>{label(item)}</option>)}
        </select>
      </label>
      {rest?.on && <label className="text-xs">{t('restAt')}
        <select aria-label={`${t('restAt')} ${slot.id}`} disabled={locked} title={why} value={rest.at ?? ''} className={fieldClass}
          onChange={event => void run({ rest: { pose: 'sit', on: rest.on, ...(event.target.value ? { at: event.target.value } : {}) } })}>
          <option value="">{t('restNoTable')}</option>
          {others.filter(item => item.id !== rest.on).map(item => <option key={item.id} value={item.id}>{label(item)}</option>)}
        </select>
      </label>}
      <label className="text-xs">{t('realHeight')}
        <input aria-label={`${t('realHeight')} ${slot.id}`} type="number" min={0.05} max={100} step={0.01} disabled={locked} title={why}
          value={height || String(drawn)} className={`${fieldClass} w-20`} onChange={event => setHeight(event.target.value)} />
      </label>
      <button type="button" disabled={locked || !(Number(height) > 0) || Number(height) === drawn} title={why}
        className="min-h-10 rounded-lg border border-border px-3 text-xs hover:bg-bg-hover disabled:opacity-40"
        onClick={() => void run({ height: Number(height) })}>{t('realHeightApply')}</button>
    </div>
    <p className="text-xs text-text-muted">{t('restHelp')}</p>
    {notes.map(line => <p key={line} role="status" className="text-xs text-amber-300">{line}</p>)}
  </div>
}
