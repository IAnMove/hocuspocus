import { useEffect, useMemo, useState } from 'react'
import { useStore } from '../../stores/useStore'
import { generateImageAsset } from '../../lib/imageGeneration'
import { buildInfinitePanoramaPrompt, createTripleTileLayout } from '../../lib/panoramaLoop'

type PreparedPanorama = { file: File; url: string; width: number; height: number }

const loadImage = (url: string) => new Promise<HTMLImageElement>((resolve, reject) => {
  const image = new Image()
  image.onload = () => resolve(image)
  image.onerror = () => reject(new Error('Could not read this background image.'))
  image.src = url
})

const canvasBlob = (canvas: HTMLCanvasElement) => new Promise<Blob>((resolve, reject) => {
  canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('Could not prepare the panorama canvas.')), 'image/png')
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
    if (!context) throw new Error('This browser cannot prepare the panorama canvas.')
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

  const prompt = useMemo(() => buildInfinitePanoramaPrompt({ subject, style, foregroundOccluder: occluder }), [subject, style, occluder])
  const prepare = async (file: File) => {
    setSource(file); setMessage(null)
    try {
      const next = await prepareTripleTile(file, seamPercent)
      setPrepared(previous => { if (previous) URL.revokeObjectURL(previous.url); return next })
    } catch (error) {
      setPrepared(null); setMessage(error instanceof Error ? error.message : 'Could not prepare panorama.')
    }
  }
  const updateSeam = (value: number) => {
    const next = Math.max(4, Math.min(25, value))
    setSeamPercent(next)
    if (source) void prepareTripleTile(source, next).then(result => setPrepared(previous => { if (previous) URL.revokeObjectURL(previous.url); return result })).catch(error => setMessage(error instanceof Error ? error.message : 'Could not prepare panorama.'))
  }
  const generate = async () => {
    if (!prepared) { setMessage('Choose a background image first.'); return }
    if (!selectedModel) { setMessage('Choose a reference-capable image model first.'); return }
    setBusy(true); setMessage(null)
    try {
      const asset = await generateImageAsset('maestro', prompt, selectedModel, prepared.url, 'visible seam, border, frame, text, duplicated focal object', { strictReference: true, referenceMode: 'edit' })
      await loadOutputs()
      setMessage(`Generated panorama variation: ${asset.name}`)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Could not generate panorama variation.')
    } finally {
      setBusy(false)
    }
  }

  return <section className="space-y-2 rounded-lg border border-amber-400/25 bg-amber-400/[.035] p-3">
    <div className="flex items-center justify-between gap-2"><span className="text-[11px] font-medium text-amber-100">Fondo infinito</span><span className="text-[8px] text-amber-200/70">Experimental · image edit</span></div>
    <p className="text-[9px] leading-relaxed text-text-muted">Prepara tres copias del fondo y marca las dos costuras para que un modelo de imagen continúe el paisaje. El resultado se guarda en Images y puede elegirse después como plate en 3D Video.</p>
    <input aria-label="Panorama source image" type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={event => { const file = event.target.files?.[0]; if (file) void prepare(file) }} className="block w-full text-[9px] text-text-muted file:mr-2 file:rounded file:border-0 file:bg-bg-tertiary file:px-2 file:py-1 file:text-[9px] file:text-text-secondary" />
    <div className="grid grid-cols-2 gap-2"><label className="text-[9px] text-text-muted">Scene / subject<input value={subject} disabled={busy} onChange={event => setSubject(event.target.value)} className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" /></label><label className="text-[9px] text-text-muted">Style (optional)<input value={style} disabled={busy} onChange={event => setStyle(event.target.value)} placeholder="anime background" className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" /></label></div>
    <div className="grid grid-cols-2 gap-2"><label className="text-[9px] text-text-muted">Seam cover (optional)<input value={occluder} disabled={busy} onChange={event => setOccluder(event.target.value)} placeholder="lamp post / tree" className="mt-0.5 w-full rounded border border-border bg-bg-primary px-2 py-1 text-[10px]" /></label><label className="text-[9px] text-text-muted">Seam width {seamPercent}%<input type="range" min="4" max="25" value={seamPercent} disabled={busy} onChange={event => updateSeam(Number(event.target.value))} className="mt-1 w-full accent-amber-300" /></label></div>
    {prepared && <div className="overflow-hidden rounded border border-amber-300/20 bg-black/20"><img src={prepared.url} alt="Three repeated copies with marked joins" className="block max-h-28 w-full object-contain" /><p className="border-t border-amber-300/10 px-1.5 py-1 text-[8px] text-text-muted">3× preview · each source tile {prepared.width}×{prepared.height}; highlighted bands are the only seams to repair.</p></div>}
    <details className="text-[8px] text-text-muted"><summary className="cursor-pointer">Exact edit prompt</summary><p className="mt-1 rounded bg-black/20 p-1.5 leading-relaxed">{prompt}</p></details>
    <button type="button" disabled={!prepared || busy} onClick={() => void generate()} className="w-full rounded border border-amber-300/45 bg-amber-400/10 px-2 py-1.5 text-[10px] text-amber-100 disabled:opacity-40">{busy ? 'Generating seamless variation…' : `Generate with ${selectedModel || 'selected image model'}`}</button>
    {message && <p className={`text-[8px] ${/generated/i.test(message) ? 'text-emerald-200' : 'text-red-300'}`}>{message}</p>}
  </section>
}
