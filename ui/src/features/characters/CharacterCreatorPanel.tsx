import { useEffect, useMemo, useRef, useState } from 'react'
import { Box, Camera, Loader2, PersonStanding, Plus, Upload, X, Zap } from 'lucide-react'
import * as api from '../../api/client'
import { getFileUrl } from '../../api/client'
import { useStore } from '../../stores/useStore'
import {
  buildCharacterOrbitPrompt,
  CHARACTER_ORBIT_VIEWS,
  CHARACTER_SHEET_FRAMES,
  CHARACTER_SHEET_RESOLUTION,
  CHARACTER_SHEET_STEPS,
  needsVisionDescribe,
  viewCaptureTime,
  type HunyuanView,
  type OrbitRefRole,
  type OrbitSubjectKind,
} from './orbitPrompt'

const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-violet-400/50 bg-violet-500/15 px-2.5 py-1.5 text-xs text-violet-100 hover:bg-violet-500/25 disabled:opacity-40 disabled:cursor-not-allowed'
const MAX_REFS = 9

interface UploadedRef {
  id: string
  role: OrbitRefRole
  file: File
  preview: string
  path?: string
  filename?: string
  url?: string
}

interface CapturedView {
  id: string
  hunyuan: HunyuanView
  label: string
  filename: string
  url: string
}

const EXTRA_ROLES: Array<{ id: OrbitRefRole; label: string }> = [
  { id: 'extra', label: 'Otro ángulo / detalle' },
  { id: 'face', label: 'Solo cara' },
  { id: 'outfit', label: 'Solo ropa' },
  { id: 'accessory', label: 'Accesorio / objeto extra' },
]

function resolveOrbitModel(models: Array<{ model_type: string }>): string {
  const preferred = ['minimax_h3_ref2va', 'minimax_h3_ref2va_full', 'minimax_h3']
  return preferred.find(id => models.some(model => model.model_type === id)) || 'minimax_h3_ref2va'
}

function newId(): string {
  return `ref-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export function CharacterCreatorPanel() {
  const models = useStore(s => s.models)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const loadOutputs = useStore(s => s.loadOutputs)
  const [kind, setKind] = useState<OrbitSubjectKind>('character')
  const [refs, setRefs] = useState<UploadedRef[]>([])
  const [aPrompt, setAPrompt] = useState('')
  const [showAPrompt, setShowAPrompt] = useState(false)
  const [useTurbo, setUseTurbo] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobMessage, setJobMessage] = useState('')
  const [videoName, setVideoName] = useState<string | null>(null)
  const [views, setViews] = useState<CapturedView[]>([])
  const [hunyuanJobId, setHunyuanJobId] = useState<string | null>(null)
  const [hunyuanMessage, setHunyuanMessage] = useState('')
  const [hunyuanGlb, setHunyuanGlb] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const modelType = useMemo(() => resolveOrbitModel(models), [models])
  const readyRefs = refs.filter(ref => Boolean(ref.file))
  const refsRef = useRef(refs)
  refsRef.current = refs

  useEffect(() => () => {
    refsRef.current.forEach(ref => { if (ref.preview) URL.revokeObjectURL(ref.preview) })
  }, [])

  const setRefFile = (id: string | null, file: File, role: OrbitRefRole) => {
    const preview = URL.createObjectURL(file)
    setRefs(current => {
      if (!id) {
        return [...current, { id: newId(), role, file, preview }]
      }
      return current.map(ref => {
        if (ref.id !== id) return ref
        if (ref.preview) URL.revokeObjectURL(ref.preview)
        return { ...ref, file, preview, path: undefined, filename: undefined, url: undefined }
      })
    })
  }

  const clearRef = (id: string) => {
    setRefs(current => {
      const match = current.find(ref => ref.id === id)
      if (match?.preview) URL.revokeObjectURL(match.preview)
      return current.filter(ref => ref.id !== id)
    })
  }

  const setRole = (id: string, role: OrbitRefRole) => {
    setRefs(current => current.map(ref => ref.id === id ? { ...ref, role } : ref))
  }

  const uploadRef = async (ref: UploadedRef): Promise<UploadedRef> => {
    if (ref.path) return ref
    const uploaded = await api.uploadImage(ref.file)
    return { ...ref, path: uploaded.path, filename: uploaded.filename, url: uploaded.url }
  }

  const generateOrbit = async () => {
    if (!readyRefs.length) return
    setBusy(true)
    setError(null)
    setViews([])
    setVideoName(null)
    setHunyuanGlb(null)
    setHunyuanMessage('')
    try {
      const uploaded: UploadedRef[] = []
      for (const ref of readyRefs) uploaded.push(await uploadRef(ref))
      setRefs(current => current.map(ref => uploaded.find(item => item.id === ref.id) || ref))
      let resolvedAPrompt = aPrompt.trim()
      if (needsVisionDescribe(resolvedAPrompt)) {
        setJobMessage('MiniMax está describiendo la imagen…')
        const described = await api.describeCharacterRefs({
          kind,
          image_paths: uploaded.map(ref => ref.path).filter((path): path is string => Boolean(path)),
          roles: uploaded.map(ref => ref.role),
          workspace: activeWorkspace,
        })
        resolvedAPrompt = described.a_prompt.trim()
        setAPrompt(resolvedAPrompt)
        setShowAPrompt(true)
      }
      const submitted = await api.submitGeneration({
        model_type: modelType,
        generation_mode: 'video',
        prompt: buildCharacterOrbitPrompt(kind, uploaded.map(ref => ({ role: ref.role })), resolvedAPrompt),
        negative_prompt: 'motion blur, extra limbs, extra faces, readable text, watermark, floor line, backdrop shadows, music, speech, moving hair, moving cloth',
        resolution: CHARACTER_SHEET_RESOLUTION,
        video_length: CHARACTER_SHEET_FRAMES,
        num_inference_steps: useTurbo ? 4 : CHARACTER_SHEET_STEPS,
        guidance_scale: 1,
        seed: -1,
        workspace: activeWorkspace,
        h3_reference_mode: 'references',
        h3_ref_image_size: 'max',
        minimax_h3_reference_detail: 'max',
        minimax_h3_turbo_mode: useTurbo,
        image_refs: uploaded.map(ref => ref.path),
        minimax_h3_references: uploaded.map((ref, index) => ({
          id: ref.id,
          type: 'image',
          path: ref.path,
          filename: ref.filename,
          url: ref.url,
          role: ref.role === 'subject'
            ? `the complete ${kind} in picture ${index + 1}`
            : `${ref.role} reference from picture ${index + 1}`,
        })),
        video_prompt_type: 'I',
      })
      setJobId(submitted.job_id)
      setJobMessage('Órbita H3 en cola…')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
    }
  }

  const takePhotos = async (sourceName: string) => {
    setBusy(true)
    setError(null)
    try {
      const metadata = await api.fetchOutputMetadata(sourceName, activeWorkspace).catch(() => null)
      const rawLength = metadata?.params?.video_length
      const duration = typeof rawLength === 'number' && rawLength > 0
        ? rawLength / 24
        : CHARACTER_SHEET_FRAMES / 24
      const captured: CapturedView[] = []
      for (const view of CHARACTER_ORBIT_VIEWS) {
        const shot = await api.captureVideoEditorFrame({
          source: sourceName,
          time: Math.min(viewCaptureTime(view.frame), Math.max(0, duration - 0.04)),
          name: `${kind}_${view.id}`,
        })
        captured.push({
          id: view.id,
          hunyuan: view.hunyuan,
          label: kind === 'object' ? view.objectLabel : view.label,
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
          setJobId(null)
          void loadOutputs()
          if (name) void takePhotos(name)
          else setBusy(false)
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

  const generateHunyuan = async () => {
    const front = views.find(view => view.hunyuan === 'front')
    if (!front) return
    setBusy(true)
    setError(null)
    setHunyuanGlb(null)
    try {
      const images = Object.fromEntries(
        views.map(view => [view.hunyuan, view.filename]),
      ) as Partial<Record<HunyuanView, string>>
      const job = await api.startHunyuan3DJob({
        operation: 'generate',
        preset: 'multiview',
        model_id: 'hunyuan3d-2mv-turbo',
        workspace: activeWorkspace,
        images,
        texture_mode: 'v2-turbo',
        cpu_offload: true,
        flashvdm: true,
        remove_background: true,
        output_format: 'glb',
      })
      setHunyuanJobId(job.job_id)
      setHunyuanMessage(job.message || 'Hunyuan3D en cola…')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!hunyuanJobId) return
    let cancelled = false
    const tick = async () => {
      try {
        const status = await api.fetchHunyuan3DJob(hunyuanJobId)
        if (cancelled) return
        setHunyuanMessage(status.message || status.status)
        if (status.status === 'completed') {
          setHunyuanGlb(status.filename)
          setHunyuanJobId(null)
          setBusy(false)
          void loadOutputs()
          if (status.filename) void import('@google/model-viewer')
          return
        }
        if (status.status === 'failed' || status.status === 'cancelled') {
          setError(status.error || `Hunyuan3D ${status.status}`)
          setHunyuanJobId(null)
          setBusy(false)
          return
        }
        window.setTimeout(() => { void tick() }, 1500)
      } catch (reason) {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason))
          setHunyuanJobId(null)
          setBusy(false)
        }
      }
    }
    void tick()
    return () => { cancelled = true }
  }, [hunyuanJobId, loadOutputs])

  return (
    <section aria-label="Character Creator" className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-bg-primary">
      <header className="border-b border-border bg-bg-secondary px-3 py-2">
        <h2 className="text-sm font-semibold text-text-primary">Character Creator</h2>
        <p className="text-[10px] text-text-muted">
          Sube una imagen. MiniMax describe el sujeto y arma el prompt de órbita. No hace falta escribir nada.
        </p>
      </header>
      <div className="flex-1 overflow-y-auto p-3 md:p-4">
        <div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <div className="space-y-3">
            <div className="flex gap-1">
              <button type="button" className={`${button} flex-1 ${kind === 'character' ? 'border-violet-400/40 text-violet-100' : ''}`} onClick={() => setKind('character')}>Personaje</button>
              <button type="button" className={`${button} flex-1 ${kind === 'object' ? 'border-violet-400/40 text-violet-100' : ''}`} onClick={() => setKind('object')}>Objeto</button>
            </div>

            <RefPicker
              label={kind === 'object' ? 'Imagen principal del objeto' : 'Imagen principal del sujeto'}
              hint="Obligatoria. Una sola basta. MiniMax lee la foto y escribe el A Prompt."
              value={refs[0] || null}
              roleLocked="subject"
              onPick={file => {
                if (refs[0]) setRefFile(refs[0].id, file, 'subject')
                else setRefFile(null, file, 'subject')
              }}
              onClear={() => { if (refs[0]) clearRef(refs[0].id) }}
            />

            {refs.slice(1).map((ref, index) => (
              <RefPicker
                key={ref.id}
                label={`Referencia extra ${index + 1}`}
                hint="Opcional. Cara, ropa, accesorio u otro ángulo."
                value={ref}
                onPick={file => setRefFile(ref.id, file, ref.role)}
                onClear={() => clearRef(ref.id)}
                onRole={role => setRole(ref.id, role)}
              />
            ))}

            {refs.length < MAX_REFS && (
              <button
                type="button"
                className={`${button} w-full`}
                onClick={() => {
                  const input = document.createElement('input')
                  input.type = 'file'
                  input.accept = 'image/*'
                  input.onchange = event => {
                    const file = (event.target as HTMLInputElement).files?.[0]
                    if (file) setRefFile(null, file, kind === 'object' ? 'extra' : 'outfit')
                  }
                  input.click()
                }}
              >
                <Plus size={13} /> Añadir referencia opcional
              </button>
            )}

            <div className="space-y-1">
              <button type="button" className={`${button} w-full`} onClick={() => setShowAPrompt(open => !open)}>
                {showAPrompt ? 'Ocultar A Prompt' : 'A Prompt opcional'}
              </button>
              {showAPrompt && (
                <textarea
                  value={aPrompt}
                  onChange={event => setAPrompt(event.target.value)}
                  rows={5}
                  placeholder="Vacío = MiniMax describe las fotos al generar."
                  className="w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[11px] text-text-primary"
                />
              )}
            </div>

            <label className="flex items-center gap-2 text-[11px] text-text-secondary">
              <input type="checkbox" checked={useTurbo} onChange={event => setUseTurbo(event.target.checked)} className="accent-violet-400" />
              <Zap size={12} className={useTurbo ? 'text-violet-200' : 'text-text-muted'} />
              Turbo LoRA (más rápido, menos fidelidad)
            </label>

            <p className="text-[10px] text-text-muted">
              {modelType} · {CHARACTER_SHEET_RESOLUTION} 9:16 · {CHARACTER_SHEET_FRAMES} frames · grabs 2 / 21 / 42 / 63
            </p>
            <button type="button" className={primary + ' w-full'} disabled={busy || readyRefs.length === 0} onClick={() => void generateOrbit()}>
              {busy && !videoName ? <Loader2 size={13} className="animate-spin" /> : <PersonStanding size={13} />}
              Generar órbita 360
            </button>
            <button type="button" className={button + ' w-full'} disabled={busy || !videoName} onClick={() => { if (videoName) void takePhotos(videoName) }}>
              {busy && videoName && !hunyuanJobId ? <Loader2 size={13} className="animate-spin" /> : <Camera size={13} />}
              Take photo · 4 vistas
            </button>
            <button type="button" className={primary + ' w-full'} disabled={busy || views.length < 4} onClick={() => void generateHunyuan()}>
              {busy && hunyuanJobId ? <Loader2 size={13} className="animate-spin" /> : <Box size={13} />}
              Generar Hunyuan3D
            </button>
            {jobMessage && <p className="text-[11px] text-text-secondary">{jobMessage}</p>}
            {hunyuanMessage && <p className="text-[11px] text-text-secondary">{hunyuanMessage}</p>}
            {error && <p className="text-[11px] text-red-300">{error}</p>}
          </div>

          <div className="space-y-3">
            <div className="overflow-hidden rounded-xl border border-border bg-black">
              {videoName ? (
                <video src={getFileUrl(videoName)} controls className="mx-auto aspect-[9/16] max-h-[420px] w-full object-contain" />
              ) : (
                <div className="flex aspect-[9/16] max-h-[420px] flex-col items-center justify-center gap-2 text-text-muted">
                  <PersonStanding size={22} />
                  <span className="text-[11px]">Sube al menos una imagen y genera la órbita</span>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {CHARACTER_ORBIT_VIEWS.map(view => {
                const captured = views.find(item => item.id === view.id)
                const label = kind === 'object' ? view.objectLabel : view.label
                return (
                  <figure key={view.id} className="overflow-hidden rounded-lg border border-border bg-bg-secondary">
                    {captured ? (
                      <img src={captured.url} alt={label} className="aspect-[3/4] w-full object-cover" />
                    ) : (
                      <div className="flex aspect-[3/4] items-center justify-center text-[10px] text-text-muted">Sin foto</div>
                    )}
                    <figcaption className="px-2 py-1 text-[10px] text-text-secondary">{label}</figcaption>
                  </figure>
                )
              })}
            </div>
            {hunyuanGlb && (
              <div className="overflow-hidden rounded-xl border border-border bg-bg-secondary">
                <model-viewer
                  src={getFileUrl(hunyuanGlb)}
                  alt="Hunyuan3D"
                  camera-controls
                  auto-rotate
                  shadow-intensity="1"
                  className="h-72 w-full"
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}

function RefPicker({
  label, hint, value, roleLocked, onPick, onClear, onRole,
}: {
  label: string
  hint: string
  value: UploadedRef | null
  roleLocked?: OrbitRefRole
  onPick: (file: File) => void
  onClear: () => void
  onRole?: (role: OrbitRefRole) => void
}) {
  return (
    <div className="rounded-xl border border-border bg-bg-secondary p-3">
      <div className="text-xs font-medium text-text-primary">{label}</div>
      <p className="mt-1 text-[10px] text-text-muted">{hint}</p>
      {!roleLocked && value && onRole && (
        <select
          value={value.role}
          onChange={event => onRole(event.target.value as OrbitRefRole)}
          className="mt-2 w-full rounded-md border border-border bg-bg-primary px-2 py-1 text-[11px] text-text-primary"
        >
          {EXTRA_ROLES.map(role => <option key={role.id} value={role.id}>{role.label}</option>)}
        </select>
      )}
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
