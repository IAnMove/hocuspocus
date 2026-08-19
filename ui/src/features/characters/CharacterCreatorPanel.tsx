import { useEffect, useMemo, useState } from 'react'
import { Camera, Loader2, PersonStanding, Upload, X } from 'lucide-react'
import * as api from '../../api/client'
import { getFileUrl } from '../../api/client'
import { useStore } from '../../stores/useStore'
import { buildCharacterOrbitPrompt, CHARACTER_ORBIT_VIEWS } from './orbitPrompt'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-violet-400/50 bg-violet-500/15 px-2.5 py-1.5 text-xs text-violet-100 hover:bg-violet-500/25 disabled:opacity-40 disabled:cursor-not-allowed'

interface UploadedRef {
  file: File
  preview: string
  path?: string
  filename?: string
  url?: string
}

interface CapturedView {
  id: string
  label: string
  filename: string
  url: string
}

function resolveOrbitModel(models: Array<{ model_type: string }>): string {
  const preferred = ['minimax_h3_ref2va', 'minimax_h3_ref2va_full', 'minimax_h3']
  return preferred.find(id => models.some(model => model.model_type === id)) || 'minimax_h3_ref2va'
}

export function CharacterCreatorPanel() {
  const models = useStore(s => s.models)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const loadOutputs = useStore(s => s.loadOutputs)
  const [face, setFace] = useState<UploadedRef | null>(null)
  const [outfit, setOutfit] = useState<UploadedRef | null>(null)
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobMessage, setJobMessage] = useState('')
  const [videoName, setVideoName] = useState<string | null>(null)
  const [views, setViews] = useState<CapturedView[]>([])
  const [error, setError] = useState<string | null>(null)
  const modelType = useMemo(() => resolveOrbitModel(models), [models])

  useEffect(() => () => {
    if (face?.preview) URL.revokeObjectURL(face.preview)
    if (outfit?.preview) URL.revokeObjectURL(outfit.preview)
  }, [face, outfit])

  const pickFile = (kind: 'face' | 'outfit', file: File) => {
    const preview = URL.createObjectURL(file)
    const next = { file, preview }
    if (kind === 'face') {
      if (face?.preview) URL.revokeObjectURL(face.preview)
      setFace(next)
    } else {
      if (outfit?.preview) URL.revokeObjectURL(outfit.preview)
      setOutfit(next)
    }
  }

  const uploadRef = async (ref: UploadedRef): Promise<UploadedRef> => {
    if (ref.path) return ref
    const uploaded = await api.uploadImage(ref.file)
    return { ...ref, path: uploaded.path, filename: uploaded.filename, url: uploaded.url }
  }

  const generateOrbit = async () => {
    if (!face || !outfit) return
    setBusy(true)
    setError(null)
    setViews([])
    setVideoName(null)
    try {
      const faceRef = await uploadRef(face)
      const outfitRef = await uploadRef(outfit)
      setFace(faceRef)
      setOutfit(outfitRef)
      const submitted = await api.submitGeneration({
        model_type: modelType,
        generation_mode: 'video',
        prompt: buildCharacterOrbitPrompt(),
        negative_prompt: 'motion blur, extra limbs, extra faces, readable text, watermark, floor line, backdrop shadows, music, speech, moving hair, moving cloth',
        resolution: '864x480',
        video_length: 124,
        num_inference_steps: 20,
        guidance_scale: 1,
        seed: -1,
        workspace: activeWorkspace,
        h3_reference_mode: 'references',
        image_refs: [faceRef.path, outfitRef.path],
        minimax_h3_references: [
          {
            id: 'face',
            type: 'image',
            path: faceRef.path,
            filename: faceRef.filename,
            url: faceRef.url,
            role: 'the identity and appearance of the character',
          },
          {
            id: 'outfit',
            type: 'image',
            path: outfitRef.path,
            filename: outfitRef.filename,
            url: outfitRef.url,
            role: 'the outfit and costume worn by the character; ignore the face and background',
          },
        ],
        video_prompt_type: 'I',
      })
      setJobId(submitted.job_id)
      setJobMessage('Orbit queued…')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    const tick = async () => {
      try {
        const status = await api.fetchJobStatus(jobId)
        if (cancelled) return
        setJobMessage(status.message || status.status)
        if (status.status === 'completed') {
          const name = status.output_files.find(file => /\.(mp4|webm|mov)$/i.test(file)) || status.output_files[0] || null
          setVideoName(name)
          setBusy(false)
          setJobId(null)
          void loadOutputs()
          return
        }
        if (status.status === 'failed' || status.status === 'cancelled') {
          setError(status.error || `Orbit ${status.status}`)
          setBusy(false)
          setJobId(null)
          return
        }
        window.setTimeout(() => { void tick() }, 2000)
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason))
          setBusy(false)
          setJobId(null)
        }
      }
    }
    void tick()
    return () => { cancelled = true }
  }, [jobId, loadOutputs])

  const takePhotos = async () => {
    if (!videoName) return
    setBusy(true)
    setError(null)
    try {
      const metadata = await api.fetchOutputMetadata(videoName, activeWorkspace).catch(() => null)
      const rawLength = metadata?.params?.video_length
      const duration = typeof rawLength === 'number' && rawLength > 0 ? rawLength / 24 : 5.17
      const captured: CapturedView[] = []
      for (const view of CHARACTER_ORBIT_VIEWS) {
        const shot = await api.captureVideoEditorFrame({
          source: videoName,
          time: Math.max(0, duration * view.fraction),
          name: `character_${view.id}`,
        })
        captured.push({
          id: view.id,
          label: view.label,
          filename: shot.filename,
          url: shot.url || getFileUrl(shot.filename),
        })
      }
      setViews(captured)
      void loadOutputs()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section aria-label="Character Creator" className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-bg-primary">
      <header className="border-b border-border bg-bg-secondary px-3 py-2">
        <h2 className="text-sm font-semibold text-text-primary">Character Creator</h2>
        <p className="text-[10px] text-text-muted">
          MiniMax H3 nativo: cara + traje, órbita 360, luego Take photo para frente / lados / espalda. No usa Comfy.
        </p>
      </header>
      <div className="flex-1 overflow-y-auto p-3 md:p-4">
        <div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-[20rem_minmax(0,1fr)]">
          <div className="space-y-3">
            <RefPicker
              label="Picture 1 · Cara / identidad"
              hint="Se conserva el rostro y el estilo. Se ignora el fondo."
              value={face}
              onPick={file => pickFile('face', file)}
              onClear={() => setFace(null)}
            />
            <RefPicker
              label="Picture 2 · Traje / disfraz"
              hint="Se copia ropa y materiales. Se ignora la cara y el escenario."
              value={outfit}
              onPick={file => pickFile('outfit', file)}
              onClear={() => setOutfit(null)}
            />
            <p className="text-[10px] text-text-muted">Modelo: {modelType} · 124 frames · fondo gris seamless</p>
            <button type="button" className={primary + ' w-full'} disabled={busy || !face || !outfit} onClick={() => void generateOrbit()}>
              {busy && !videoName ? <Loader2 size={13} className="animate-spin" /> : <PersonStanding size={13} />}
              Generar órbita 360
            </button>
            <button type="button" className={button + ' w-full'} disabled={busy || !videoName} onClick={() => void takePhotos()}>
              {busy && videoName ? <Loader2 size={13} className="animate-spin" /> : <Camera size={13} />}
              Take photo · 4 vistas
            </button>
            {jobMessage && <p className="text-[11px] text-text-secondary">{jobMessage}</p>}
            {error && <p className="text-[11px] text-red-300">{error}</p>}
          </div>

          <div className="space-y-3">
            <div className="overflow-hidden rounded-xl border border-border bg-black">
              {videoName ? (
                <video src={getFileUrl(videoName)} controls className="aspect-video w-full object-contain" />
              ) : (
                <div className="flex aspect-video flex-col items-center justify-center gap-2 text-text-muted">
                  <PersonStanding size={22} />
                  <span className="text-[11px]">Aquí aparecerá el vídeo de órbita</span>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {CHARACTER_ORBIT_VIEWS.map(view => {
                const captured = views.find(item => item.id === view.id)
                return (
                  <figure key={view.id} className="overflow-hidden rounded-lg border border-border bg-bg-secondary">
                    {captured ? (
                      <img src={captured.url} alt={view.label} className="aspect-[3/4] w-full object-cover" />
                    ) : (
                      <div className="flex aspect-[3/4] items-center justify-center text-[10px] text-text-muted">Sin foto</div>
                    )}
                    <figcaption className="px-2 py-1 text-[10px] text-text-secondary">{view.label}</figcaption>
                  </figure>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

function RefPicker({
  label, hint, value, onPick, onClear,
}: {
  label: string
  hint: string
  value: UploadedRef | null
  onPick: (file: File) => void
  onClear: () => void
}) {
  return (
    <div className="rounded-xl border border-border bg-bg-secondary p-3">
      <div className="text-xs font-medium text-text-primary">{label}</div>
      <p className="mt-1 text-[10px] text-text-muted">{hint}</p>
      {value ? (
        <div className="relative mt-2 overflow-hidden rounded-lg border border-border">
          <img src={value.preview} alt="" className="h-40 w-full object-cover" />
          <button type="button" className="absolute right-2 top-2 rounded bg-black/60 p-1 text-white" onClick={onClear} aria-label={`Quitar ${label}`}>
            <X size={12} />
          </button>
        </div>
      ) : (
        <button
          type="button"
          className="mt-2 flex h-28 w-full flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border text-text-muted hover:border-violet-400/50"
          onClick={() => {
            const input = document.createElement('input')
            input.type = 'file'
            input.accept = 'image/*'
            input.onchange = event => {
              const file = (event.target as HTMLInputElement).files?.[0]
              if (file) onPick(file)
            }
            input.click()
          }}
        >
          <Upload size={14} />
          <span className="text-[10px]">Soltar o elegir imagen</span>
        </button>
      )}
    </div>
  )
}

export default CharacterCreatorPanel
