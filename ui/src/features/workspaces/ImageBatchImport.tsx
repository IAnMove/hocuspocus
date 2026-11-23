import { useRef, useState } from 'react'
import { runBatch } from './imageBatch'

export function ImageBatchImport() {
  const input = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const [stopping, setStopping] = useState(false)
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
      if (!file || controller.current) return
      const run = new AbortController()
      controller.current = run
      setBusy(true)
      setArchive(undefined)
      setStatus('Importando ZIP…')
      try {
        const { archive, done, total, cancelled } = await runBatch(file, setStatus, run.signal)
        setArchive(archive)
        setStatus(`${done} de ${total} imágenes generadas · ${total - done - cancelled} fallidas${cancelled ? ` · ${cancelled} canceladas` : ''}`)
      } catch (error) {
        setStatus(run.signal.aborted ? 'Lote cancelado' : error instanceof Error ? error.message : String(error))
      } finally {
        controller.current = null
        setStopping(false)
        setBusy(false)
      }
    }} />
    <button type="button" disabled={busy} onClick={() => input.current?.click()}
      className="rounded border border-border px-2 py-1 text-xs disabled:opacity-50">Importar lote</button>
    {busy && <button type="button" disabled={stopping} onClick={() => {
      controller.current?.abort()
      setStopping(true)
      setStatus('Cancelando lote…')
    }} className="ml-2 rounded border border-border px-2 py-1 text-xs disabled:opacity-50">Cancelar lote</button>}
    {archive && <button type="button" onClick={download} className="block text-xs underline">Descargar resultados</button>}
    <p aria-live="polite" className="break-words text-xs text-text-muted">{status}</p>
  </div>
}
