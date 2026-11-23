import { useRef, useSyncExternalStore } from 'react'
import {
  getImageBatchSession, startImageBatch, stopImageBatch, subscribeImageBatchSession,
} from './imageBatchSession'

export function ImageBatchImport() {
  const input = useRef<HTMLInputElement>(null)
  const { busy, stopping, status, archive } = useSyncExternalStore(
    subscribeImageBatchSession, getImageBatchSession,
  )
  const download = () => {
    if (!archive) return
    const url = URL.createObjectURL(archive)
    const link = document.createElement('a')
    link.href = url
    link.download = 'resultados.zip'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
  return <div className="mt-2 space-y-1">
    <input ref={input} type="file" accept=".zip" hidden onChange={event => {
      const file = event.currentTarget.files?.[0]
      event.currentTarget.value = ''
      if (file) void startImageBatch(file)
    }} />
    <button type="button" disabled={busy} onClick={() => input.current?.click()}
      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-50">Importar lote</button>
    {busy && <button type="button" disabled={stopping} onClick={stopImageBatch}
      className="ml-2 rounded border border-border px-2 py-1 text-xs disabled:opacity-50">Cancelar lote</button>}
    {archive && <button type="button" onClick={download} className="block text-xs underline">Descargar resultados</button>}
    <p aria-live="polite" className="break-words text-xs text-text-muted">{status}</p>
  </div>
}
