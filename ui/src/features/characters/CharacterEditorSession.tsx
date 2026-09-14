import { lazy, Suspense, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useCharacterEditorHandoff, type CharacterEditorRequest } from './characterEditorHandoff'

const Definition = lazy(() => import('./CharacterDefinitionEditor').then(module => ({ default: module.CharacterDefinitionEditor })))

export function CharacterEditorSession({ request }: { request: CharacterEditorRequest }) {
  const { t } = useUiTranslation('characters')
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState('')
  const saveRef = useRef<(() => Promise<void>) | null>(null)
  const [saving, setSaving] = useState(false)
  const returnToSource = async () => {
    setBusy(true); setError('')
    try {
      await request.onReturn()
      if (useCharacterEditorHandoff.getState().request === request) useCharacterEditorHandoff.setState({ request: null })
    } catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }
  const saveAndReturn = async () => {
    setSaving(true); setError('')
    try {
      if (!saveRef.current) throw new Error(t('speechWorkshop.busy'))
      await saveRef.current()
      await returnToSource()
    } catch (cause) { setError((cause as Error).message) }
    finally { setSaving(false) }
  }
  return <section aria-label={t('editorSession.title', { name: request.kit.name })} className="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-8">
    <header className="space-y-3">
      <p className="text-sm text-text-muted">{request.sourceLabel}</p>
      <h2 className="text-xl font-semibold">{t('editorSession.title', { name: request.kit.name })}</h2>
      {request.kit.base && <img src={request.kit.base.source} alt={request.kit.name} className="h-40 max-w-full rounded-lg border border-border object-contain" />}
      <p className="text-sm text-text-secondary">{t('editorSession.hint')}</p>
      <button type="button" className="min-h-10 rounded-lg border border-border px-4 text-sm disabled:opacity-40"
        disabled={busy || saving || dirty} onClick={() => void returnToSource()}>{t('editorSession.return')}</button>
      {dirty && <p role="status" className="text-xs text-amber-200">{t('editorSession.saveFirst')}</p>}
    </header>
    <Suspense fallback={<p role="status">{t('speechWorkshop.busy')}</p>}>
      <Definition saveRef={saveRef} workspace={request.workspace} initialKit={request.kit} lockIdentity spacious initialDraft={request.draft}
        onDraftChange={draft => { request.draft = draft }}
        onSaved={async kit => {
          await request.onSaved(kit)
          request.kit = kit
          request.saved = true
        }} onBusyChange={setBusy} onDirtyChange={setDirty} />
    </Suspense>
    <footer className="sticky bottom-0 z-20 flex flex-wrap items-center gap-3 rounded-lg border border-cyan-400/40 bg-bg-secondary p-4 shadow-lg">
      <button type="button" disabled={busy || saving} onClick={() => void saveAndReturn()}
        className="min-h-11 rounded-lg bg-cyan-500 px-5 py-2 text-sm font-semibold text-black disabled:opacity-40">
        {saving ? t('speechWorkshop.busy') : t('editorSession.saveAllReturn')}
      </button>
      <p className="text-xs text-text-secondary">{t('editorSession.saveAllHint')}</p>
    </footer>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </section>
}
