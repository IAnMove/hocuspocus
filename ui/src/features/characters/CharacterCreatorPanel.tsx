import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Box, Camera, Loader2, PersonStanding, Plus, Upload, X } from 'lucide-react'
import * as api from '../../api/client'
import { getFileUrl } from '../../api/client'
import { useSerializedPoll } from '../../hooks/useSerializedPoll'
import { useStore } from '../../stores/useStore'
import { queueFaceRigHandoff } from '../../lib/characterKitHandoff'
import { safeStorageGet, safeStorageSet } from '../../lib/safeStorage'
import {
  attachCharacterCreatorMeshForWorkspace,
  characterCreatorHistoryKey,
  parseCharacterCreatorHistory,
  rememberCharacterCreatorSheetForWorkspace,
  type CharacterCreatorHistoryEntry,
} from './characterCreatorHistory'
import { useUiTranslation } from '../../i18n'
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

const historyStorage = {
  getItem: (key: string) => safeStorageGet('local', key),
  setItem: (key: string, value: string) => { safeStorageSet('local', key, value) },
}

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
  time: number
}

const EXTRA_ROLE_IDS: OrbitRefRole[] = ['extra', 'face', 'outfit', 'accessory']

function resolveOrbitModel(models: Array<{ model_type: string }>): string {
  // Character Creator uses the isolated Comfy/ConvRot worker. It already
  // contains the Ref2VA checkpoint used by PoopMan333's 6-panel workflow;
  // native H3 remains the fallback for installations without Legacy assets.
  const preferred = ['minimax_h3_legacy', 'minimax_h3_ref2va', 'minimax_h3_ref2va_full', 'minimax_h3']
  return preferred.find(id => models.some(model => model.model_type === id)) || 'minimax_h3_ref2va'
}

function newId(): string {
  return `ref-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
}

export function CharacterCreatorPanel() {
  const { t } = useUiTranslation('characters')
  const models = useStore(s => s.models)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const llmProvider = useStore(s => s.productionProfile.text.provider)
  const outputFiles = useStore(s => s.outputs)
  const loadOutputs = useStore(s => s.loadOutputs)
  const setMediaFilter = useStore(s => s.setMediaFilter)
  const [kind, setKind] = useState<OrbitSubjectKind>('character')
  const [refs, setRefs] = useState<UploadedRef[]>([])
  const [aPrompt, setAPrompt] = useState('')
  const [showAPrompt, setShowAPrompt] = useState(false)
  const [busy, setBusy] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobMessage, setJobMessage] = useState('')
  const [videoName, setVideoName] = useState<string | null>(null)
  const [views, setViews] = useState<CapturedView[]>([])
  const [videoDuration, setVideoDuration] = useState(CHARACTER_SHEET_FRAMES / 24)
  const [selectedViewId, setSelectedViewId] = useState<string | null>(null)
  const [selectedTime, setSelectedTime] = useState(0)
  const videoPreviewRef = useRef<HTMLVideoElement>(null)
  const [hunyuanJobId, setHunyuanJobId] = useState<string | null>(null)
  const [hunyuanMessage, setHunyuanMessage] = useState('')
  const [hunyuanGlb, setHunyuanGlb] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<CharacterCreatorHistoryEntry[]>([])
  const modelType = useMemo(() => resolveOrbitModel(models), [models])
  const readyRefs = refs.filter(ref => Boolean(ref.file))
  const refsRef = useRef(refs)
  const aPromptRef = useRef(aPrompt)
  const hunyuanGlbRef = useRef(hunyuanGlb)
  const activeWorkspaceRef = useRef(activeWorkspace)
  const orbitWorkspaceRef = useRef(activeWorkspace)
  const hunyuanWorkspaceRef = useRef(activeWorkspace)
  refsRef.current = refs
  aPromptRef.current = aPrompt
  hunyuanGlbRef.current = hunyuanGlb
  activeWorkspaceRef.current = activeWorkspace

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
    const workspaceAtStart = activeWorkspace
    orbitWorkspaceRef.current = workspaceAtStart
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
        if (llmProvider !== 'minimax' && llmProvider !== 'local') {
          throw new Error(t('creator.errors.autoDescribe'))
        }
        setJobMessage(llmProvider === 'minimax' ? t('creator.status.minimaxDescribe') : t('creator.status.llmDescribe'))
        const described = await api.describeCharacterRefs({
          kind,
          image_paths: uploaded.map(ref => ref.path).filter((path): path is string => Boolean(path)),
          roles: uploaded.map(ref => ref.role),
          workspace: workspaceAtStart,
        })
        resolvedAPrompt = described.a_prompt.trim()
        setAPrompt(resolvedAPrompt)
        setShowAPrompt(true)
      }
      const submitted = await api.submitGeneration({
        model_type: modelType,
        generation_mode: 'video',
        prompt: buildCharacterOrbitPrompt(kind, uploaded.map(ref => ({ role: ref.role })), resolvedAPrompt),
        resolution: CHARACTER_SHEET_RESOLUTION,
        video_length: CHARACTER_SHEET_FRAMES,
        // This is the isolated PoopMan333-compatible 6-panel recipe. Do not
        // send the native H3 Turbo adapter here: it is a different LoRA and
        // its low-step sampler produces the broken multi-shot result seen in
        // the native runtime.
        character_sheet_engine: 'poopman333_6_panel',
        num_inference_steps: CHARACTER_SHEET_STEPS,
        guidance_scale: 1,
        seed: -1,
        workspace: workspaceAtStart,
        h3_reference_mode: 'references',
        h3_ref_image_size: 'max',
        minimax_h3_reference_detail: 'max',
        minimax_h3_turbo_mode: false,
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
      setJobMessage(t('creator.status.orbitQueued'))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
    }
  }

  const takePhotos = useCallback(async (sourceName: string, workspace = activeWorkspace) => {
    setBusy(true)
    setError(null)
    try {
      const metadata = await api.fetchOutputMetadata(sourceName, workspace).catch(() => null)
      const rawLength = metadata?.params?.video_length
      const duration = typeof rawLength === 'number' && rawLength > 0
        ? rawLength / 24
        : CHARACTER_SHEET_FRAMES / 24
      setVideoDuration(duration)
      const captured: CapturedView[] = []
      for (const view of CHARACTER_ORBIT_VIEWS) {
        const time = Math.min(viewCaptureTime(view.frame), Math.max(0, duration - 0.04))
        const shot = await api.captureVideoEditorFrame({
          source: sourceName,
          time,
          name: `${kind}_${view.id}`,
          workspace,
        })
        captured.push({
          id: view.id,
          hunyuan: view.hunyuan,
          label: kind === 'object' ? view.objectLabel : view.label,
          filename: shot.filename,
          url: shot.url || getFileUrl(shot.filename, workspace),
          time,
        })
      }
      const entry: CharacterCreatorHistoryEntry = {
        id: `sheet-${sourceName}`,
        name: aPromptRef.current.trim().split(/[.!\n]/)[0].slice(0, 48) || sourceName.replace(/\.[^.]+$/, ''),
        kind,
        videoName: sourceName,
        views: captured,
        hunyuanGlb: hunyuanGlbRef.current,
        workspace,
        createdAt: new Date().toISOString(),
      }
      const next = rememberCharacterCreatorSheetForWorkspace(historyStorage, workspace, entry)
      if (activeWorkspaceRef.current === workspace) {
        setViews(captured)
        setSelectedViewId(captured[0]?.id || null)
        setSelectedTime(captured[0]?.time || 0)
        setHistory(next)
      }
      void loadOutputs()
    } catch (reason) {
      if (activeWorkspaceRef.current === workspace) {
        setError(reason instanceof Error ? reason.message : String(reason))
      }
    } finally {
      setBusy(false)
    }
  }, [activeWorkspace, kind, loadOutputs])

  const openFaceRigFromCreator = async () => {
    if (kind !== 'character') {
      setError(t('creator.errors.faceRigKitsOnly'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const captured = views.find(view => view.id === selectedViewId) ?? views.find(view => view.id === 'front') ?? views[0]
      let source = captured?.url || (captured?.filename ? getFileUrl(captured.filename, activeWorkspace) : '')
      if (!source || source.startsWith('blob:') || source.startsWith('data:')) {
        const subject = refs[0]
        if (!subject?.file) throw new Error(t('creator.errors.needViewOrUpload'))
        const uploaded = await uploadRef(subject)
        setRefs(current => current.map(ref => ref.id === uploaded.id ? uploaded : ref))
        source = uploaded.url || (uploaded.filename ? getFileUrl(uploaded.filename, activeWorkspace) : '')
      }
      const name = aPrompt.trim().split(/[.!\n]/)[0].slice(0, 48) || 'Character from Creator'
      queueFaceRigHandoff({ name, source, workspace: activeWorkspace })
      setMediaFilter('scene3d')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  const replaceSelectedView = async () => {
    if (!videoName || !selectedViewId) return
    const selected = views.find(view => view.id === selectedViewId)
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      const time = Math.min(selectedTime, Math.max(0, videoDuration - 0.04))
      const shot = await api.captureVideoEditorFrame({
        source: videoName,
        time,
        name: `${kind}_${selected.id}_manual`,
        workspace: activeWorkspace,
      })
      setViews(current => current.map(view => view.id === selected.id
        ? { ...view, filename: shot.filename, url: shot.url || getFileUrl(shot.filename, activeWorkspace), time }
        : view,
      ))
      void loadOutputs()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    setHistory(parseCharacterCreatorHistory(safeStorageGet('local', characterCreatorHistoryKey(activeWorkspace))))
  }, [activeWorkspace])

  const restoredWorkspaceRef = useRef<string | null>(null)
  const busyRef = useRef(busy)
  const jobIdRef = useRef(jobId)
  const hunyuanJobIdRef = useRef(hunyuanJobId)
  busyRef.current = busy
  jobIdRef.current = jobId
  hunyuanJobIdRef.current = hunyuanJobId
  useEffect(() => {
    if (!outputFiles.length) return
    if (restoredWorkspaceRef.current === activeWorkspace) return
    if (busy || jobId || hunyuanJobId || readyRefs.length) {
      restoredWorkspaceRef.current = activeWorkspace
      return
    }
    restoredWorkspaceRef.current = activeWorkspace
    let cancelled = false
    const restoreLatestCharacterSheet = async () => {
      try {
        for (const output of outputFiles.filter(item => item.type === 'video').slice(0, 50)) {
          const metadata = await api.fetchOutputMetadata(output.name, activeWorkspace).catch(() => null)
          if (metadata?.params?.character_sheet_engine !== 'poopman333_6_panel') continue
          if (cancelled || busyRef.current || jobIdRef.current || hunyuanJobIdRef.current) return
          setVideoName(output.name)
          await takePhotos(output.name)
          return
        }
      } catch {
        // Recovery is best effort; a fresh panel remains fully usable.
      }
    }
    void restoreLatestCharacterSheet()
    return () => { cancelled = true }
  }, [activeWorkspace, busy, hunyuanJobId, jobId, outputFiles, readyRefs.length, takePhotos])

  const orbitFailuresRef = useRef(0)
  useEffect(() => { orbitFailuresRef.current = 0 }, [jobId])
  useSerializedPoll({
    enabled: Boolean(jobId),
    intervalMs: 2000,
    ownerKey: jobId,
    poll: () => api.fetchJobStatus(jobId!),
    onValue: status => {
      orbitFailuresRef.current = 0
      const workspace = orbitWorkspaceRef.current
      const stillOnOrigin = activeWorkspaceRef.current === workspace
      if (stillOnOrigin) setJobMessage(status.message || status.status)
      if (status.status === 'completed') {
        const name = status.output_files.find(file => /\.(mp4|webm|mov)$/i.test(file)) || status.output_files[0] || null
        if (stillOnOrigin) setVideoName(name)
        setJobId(null)
        void loadOutputs()
        if (name) void takePhotos(name, workspace)
        else setBusy(false)
        return
      }
      if (status.status === 'failed' || status.status === 'cancelled') {
        if (stillOnOrigin) setError(status.error || t(status.status === 'cancelled' ? 'creator.errors.orbitCancelled' : 'creator.errors.orbitFailed'))
        setBusy(false)
        setJobId(null)
      }
    },
    onError: reason => {
      orbitFailuresRef.current += 1
      const lost = (reason as Error & { status?: number }).status === 404
      if (!lost && orbitFailuresRef.current < 4) return
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
      setJobId(null)
    },
  })

  const generateHunyuan = async () => {
    const front = views.find(view => view.hunyuan === 'front')
    if (!front) return
    const workspaceAtStart = activeWorkspace
    hunyuanWorkspaceRef.current = workspaceAtStart
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
        workspace: workspaceAtStart,
        images,
        texture_mode: 'v2-turbo',
        cpu_offload: true,
        flashvdm: true,
        remove_background: true,
        output_format: 'glb',
      })
      setHunyuanJobId(job.job_id)
      setHunyuanMessage(job.message || t('creator.status.hunyuanQueued'))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
      setBusy(false)
    }
  }

  const hunyuanFailuresRef = useRef(0)
  useEffect(() => { hunyuanFailuresRef.current = 0 }, [hunyuanJobId])
  useSerializedPoll({
    enabled: Boolean(hunyuanJobId),
    intervalMs: 1500,
    ownerKey: hunyuanJobId,
    poll: () => api.fetchHunyuan3DJob(hunyuanJobId!),
    onValue: status => {
      hunyuanFailuresRef.current = 0
      const workspace = hunyuanWorkspaceRef.current
      const stillOnOrigin = activeWorkspaceRef.current === workspace
      if (stillOnOrigin) setHunyuanMessage(status.message || status.status)
      if (status.status === 'completed') {
        if (stillOnOrigin) setHunyuanGlb(status.filename)
        setHunyuanJobId(null)
        setBusy(false)
        const sheetName = videoName
        const meshName = status.filename
        if (meshName && sheetName) {
          const next = attachCharacterCreatorMeshForWorkspace(historyStorage, workspace, sheetName, meshName)
          if (stillOnOrigin) setHistory(next)
        }
        void loadOutputs()
        if (status.filename) void import('@google/model-viewer')
        return
      }
      if (status.status === 'failed' || status.status === 'cancelled') {
        if (stillOnOrigin) setError(status.error || t(status.status === 'cancelled' ? 'creator.errors.hunyuanCancelled' : 'creator.errors.hunyuanFailed'))
        setHunyuanJobId(null)
        setBusy(false)
      }
    },
    onError: reason => {
      hunyuanFailuresRef.current += 1
      const lost = (reason as Error & { status?: number }).status === 404
      if (!lost && hunyuanFailuresRef.current < 4) return
      setError(reason instanceof Error ? reason.message : String(reason))
      setHunyuanJobId(null)
      setBusy(false)
    },
  })

  const orbitViewLabel = (id: string) => t(kind === 'object' ? `creator.objectViews.${id}` : `creator.views.${id}`)

  return (
    <section aria-label={t('creator.title')} className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-bg-primary">
      <header className="border-b border-border bg-bg-secondary px-3 py-2">
        <h2 className="text-sm font-semibold text-text-primary">{t('creator.title')}</h2>
        <p className="text-[10px] text-text-muted">
          {t('creator.subtitle')}
        </p>
        {kind === 'character' && (
          <button
            type="button"
            className={`${button} mt-2`}
            disabled={busy}
            onClick={() => void openFaceRigFromCreator()}
          >
            {t('creator.openFaceRig')}
          </button>
        )}
        {history.length > 0 && (
          <div className="mt-2 space-y-1">
            <p className="text-[10px] text-text-muted">{t('creator.history')}</p>
            <div className="flex gap-1 overflow-x-auto pb-1">
              {history.map(entry => (
                <button
                  key={entry.id}
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setKind(entry.kind)
                    setVideoName(entry.videoName)
                    setViews(entry.views)
                    setSelectedViewId(entry.views[0]?.id || 'front')
                    setSelectedTime(entry.views[0]?.time || 0)
                    setHunyuanGlb(entry.hunyuanGlb || null)
                    setError(null)
                  }}
                  className={`min-w-[4.5rem] max-w-[5.5rem] shrink-0 overflow-hidden rounded border p-1 text-left ${videoName === entry.videoName ? 'border-violet-400/50 bg-violet-500/15' : 'border-border bg-bg-tertiary'}`}
                >
                  {entry.views[0]?.url
                    ? <img src={entry.views[0].url} alt="" className="mb-1 aspect-square w-full rounded object-cover" />
                    : <div className="mb-1 aspect-square w-full rounded bg-bg-active" />}
                  <span className="block truncate text-[9px] text-text-primary">{entry.name}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </header>
      <div className="flex-1 overflow-y-auto p-3 md:p-4">
        <div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
          <div className="space-y-3">
            <div className="flex gap-1">
              <button type="button" className={`${button} flex-1 ${kind === 'character' ? 'border-violet-400/40 text-violet-100' : ''}`} onClick={() => setKind('character')}>{t('creator.kind.character')}</button>
              <button type="button" className={`${button} flex-1 ${kind === 'object' ? 'border-violet-400/40 text-violet-100' : ''}`} onClick={() => setKind('object')}>{t('creator.kind.object')}</button>
            </div>

            <RefPicker
              label={kind === 'object' ? t('creator.objectImage') : t('creator.subjectImage')}
              hint={t('creator.subjectHint')}
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
                label={t('creator.extraRef', { index: index + 1 })}
                hint={t('creator.extraHint')}
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
                <Plus size={13} /> {t('creator.addOptionalRef')}
              </button>
            )}

            <div className="space-y-1">
              <button type="button" className={`${button} w-full`} onClick={() => setShowAPrompt(open => !open)}>
                {showAPrompt ? t('creator.hideAPrompt') : t('creator.optionalAPrompt')}
              </button>
              {showAPrompt && (
                <textarea
                  value={aPrompt}
                  onChange={event => setAPrompt(event.target.value)}
                  rows={5}
                  placeholder={t('creator.aPromptPlaceholder')}
                  className="w-full rounded-md border border-border bg-bg-secondary px-2 py-1.5 text-[11px] text-text-primary"
                />
              )}
            </div>

            <p className="text-[10px] text-text-muted">
              {t('creator.engineNote')}
            </p>

            <p className="text-[10px] text-text-muted">
              {t('creator.engineMeta', { model: modelType, resolution: CHARACTER_SHEET_RESOLUTION, frames: CHARACTER_SHEET_FRAMES, grabs: '2 / 21 / 42 / 63' })}
            </p>
            <button type="button" className={primary + ' w-full'} disabled={busy || readyRefs.length === 0} onClick={() => void generateOrbit()}>
              {busy && !videoName ? <Loader2 size={13} className="animate-spin" /> : <PersonStanding size={13} />}
              {t('creator.orbitGenerate')}
            </button>
            <button type="button" className={button + ' w-full'} disabled={busy || !videoName} onClick={() => { if (videoName) void takePhotos(videoName) }}>
              {busy && videoName && !hunyuanJobId ? <Loader2 size={13} className="animate-spin" /> : <Camera size={13} />}
              {t('creator.takePhotos')}
            </button>
            <button type="button" className={primary + ' w-full'} disabled={busy || views.length < 4} onClick={() => void generateHunyuan()}>
              {busy && hunyuanJobId ? <Loader2 size={13} className="animate-spin" /> : <Box size={13} />}
              {t('creator.hunyuanGenerate')}
            </button>
            {jobMessage && <p className="text-[11px] text-text-secondary">{jobMessage}</p>}
            {hunyuanMessage && <p className="text-[11px] text-text-secondary">{hunyuanMessage}</p>}
            {error && <p className="text-[11px] text-red-300">{error}</p>}
          </div>

          <div className="space-y-3">
            <div className="overflow-hidden rounded-xl border border-border bg-black">
              {videoName ? (
                <video ref={videoPreviewRef} src={getFileUrl(videoName, activeWorkspace)} controls className="mx-auto aspect-[9/16] max-h-[420px] w-full object-contain" />
              ) : (
                <div className="flex aspect-[9/16] max-h-[420px] flex-col items-center justify-center gap-2 text-text-muted">
                  <PersonStanding size={22} />
                  <span className="text-[11px]">{t('creator.emptyOrbit')}</span>
                </div>
              )}
            </div>
            {videoName && selectedViewId && (
              <div className="rounded-xl border border-violet-400/30 bg-violet-500/5 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-xs font-medium text-text-primary">{t('creator.adjustCapture', { label: orbitViewLabel(selectedViewId) })}</p>
                    <p className="text-[10px] text-text-muted">{t('creator.adjustHint')}</p>
                  </div>
                  <span className="shrink-0 font-mono text-[11px] text-violet-200">{selectedTime.toFixed(2)}s</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max={Math.max(0, videoDuration - 0.04)}
                  step="0.04"
                  value={Math.min(selectedTime, Math.max(0, videoDuration - 0.04))}
                  onChange={event => {
                    const time = Number(event.target.value)
                    setSelectedTime(time)
                    if (videoPreviewRef.current) videoPreviewRef.current.currentTime = time
                  }}
                  className="mt-3 w-full accent-violet-400"
                  aria-label={t('creator.captureTimeAria')}
                />
                <button type="button" className={button + ' mt-2 w-full'} disabled={busy} onClick={() => void replaceSelectedView()}>
                  <Camera size={13} /> {t('creator.replaceView')}
                </button>
              </div>
            )}
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {CHARACTER_ORBIT_VIEWS.map(view => {
                const captured = views.find(item => item.id === view.id)
                const label = orbitViewLabel(view.id)
                const selected = selectedViewId === view.id
                return (
                  <button
                    key={view.id}
                    type="button"
                    onClick={() => {
                      setSelectedViewId(view.id)
                      if (captured) setSelectedTime(captured.time)
                    }}
                    className={`overflow-hidden rounded-lg border bg-bg-secondary text-left transition-colors ${selected ? 'border-violet-400 ring-1 ring-violet-400/50' : 'border-border hover:border-violet-400/50'}`}
                    aria-label={t('creator.selectViewAria', { label })}
                  >
                    {captured ? (
                      <img src={captured.url} alt={label} className="aspect-[3/4] w-full object-cover" />
                    ) : (
                      <div className="flex aspect-[3/4] items-center justify-center text-[10px] text-text-muted">{t('creator.noPhoto')}</div>
                    )}
                    <span className="block px-2 py-1 text-[10px] text-text-secondary">{label}{captured ? ` · ${captured.time.toFixed(2)}s` : ''}</span>
                  </button>
                )
              })}
            </div>
            {hunyuanGlb && (
              <div className="overflow-hidden rounded-xl border border-border bg-bg-secondary">
                <model-viewer
                  src={getFileUrl(hunyuanGlb, activeWorkspace)}
                  alt={t('creator.hunyuanAlt')}
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
  const { t } = useUiTranslation('characters')
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
          {EXTRA_ROLE_IDS.map(id => <option key={id} value={id}>{t(`creator.roles.${id}`)}</option>)}
        </select>
      )}
      {value ? (
        <div className="relative mt-2 overflow-hidden rounded-lg border border-border">
          <img src={value.preview} alt="" className="h-40 w-full object-cover" />
          <button type="button" className="absolute right-2 top-2 rounded bg-black/60 p-1 text-white" onClick={onClear} aria-label={t('creator.removeRefAria', { label })}>
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
          <span className="text-[10px]">{t('creator.dropOrChoose')}</span>
        </button>
      )}
    </div>
  )
}

export default CharacterCreatorPanel
