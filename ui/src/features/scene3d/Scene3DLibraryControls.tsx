import { useEffect, useRef, useState } from 'react'
import { fetchOutputs, type ApiOutput } from '../../api/outputs'
import { AssetExplorerDialog } from '../../components/common/AssetExplorerDialog'
import { useUiTranslation } from '../../i18n'
import { isWorld3DOutput, loadWorld3DOutput, saveWorld3DOutput } from './sceneLibrary'
import type { Scene3DDocumentRef } from './documentHistory.ts'
import type { Scene3DDocument } from './types'

export function Scene3DLibraryControls({ document, workspace, disabled, preview, identity, onLoad, onSaved }: {
  document: Scene3DDocument; workspace: string; disabled: boolean
  preview: () => string | undefined
  identity?: Scene3DDocumentRef
  onLoad: (document: Scene3DDocument, source?: Scene3DDocumentRef) => void
  onSaved?: (output: ApiOutput, document: Scene3DDocument, identity: Scene3DDocumentRef) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false)
  const [items, setItems] = useState<ApiOutput[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [retry, setRetry] = useState(0), [name, setName] = useState('')
  const [note, setNote] = useState(''), [error, setError] = useState('')
  const current = useRef({ document, workspace, disabled, identity })
  current.current = { document, workspace, disabled, identity }
  const loading = useRef<AbortController | null>(null)
  useEffect(() => () => { loading.current?.abort() }, [])
  useEffect(() => {
    loading.current?.abort(); setOpen(false); setBusy(false); setNote(''); setError('')
  }, [workspace])
  useEffect(() => {
    if (!open) return
    const abort = new AbortController()
    setStatus('loading')
    void fetchOutputs(0, 0, { mediaType: 'scene', workspace, signal: abort.signal }).then(result => {
      if (!abort.signal.aborted) { setItems(result.outputs.filter(isWorld3DOutput)); setStatus('ready') }
    }).catch(() => { if (!abort.signal.aborted) setStatus('error') })
    return () => abort.abort()
  }, [open, workspace, retry])
  const choose = async (item: ApiOutput | null) => {
    if (!item) return
    const captured = current.current, abort = new AbortController()
    loading.current?.abort(); loading.current = abort
    setBusy(true); setError('')
    try {
      const next = await loadWorld3DOutput(item, captured.workspace, abort.signal)
      if (abort.signal.aborted) return
      if (current.current.document !== captured.document || current.current.workspace !== captured.workspace || current.current.disabled) {
        setError(t('library.changed')); return
      }
      onLoad(next, { workspace: captured.workspace, documentId: item.name, revision: Math.max(1, Math.trunc(item.created_at) || 1) })
      setOpen(false); setNote('')
    } catch { if (!abort.signal.aborted) setError(t('invalidDocument')) }
    finally { if (loading.current === abort) { loading.current = null; setBusy(false) } }
  }
  const save = async () => {
    const captured = current.current
    setBusy(true); setError(''); setNote('')
    try {
      const png = preview()
      if (!png) throw new Error(t('library.previewUnavailable'))
      const saved = await saveWorld3DOutput(captured.document, png, name.trim() || captured.document.templateId, captured.workspace)
      if (captured.identity) onSaved?.(saved, captured.document, captured.identity)
      if (current.current.workspace === captured.workspace) setNote(t('library.saved'))
    } catch (cause) { setError(cause instanceof Error ? cause.message : t('library.saveFailed')) }
    finally { setBusy(false) }
  }
  return <>
    <input aria-label={t('library.name')} placeholder={t('library.name')} value={name} maxLength={120} disabled={disabled || busy}
      onChange={event => setName(event.target.value)} className="min-h-10 rounded-lg border border-border bg-bg-primary px-3" />
    <button type="button" disabled={disabled || busy} onClick={() => void save()} className="min-h-10 rounded-lg border border-border px-3">{t('library.save')}</button>
    <button type="button" disabled={disabled || busy} onClick={() => { setError(''); setOpen(true) }} className="min-h-10 rounded-lg border border-border px-3">{t('library.open')}</button>
    {busy && loading.current && <button type="button" className="min-h-10 rounded-lg border border-border px-3"
      onClick={() => { loading.current?.abort(); loading.current = null; setBusy(false) }}>{t('library.cancelLoad')}</button>}
    {note && <span role="status">{note}</span>}{error && <span role="alert">{error}</span>}
    <AssetExplorerDialog open={open} title={t('library.open')} subtitle={t('library.help')} items={items}
      workspaceId={workspace} remote={false} constraints={{ kinds: ['scene'], maxCount: 1, optional: false }} status={busy ? 'loading' : status}
      onRetry={() => setRetry(value => value + 1)} onChoose={item => { if (!busy && !disabled) void choose(item) }}
      onClose={() => setOpen(false)} />
  </>
}
