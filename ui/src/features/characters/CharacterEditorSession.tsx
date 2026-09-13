import { lazy, Suspense, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useCharacterEditorHandoff, type CharacterEditorRequest } from './characterEditorHandoff'

const Definition = lazy(() => import('./CharacterDefinitionEditor').then(module => ({ default: module.CharacterDefinitionEditor })))

export function CharacterEditorSession({ request }: { request: CharacterEditorRequest }) {
  const { t } = useUiTranslation('characters')
  const [busy, setBusy] = useState(false), [dirty, setDirty] = useState(false), [error, setError] = useState('')
  const returnToSource = async () => {
    setBusy(true); setError('')
    try {
      await request.onReturn()
      if (useCharacterEditorHandoff.getState().request === request) useCharacterEditorHandoff.setState({ request: null })
    } catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }
  return <section aria-label={t('editorSession.title', { name: request.kit.name })} className="mx-auto w-full max-w-5xl space-y-6 p-4 md:p-8">
    <header className="space-y-3">
      <p className="text-sm text-text-muted">{request.sourceLabel}</p>
      <h2 className="text-xl font-semibold">{t('editorSession.title', { name: request.kit.name })}</h2>
      {request.kit.base && <img src={request.kit.base.source} alt={request.kit.name} className="h-40 max-w-full rounded-lg border border-border object-contain" />}
      <p className="text-sm text-text-secondary">{t('editorSession.hint')}</p>
      <button type="button" className="min-h-10 rounded-lg border border-border px-4 text-sm disabled:opacity-40"
        disabled={busy || dirty} onClick={() => void returnToSource()}>{t('editorSession.return')}</button>
      {dirty && <p role="status" className="text-xs text-amber-200">{t('editorSession.saveFirst')}</p>}
    </header>
    <Suspense fallback={<p role="status">{t('speechWorkshop.busy')}</p>}>
      <Definition workspace={request.workspace} initialKit={request.kit} lockIdentity spacious initialDraft={request.draft}
        onDraftChange={draft => { request.draft = draft }}
        onSaved={async kit => {
          await request.onSaved(kit)
          request.kit = kit
        }} onBusyChange={setBusy} onDirtyChange={setDirty} />
    </Suspense>
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </section>
}
