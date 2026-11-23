import { useRef, useState } from 'react'
import { runBatch } from './imageBatch'

export function ImageBatchImport() {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [archive, setArchive] = useState<Blob>()
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
    <input ref={input} type="file" accept=".zip" hidden onChange={async event => {
      const file = event.currentTarget.files?.[0]
      event.currentTarget.value = ''
      if (!file) return
      setBusy(true)
      setStatus('Importando ZIP…')
      try {
        const { archive, done, total } = await runBatch(file, setStatus)
        setArchive(archive)
        setStatus(`${done} de ${total} imágenes generadas · ${total - done} fallidas`)
      } catch (error) {
        setStatus(error instanceof Error ? error.message : String(error))
      } finally {
        setBusy(false)
      }
    }} />
    <button type="button" disabled={busy} onClick={() => input.current?.click()}
      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-50">Importar lote</button>
    {archive && <button type="button" onClick={download} className="block text-xs underline">Descargar resultados</button>}
    <p aria-live="polite" className="break-words text-xs text-text-muted">{status}</p>
  </div>
}
