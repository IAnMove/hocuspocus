import { useContext, useState, type ReactNode } from 'react'
import { Edit3, Loader2, RotateCcw, Save, X } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import { primaryButton, secondaryButton } from '../styles'
import type { SeriesShotScript } from '../../../api/seriesShotInspector'
import { RerenderShot } from './context'
import { setSectionDraft, type SectionDraft, type SectionKey } from './inspectorStore'
import { sectionChanges, sectionSlice } from './model'

/** Save a part's changes; resolves to what the save did, in words. */
export type SaveChanges = (changes: Record<string, unknown>) => Promise<string | void>

/** What a part's editor gets: its draft (the keys it edits, as the script has them) and a way to change it. */
export interface DraftProps {
  draft: SectionDraft
  change: (draft: SectionDraft) => void
}

const button = 'min-h-10 sm:min-h-0 sm:py-1.5'

/** What the last save did, with the shot's re-render right there (the main call to action may be far up the page). */
function SavedNotice({ text }: { text: string }) {
  const rerender = useContext(RerenderShot)
  return <div role="status" className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-violet-500/30 bg-violet-500/10 px-2 py-1.5 text-[11px] text-violet-100">
    <span className="min-w-0 flex-1">{text}</span>
    {rerender && <button type="button" className={`${primaryButton} ${button}`} disabled={rerender.busy} onClick={rerender.run}><RotateCcw size={13} />{rerender.label}</button>}
  </div>
}

function EditFooter({ busy, changed, error, onSave, onCancel }: { busy: boolean; changed: boolean; error: string; onSave: () => void; onCancel: () => void }) {
  const { t } = useUiTranslation('seriesLab')
  return <>
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" className={`${primaryButton} ${button}`} disabled={busy || !changed} onClick={onSave}>
        {busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}{t('inspector.save')}</button>
      <button type="button" className={`${secondaryButton} ${button}`} disabled={busy} onClick={onCancel}><X size={13} />{t('inspector.cancel')}</button>
    </div>
    {error && <p role="alert" className="whitespace-pre-wrap rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-300">{error}</p>}
  </>
}

interface SectionProps {
  id: string; inspector: string; shotId: string; section: SectionKey; script: SeriesShotScript | undefined
  draft: SectionDraft | undefined; title: string; summary: ReactNode; icon: ReactNode; save: SaveChanges
  view?: ReactNode; editor: (props: DraftProps) => ReactNode; actions?: ReactNode; editable?: boolean
  /** A part that edits inside one key (a 3D shot's cast in scene3d): its draft, and the changes that draft makes. */
  slice?: (script: SeriesShotScript | undefined) => SectionDraft
  diff?: (draft: SectionDraft, script: SeriesShotScript | undefined) => Record<string, unknown> | null
}

/** The draft of one part and its save: kept in the inspector store, dropped when it matches what is saved. */
function useSectionDraft({ inspector, shotId, section, script, draft, save, slice, diff }: SectionProps) {
  const { t } = useUiTranslation('seriesLab')
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const changesOf = (value: SectionDraft) => diff ? diff(value, script) : sectionChanges(section, value, script)
  const changes = draft ? changesOf(draft) : null
  const cancel = () => { setSectionDraft(inspector, shotId, section, undefined); setOpen(false); setError('') }
  const submit = async () => {
    if (!changes) { cancel(); return }
    setBusy(true); setError(''); setSaved('')
    try {
      setSaved((await save(changes)) || t('inspector.saved.plain'))
      setSectionDraft(inspector, shotId, section, undefined); setOpen(false)
    } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) }
  }
  return {
    editing: open || draft !== undefined, busy, error, saved, changes, cancel, submit,
    current: draft ?? (slice ? slice(script) : sectionSlice(script, section)),
    edit: () => { setSaved(''); setOpen(true) },
    // A draft back to what is saved is no draft: nothing is left unsaved (the editor stays open).
    change: (next: SectionDraft) => { setOpen(true); setSectionDraft(inspector, shotId, section, changesOf(next) ? next : undefined) },
  }
}

/**
 * One part of the shot: a summary with Edit; editing keeps a draft (it survives a trip to an editor and back) until
 * Save sends only what changed through the shot edit, or Cancel drops it.
 */
export function InspectorSection(props: SectionProps) {
  const { id, title, summary, icon, view, editor, actions, editable = true } = props
  const { t } = useUiTranslation('seriesLab')
  const state = useSectionDraft(props)
  return <section id={id} aria-labelledby={`${id}-title`} data-testid={id}
    className={`@container scroll-mt-20 rounded-xl border bg-bg-secondary p-3 ${state.changes ? 'border-amber-500/40' : 'border-border'}`}>
    <header className="flex flex-wrap items-center gap-2">
      <span className="text-violet-300">{icon}</span>
      <h4 id={`${id}-title`} className="text-xs font-semibold text-text-primary">{title}</h4>
      {state.changes && <span className="rounded-full border border-amber-500/40 px-2 py-0.5 text-[10px] text-amber-200">{t('inspector.unsaved')}</span>}
      <div className="ml-auto flex flex-wrap gap-1.5">
        {actions}
        {editable && !state.editing && <button type="button" className={`${secondaryButton} ${button}`} onClick={state.edit}>
          <Edit3 size={13} />{t('inspector.edit')}</button>}
      </div>
    </header>
    {state.editing ? <div className="mt-3 space-y-3">
      {editor({ draft: state.current, change: state.change })}
      <EditFooter busy={state.busy} changed={Boolean(state.changes)} error={state.error} onSave={() => void state.submit()} onCancel={state.cancel} />
    </div> : <>
      {state.saved && <SavedNotice text={state.saved} />}
      <div className="mt-2 text-[11px] text-text-secondary">{summary}</div>
      {view}
    </>}
  </section>
}
