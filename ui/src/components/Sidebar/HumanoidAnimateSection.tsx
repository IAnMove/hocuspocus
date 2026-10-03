import { useCallback, useEffect, useRef, useState } from 'react'
import { FileUp, Loader2, PlusCircle, RefreshCw, X } from 'lucide-react'
import { animateHumanoid, fetchHumanoidRigs, uploadAnimationFile, type HumanoidAnimateResult, type HumanoidRig, type RigAnimation } from '../../api/model3d'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { DEFAULT_BPM, clampBpm, clipGroups, rigLabel } from './humanoidRig'
import { useClipText } from './humanoidClipText'

const IMPORT_TYPES = '.bvh,.glb,.gltf'

/** Add library clips, or a BVH/glTF animation, to a character already rigged with the humanoid engine. */
export function HumanoidAnimateSection({ clips, refreshKey }: { clips: RigAnimation[]; refreshKey?: string | null }) {
  const { t } = useUiTranslation('scene3d')
  const workspace = useStore(state => state.activeWorkspace) || 'default'
  const [rigs, setRigs] = useState<HumanoidRig[] | null>(null)
  const [rig, setRig] = useState<string | null>(null)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [bpm, setBpm] = useState(DEFAULT_BPM)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<HumanoidAnimateResult | null>(null)
  // Only the latest listing may land. A workspace change remounts this card (see HumanoidAnimateSlot).
  const loads = useRef(0)

  const load = useCallback(async (prefer?: string) => {
    const ticket = ++loads.current
    try {
      const found = await fetchHumanoidRigs(workspace)
      if (ticket !== loads.current) return
      setRigs(found)
      const wanted = (name: string | null | undefined) => Boolean(name) && found.some(item => item.name === name)
      setRig(current => (wanted(prefer) ? prefer! : wanted(current) ? current : found[0]?.name ?? null))
    } catch (err) {
      if (ticket !== loads.current) return
      setRigs([])
      setError(err instanceof Error ? err.message : t('rig.animateFailed'))
    }
  }, [workspace, t])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const toggle = (id: string) => setChosen(current => {
    const next = new Set(current)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const run = async () => {
    if (!rig) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const importFile = file ? await uploadAnimationFile(workspace, file) : null
      const saved = await animateHumanoid({ workspace, source: rig, clips: Array.from(chosen), bpm, importFile })
      setResult(saved)
      setFile(null)
      setChosen(new Set())
      void useStore.getState().maybeRefreshGallery({ message: t('rig.animateSaved', { file: saved.file, count: saved.clips.length }) })
      await load(saved.file)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('rig.animateFailed'))
    } finally {
      setBusy(false)
    }
  }

  const canRun = Boolean(rig) && (chosen.size > 0 || file !== null) && !busy
  return (
    <section className="space-y-2.5 rounded-lg border border-border bg-bg-tertiary p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="flex items-center gap-1.5 text-[11px] font-medium text-text-primary"><PlusCircle size={13} className="text-accent-blue" /> {t('rig.animateTitle')}</p>
          <p className="mt-0.5 text-[9px] leading-relaxed text-text-muted">{t('rig.animateHelp')}</p>
        </div>
        <button type="button" onClick={() => void load()} title={t('rig.refreshOutputs')} className="text-text-muted hover:text-text-primary"><RefreshCw size={11} /></button>
      </div>
      <RigPicker rigs={rigs} rig={rig} onPick={setRig} />
      <ClipChips clips={clips} chosen={chosen} onToggle={toggle} />
      <label className="block text-[10px] uppercase tracking-wider text-text-muted">
        <span className="flex items-center justify-between"><span>{t('rig.bpm')}</span><span className="text-text-primary">{bpm}</span></span>
        <input type="range" min={60} max={180} value={bpm} onChange={event => setBpm(clampBpm(Number(event.target.value)))} className="mt-1 w-full" />
      </label>
      <ImportFile file={file} onFile={setFile} />
      <button type="button" disabled={!canRun} onClick={() => void run()} className={`flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-[11px] font-medium ${canRun ? 'bg-accent-blue/80 text-white hover:bg-accent-blue' : 'cursor-not-allowed border border-border text-text-muted'}`}>
        {busy ? <Loader2 size={12} className="animate-spin" /> : <PlusCircle size={12} />} {busy ? t('rig.animateRunning') : t('rig.animateRun')}
      </button>
      {!canRun && !busy && rig && <p className="text-center text-[9px] text-text-muted">{t('rig.animateChoose')}</p>}
      {error && <p className="whitespace-pre-wrap text-[10px] text-red-300">{error}</p>}
      {result && <AnimateResult result={result} />}
    </section>
  )
}

function RigPicker({ rigs, rig, onPick }: { rigs: HumanoidRig[] | null; rig: string | null; onPick: (name: string) => void }) {
  const { t } = useUiTranslation('scene3d')
  if (rigs === null) return <p className="flex items-center gap-1.5 text-[10px] text-text-muted"><Loader2 size={11} className="animate-spin" /> {t('rig.loading')}</p>
  if (!rigs.length) return <p className="rounded border border-dashed border-border p-2 text-[10px] text-text-muted">{t('rig.animateNone')}</p>
  return (
    <label className="block text-[10px] uppercase tracking-wider text-text-muted">{t('rig.animateCharacter')}
      <select value={rig ?? ''} onChange={event => onPick(event.target.value)} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs normal-case tracking-normal text-text-primary">
        {rigs.map(item => <option key={item.name} value={item.name}>{rigLabel(item.name)} · {t('rig.animateClipCount', { count: item.clips.length })}</option>)}
      </select>
    </label>
  )
}

function ClipChips({ clips, chosen, onToggle }: { clips: RigAnimation[]; chosen: Set<string>; onToggle: (id: string) => void }) {
  const text = useClipText()
  return (
    <div className="space-y-1">
      {clipGroups(clips).map(group => (
        <div key={group.category} className="flex flex-wrap gap-1">
          {group.clips.map(clip => (
            <button key={clip.id} type="button" aria-pressed={chosen.has(clip.id)} onClick={() => onToggle(clip.id)} title={text(clip, 'humanoid').description}
              className={`rounded border px-1.5 py-0.5 text-[9px] ${chosen.has(clip.id) ? 'border-accent-blue bg-accent-blue/15 text-text-primary' : 'border-border text-text-muted hover:text-text-primary'}`}>
              {text(clip, 'humanoid').label}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}

function ImportFile({ file, onFile }: { file: File | null; onFile: (file: File | null) => void }) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div className="text-[10px] text-text-muted">
      <p className="uppercase tracking-wider">{t('rig.animateFile')}</p>
      {file ? (
        <p className="mt-1 flex items-center justify-between gap-2 rounded border border-border bg-bg-primary px-2 py-1 text-text-primary">
          <span className="truncate">{file.name}</span>
          <button type="button" onClick={() => onFile(null)} title={t('rig.animateRemoveFile')} className="text-text-muted hover:text-text-primary"><X size={11} /></button>
        </p>
      ) : (
        <label className="mt-1 flex cursor-pointer items-center gap-1.5 rounded border border-dashed border-border px-2 py-1.5 hover:border-border-light">
          <FileUp size={11} /> {t('rig.animatePickFile')}
          <input type="file" accept={IMPORT_TYPES} className="hidden" onChange={event => onFile(event.target.files?.[0] ?? null)} />
        </label>
      )}
      <p className="mt-0.5 text-[9px] leading-relaxed">{t('rig.animateFileHelp')}</p>
    </div>
  )
}

function AnimateResult({ result }: { result: HumanoidAnimateResult }) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div className="space-y-1 rounded border border-accent-green/25 bg-accent-green/5 p-2 text-[9px] text-text-muted">
      <p className="break-all text-accent-green">{t('rig.animateSaved', { file: result.file, count: result.clips.length })}</p>
      <p>{result.clips.map(clip => `${clip.index} · ${clip.name} (${clip.duration.toFixed(2)} s)`).join(', ')}</p>
      {result.warnings.length > 0 && <p className="text-amber-300/90">{t('rig.animateNotes')}: {result.warnings.join(' · ')}</p>}
    </div>
  )
}
