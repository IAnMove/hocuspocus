import { useEffect, useMemo, useState } from 'react'
import { useStore } from '../../stores/useStore'
import { ensureUiI18n, useUiTranslation } from '../../i18n'
import { generateImageAsset } from '../../lib/imageGeneration'
import { buildInfinitePanoramaPrompt, createTripleTileLayout } from '../../lib/panoramaLoop'

const ts = (key: string, opts?: Record<string, unknown>) => ensureUiI18n().t(key, { ns: 'studio', ...opts })

type PreparedPanorama = { file: File; url: string; width: number; height: number }

const loadImage = (url: string) => new Promise<HTMLImageElement>((resolve, reject) => {
  const image = new Image()
  image.onload = () => resolve(image)
  image.onerror = () => reject(new Error(ts('panorama.readFailed')))
  image.src = url
})

const canvasBlob = (canvas: HTMLCanvasElement) => new Promise<Blob>((resolve, reject) => {
  canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error(ts('panorama.canvasFailed'))), 'image/png')
})

async function prepareTripleTile(file: File, seamPercent: number): Promise<PreparedPanorama> {
  const sourceUrl = URL.createObjectURL(file)
  try {
    const image = await loadImage(sourceUrl)
    const scale = Math.min(1, 1024 / Math.max(1, image.naturalWidth))
    const width = Math.max(1, Math.round(image.naturalWidth * scale))
    const height = Math.max(1, Math.round(image.naturalHeight * scale))
    const layout = createTripleTileLayout(width, height, width * seamPercent / 100)
    const canvas = document.createElement('canvas')
    canvas.width = layout.canvas.width
    canvas.height = layout.canvas.height
    const context = canvas.getContext('2d')
    if (!context) throw new Error(ts('panorama.browserFailed'))
    for (const tile of layout.tiles) context.drawImage(image, tile.x, tile.y, tile.width, tile.height)
    for (const seam of layout.seamBands) {
      const gradient = context.createLinearGradient(seam.x, 0, seam.x + seam.width, 0)
      gradient.addColorStop(0, 'rgba(251,191,36,.05)')
      gradient.addColorStop(.5, 'rgba(251,191,36,.55)')
      gradient.addColorStop(1, 'rgba(251,191,36,.05)')
      context.fillStyle = gradient
      context.fillRect(seam.x, seam.y, seam.width, seam.height)
    }
    const blob = await canvasBlob(canvas)
    const prepared = new File([blob], `panorama-seams-${file.name.replace(/\.[^.]+$/, '')}.png`, { type: 'image/png' })
    return { file: prepared, url: URL.createObjectURL(blob), width, height }
  } finally {
    URL.revokeObjectURL(sourceUrl)
  }
}

/** A deliberately small image-side entry point for seamless horizontal backgrounds. */
export function PanoramaLoopPanel() {
  const { t } = useUiTranslation('studio')
  const selectedModel = useStore(state => {
    const remembered = state.selectedModelPerMode.image
    // MiniMax may remain selected for ordinary image creation, but this tool
    // needs a local reference-capable editor and uses the active local model.
    return remembered && !remembered.startsWith('minimax:') ? remembered : state.params.model_type
  })
  const loadOutputs = useStore(state => state.loadOutputs)
  const [source, setSource] = useState<File | null>(null)
  const [prepared, setPrepared] = useState<PreparedPanorama | null>(null)
  const [subject, setSubject] = useState('the supplied environment')
  const [style, setStyle] = useState('')
  const [occluder, setOccluder] = useState('')
  const [seamPercent, setSeamPercent] = useState(12)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => () => { if (prepared) URL.revokeObjectURL(prepared.url) }, [prepared])

  useEffect(() => {
    const encoded = window.sessionStorage.getItem('hocuspocus:panorama-loop-source')
    if (!encoded) return
    window.sessionStorage.removeItem('hocuspocus:panorama-loop-source')
    let queued: { url?: string; name?: string }
    try { queued = JSON.parse(encoded) as { url?: string; name?: string } } catch { return }
    const sourceUrl = queued.url
    if (!sourceUrl) return
    void (async () => {
      try {
        const response = await fetch(sourceUrl)
        if (!response.ok) throw new Error(t('panorama.missingBackground'))
        const blob = await response.blob()
        const extension = blob.type === 'image/png' ? 'png' : blob.type === 'image/webp' ? 'webp' : 'jpg'
        const file = new File([blob], queued.name || `3d-video-background.${extension}`, { type: blob.type || 'image/jpeg' })
        setSource(file)
        const next = await prepareTripleTile(file, seamPercent)
        setPrepared(previous => { if (previous) URL.revokeObjectURL(previous.url); return next })
        setMessage(t('panorama.received'))
      } catch (error) {
        setMessage(error instanceof Error ? error.message : t('panorama.receiveFailed'))
      }
    })()
  // Consume the hand-off once when the Image panel mounts.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const prompt = useMemo(() => buildInfinitePanoramaPrompt({ subject, style, foregroundOccluder: occluder }), [subject, style, occluder])
  const prepare = async (file: File) => {
    setSource(file); setMessage(null)
    try {
      const next = await prepareTripleTile(file, seamPercent)
      setPrepared(previous => { if (previous) URL.revokeObjectURL(previous.url); return next })
    } catch (error) {
      setPrepared(null); setMessage(error instanceof Error ? error.message : t('panorama.prepareFailed'))
    }
  }
  const updateSeam = (value: number) => {
    const next = Math.max(4, Math.min(25, value))
    setSeamPercent(next)
    if (source) void prepareTripleTile(source, next).then(result => setPrepared(previous => { if (previous) URL.revokeObjectURL(previous.url); return result })).catch(error => setMessage(error instanceof Error ? error.message : t('panorama.prepareFailed')))
  }
  const generate = async () => {
    if (!prepared) { setMessage(t('panorama.chooseImage')); return }
    if (!selectedModel) { setMessage(t('panorama.chooseModel')); return }
    setBusy(true); setMessage(null)
    try {
      const asset = await generateImageAsset('maestro', prompt, selectedModel, prepared.url, 'visible seam, border, frame, text, duplicated focal object', { strictReference: true, referenceMode: 'edit' })
      await loadOutputs()
      setMessage(t('panorama.generated', { name: asset.name }))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('panorama.generateFailed'))
    } finally {
      setBusy(false)
    }
  }

  return <section className="space-y-2 rounded-lg border border-amber-400/25 bg-amber-400/[.035] p-3">
    <div className="flex items-center justify-between gap-2"><span className="text-[11px] font-medium text-amber-100">{t('panorama.title')}</span><span className="text-[8px] text-amber-200/70">{t('panorama.experimental')}</span></div>
    <p className="text-[9px] leading-relaxed text-text-muted">{t('panorama.hint')}</p>
    <input aria-label={t('panorama.sourceAria')} type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void prepare(file) }} className="block w-full text-[9px] text-text-muted file:mr-2 file:rounded file:border-0 file:bg-bg-tertiary file:px-2 file:py-1 file:text-[9px] file:text-text-secondary" />
    <div className="grid grid-cols-2 gap-2"><label className="text-[9px] text-text-muted">{t('panorama.scene')}<input value={subject} disabled={busy} onChange={event => setSubject(event.target.value)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" /></label><label className="text-[9px] text-text-muted">{t('panorama.style')}<input value={style} disabled={busy} onChange={event => setStyle(event.target.value)} placeholder={t('panorama.stylePlaceholder')} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" /></label></div>
    <div className="grid grid-cols-2 gap-2"><label className="text-[9px] text-text-muted">{t('panorama.seamCover')}<input value={occluder} disabled={busy} onChange={event => setOccluder(event.target.value)} placeholder={t('panorama.occluderPlaceholder')} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" /></label><label className="text-[9px] text-text-muted">{t('panorama.seamWidth', { percent: seamPercent })}<input type="range" min="4" max="25" value={seamPercent} disabled={busy} onChange={event => updateSeam(Number(event.target.value))} className="mt-1 w-full accent-amber-300" /></label></div>
    {prepared && <div className="overflow-hidden rounded border border-amber-300/20 bg-black/20"><img src={prepared.url} alt={t('panorama.previewAlt')} className="block max-h-28 w-full object-contain" /><p className="border-t border-amber-300/10 px-1.5 py-1 text-[8px] text-text-muted">{t('panorama.previewCaption', { width: prepared.width, height: prepared.height })}</p></div>}
    <details className="text-[8px] text-text-muted"><summary className="cursor-pointer">{t('panorama.exactPrompt')}</summary><p className="mt-1 rounded bg-black/20 p-1.5 leading-relaxed">{prompt}</p></details>
    <button type="button" disabled={!prepared || busy} onClick={() => void generate()} className="w-full rounded border border-amber-300/45 bg-amber-400/10 px-2 py-1.5 text-[10px] text-amber-100 disabled:opacity-40">{busy ? t('panorama.generating') : t('panorama.generateWith', { model: selectedModel || t('panorama.selectedModel') })}</button>
    {message && <p className={`text-[8px] ${/generated|generada/i.test(message) ? 'text-emerald-200' : 'text-red-300'}`}>{message}</p>}
  </section>
}
