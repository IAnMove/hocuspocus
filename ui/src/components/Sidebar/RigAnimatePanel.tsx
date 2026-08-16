import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Bone, Box, Download, Loader2, PersonStanding, Play, RefreshCw, Square } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import {
  cancelRigJob,
  fetchOutputs,
  fetchRigCapabilities,
  fetchRigJob,
  getFileUrl,
  startRigJob,
  type RigCapabilities,
  type RigAnimation,
  type RigJob,
  type RigProfile,
  type RigProfileId,
} from '../../api/client'

type RigSource = { name: string; thumbnail_url?: string | null }

function RigPreviewCard({ asset, title, selected, onSelect, children }: { asset: string; title: string; selected: boolean; onSelect: () => void; children: ReactNode }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [hovered, setHovered] = useState(false)
  const play = () => {
    setHovered(true)
    const video = videoRef.current
    if (!video) return
    video.currentTime = 0
    void video.play().catch(() => {})
  }
  const stop = () => {
    setHovered(false)
    const video = videoRef.current
    if (!video) return
    video.pause()
    video.currentTime = 0
  }
  return (
    <button type="button" aria-pressed={selected} onClick={onSelect} onPointerEnter={play} onPointerLeave={stop} onFocus={play} onBlur={stop} className={`min-w-0 overflow-hidden rounded-lg border text-left transition-colors ${selected ? 'border-accent-blue bg-accent-blue/10 ring-1 ring-accent-blue/40' : 'border-border bg-bg-tertiary hover:border-accent-blue/70'}`}>
      <div className="relative aspect-video overflow-hidden bg-[#07111f]">
        <img src={`/rig-previews/${asset}.webp`} alt={`Preview of ${title}`} className="absolute inset-0 h-full w-full object-cover" loading="lazy" />
        <video ref={videoRef} src={`/rig-previews/${asset}.webm`} poster={`/rig-previews/${asset}.webp`} muted loop playsInline preload="metadata" aria-hidden="true" className={`pointer-events-none absolute inset-0 h-full w-full object-cover transition-opacity ${hovered ? 'opacity-100' : 'opacity-0'}`} />
        <span className="absolute bottom-1 right-1 rounded bg-black/65 px-1 py-0.5 text-[7px] uppercase tracking-wide text-white/80">hover</span>
      </div>
      {children}
    </button>
  )
}

function RigProfilePreview({ profile, selected, onSelect }: { profile: RigProfile; selected: boolean; onSelect: () => void }) {
  return (
    <RigPreviewCard asset={`profile-${profile.id}`} title={profile.label} selected={selected} onSelect={onSelect}>
      <div className="flex min-h-11 items-start justify-between gap-1 px-1.5 py-1.5">
        <span className="line-clamp-2 text-[9px] font-medium leading-tight text-text-secondary">{profile.label}</span>
        <span className="shrink-0 rounded bg-emerald-500/15 px-1 py-0.5 text-[7px] uppercase text-emerald-300">{profile.default_spine_joints} joints</span>
      </div>
    </RigPreviewCard>
  )
}

function RigAnimationPreview({ animation, selected, recommended, onSelect }: { animation: RigAnimation; selected: boolean; recommended: boolean; onSelect: () => void }) {
  return (
    <RigPreviewCard asset={`animation-${animation.id}`} title={animation.label} selected={selected} onSelect={onSelect}>
      <div className="space-y-1 px-1.5 py-1.5">
        <div className="flex items-start justify-between gap-1">
          <span className="line-clamp-2 text-[9px] font-medium leading-tight text-text-secondary">{animation.label}</span>
          {recommended && <span className="shrink-0 rounded bg-accent-green/10 px-1 py-0.5 text-[6px] uppercase text-accent-green">recommended</span>}
        </div>
        <div className="flex items-center justify-between gap-1">
          <span className="line-clamp-2 text-[8px] leading-tight text-text-muted">{animation.description}</span>
          {animation.category && <span className="shrink-0 rounded bg-accent-blue/10 px-1 py-0.5 text-[6px] uppercase text-accent-blue">{animation.category}</span>}
        </div>
      </div>
    </RigPreviewCard>
  )
}

/** Rig & Animate: adds a procedural skeleton + looping clips to a generated
 *  3D output. Complements the 3D tab (which creates static meshes) and the
 *  scene animator (which moves the camera, not the mesh). */
export function RigAnimatePanel() {
  const loadOutputs = useStore(state => state.loadOutputs)
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const [sources, setSources] = useState<RigSource[]>([])
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [capabilities, setCapabilities] = useState<RigCapabilities | null>(null)
  const [capabilityError, setCapabilityError] = useState<string | null>(null)
  const [source, setSource] = useState<string | null>(null)
  const [engineId, setEngineId] = useState('procedural')
  const [rigProfileId, setRigProfileId] = useState<RigProfileId>('prop')
  const [selectedClips, setSelectedClips] = useState<Set<string>>(new Set())
  const [spineJoints, setSpineJoints] = useState(5)
  const [axisMode, setAxisMode] = useState<'auto' | 'x' | 'y' | 'z'>('auto')
  const [weightFalloff, setWeightFalloff] = useState(2)
  const [job, setJob] = useState<RigJob | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exportStatus, setExportStatus] = useState<string | null>(null)

  const loadCapabilities = useCallback(() => {
    setCapabilityError(null)
    fetchRigCapabilities().then(caps => {
      setCapabilities(caps)
      const availableEngine = caps.engines.find(item => item.id === 'procedural' && item.installed) ?? caps.engines.find(item => item.installed) ?? caps.engines[0]
      if (availableEngine) setEngineId(availableEngine.id)
      const profiles = caps.rig_profiles ?? []
      const profileId = caps.default_rig_profile || profiles[0]?.id || 'prop'
      const profile = profiles.find(item => item.id === profileId)
      setRigProfileId(profileId)
      setSpineJoints(profile?.default_spine_joints ?? caps.default_spine_joints)
      setAxisMode(profile?.default_axis_mode ?? 'auto')
      setWeightFalloff(profile?.default_weight_falloff ?? 2)
      setSelectedClips(new Set(profile?.recommended_animations ?? caps.animations.map(animation => animation.id)))
    }).catch(err => {
      setCapabilityError(err instanceof Error ? err.message : 'Could not load rig capabilities')
    })
  }, [])

  useEffect(() => {
    loadCapabilities()
  }, [loadCapabilities])

  // The gallery store paginates (newest 100), which can hide older GLB
  // outputs entirely — fetch the complete .glb list straight from the
  // backend's search filter instead (it bypasses pagination).
  const loadSources = useCallback(async () => {
    setSourcesLoading(true)
    try {
      const { outputs: files } = await fetchOutputs(0, 0, { search: '.glb', workspace: activeWorkspace })
      setSources(files
        .filter(file => file.type === 'model3d' && /\.glb$/i.test(file.name) && !file.name.includes('_rigged_'))
        .map(file => ({ name: file.name, thumbnail_url: file.thumbnail_url })))
    } catch {
      setSources([])
    } finally {
      setSourcesLoading(false)
    }
  }, [activeWorkspace])

  useEffect(() => {
    void loadSources()
  }, [loadSources])

  const installedEngines = capabilities?.engines.filter(item => item.installed) ?? []
  const selectedEngine = capabilities?.engines.find(item => item.id === engineId)
  const selectedProfile = capabilities?.rig_profiles?.find(item => item.id === rigProfileId)
  const profileAnimations = capabilities?.animations.filter(animation => !selectedProfile || selectedProfile.allowed_animations.includes(animation.id)) ?? []
  const recommendedAnimationIds = selectedProfile?.recommended_animations ?? profileAnimations.map(animation => animation.id)
  const isRunning = job?.status === 'queued' || job?.status === 'running'
  const activeJobId = isRunning ? job?.job_id ?? null : null
  const canRun = !!selectedEngine?.installed && !!source && selectedClips.size > 0 && !isRunning

  useEffect(() => {
    if (!activeJobId) return
    let disposed = false
    let failures = 0
    const poll = async () => {
      try {
        const next = await fetchRigJob(activeJobId)
        failures = 0
        if (!disposed) setJob(next)
      } catch (err) {
        if (disposed) return
        failures += 1
        const message = err instanceof Error ? err.message : 'Could not read rig job status'
        setError(message)
        const lost = (err as Error & { status?: number }).status === 404
        if (lost || failures >= 4) {
          setJob(current => current && { ...current, status: 'failed', error: lost ? 'The rig job was lost — the backend probably restarted.' : message })
        }
      }
    }
    const timer = window.setInterval(poll, 1500)
    void poll()
    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [activeJobId])

  useEffect(() => {
    if (job?.status === 'completed') {
      void loadOutputs()
      void loadSources()
      setMediaFilter('model3d')
    }
    if (job?.status === 'failed') setError(job.error || job.message)
  }, [job?.status, job?.error, job?.message, loadOutputs, loadSources, setMediaFilter])

  const toggleClip = (id: string) => {
    setSelectedClips(current => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const chooseRigProfile = (id: RigProfileId) => {
    const profile = capabilities?.rig_profiles?.find(item => item.id === id)
    if (!profile) return
    setRigProfileId(id)
    setSpineJoints(profile.default_spine_joints)
    setAxisMode(profile.default_axis_mode)
    setWeightFalloff(profile.default_weight_falloff)
    setSelectedClips(new Set(profile.recommended_animations))
    setError(null)
  }

  const run = async () => {
    if (!source) return
    setError(null)
    setExportError(null)
    setExportStatus(null)
    try {
      setJob(await startRigJob({
        source,
        engine: engineId,
        rig_profile: rigProfileId,
        animations: Array.from(selectedClips),
        spine_joints: spineJoints,
        axis_mode: axisMode,
        weight_falloff: weightFalloff,
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rig job failed to start')
    }
  }

  const cancel = async () => {
    if (!job) return
    try {
      setJob(await cancelRigJob(job.job_id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel rig job')
    }
  }

  const exportAnimatedGlb = async () => {
    if (!job?.filename) {
      setExportError('The completed rig job did not return an output filename.')
      return
    }

    const filename = job.filename.split(/[\\/]/).pop()
    if (!filename || !/\.glb$/i.test(filename)) {
      setExportError('The completed rig job did not return a valid GLB filename.')
      return
    }

    const url = job.url || getFileUrl(filename)
    setExporting(true)
    setExportError(null)
    setExportStatus(null)
    try {
      // Probe one byte before handing the URL to the browser. This surfaces a
      // missing/moved gallery asset without buffering a potentially large GLB.
      const response = await fetch(url, {
        cache: 'no-store',
        headers: { Range: 'bytes=0-0' },
      })
      if (!response.ok) {
        const detail = await response.text().catch(() => '')
        throw new Error(detail || `The animated GLB could not be opened (${response.status}).`)
      }
      await response.body?.cancel()

      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      setExportStatus(`Download started: ${filename}`)
    } catch (err) {
      setExportError(err instanceof Error ? err.message : 'Could not export the animated GLB.')
    } finally {
      setExporting(false)
    }
  }

  if (capabilityError) return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 space-y-2">
      <p className="text-xs text-red-300">{capabilityError}</p>
      <p className="text-[10px] text-text-muted">Loreframe Lab&apos;s backend did not answer — it may be stopped or restarting. The procedural engine needs no extra install; this is a connection issue, not a missing installation.</p>
      <button onClick={loadCapabilities} className="rounded border border-border bg-bg-tertiary px-2.5 py-1.5 text-[10px] text-text-secondary hover:text-text-primary flex items-center gap-1"><RefreshCw size={11} /> Retry</button>
    </div>
  )

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><PersonStanding size={15} className="text-accent-blue" /> Rig &amp; Animate</div>
        <p className="text-[10px] text-text-muted mt-1">Give a generated 3D object a simple skeleton and looping animations. The result is saved as a new GLB in the gallery.</p>
      </div>

      {!capabilities ? (
        <div className="flex items-center justify-center py-8 text-xs text-text-muted"><Loader2 size={15} className="animate-spin mr-2" /> Loading...</div>
      ) : installedEngines.length === 0 ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
          <p className="text-xs font-medium text-amber-300">No rig engine is installed</p>
          <div className="mt-1 space-y-1">{capabilities.engines.map(item => item.install_hint && <p key={item.id} className="text-[10px] leading-relaxed text-text-muted"><span className="text-text-secondary">{item.label}:</span> {item.install_hint}</p>)}</div>
        </div>
      ) : (
        <>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[10px] text-text-muted uppercase tracking-wider">3D object</label>
              <button onClick={() => void loadSources()} className="text-text-muted hover:text-text-primary transition-colors" title="Refresh 3D outputs">
                <RefreshCw size={11} />
              </button>
            </div>
            {sourcesLoading ? (
              <div className="flex items-center gap-2 text-[10px] text-text-muted p-3"><Loader2 size={12} className="animate-spin" /> Loading 3D outputs...</div>
            ) : sources.length === 0 ? (
              <p className="text-[10px] text-text-muted rounded-lg border border-dashed border-border p-3">No GLB outputs yet. Generate an object in the 3D tab first.</p>
            ) : (
              <div className="grid grid-cols-3 md:grid-cols-5 gap-2 max-h-72 overflow-y-auto pr-0.5">
                {sources.map(file => (
                  <button
                    key={file.name}
                    onClick={() => setSource(file.name)}
                    className={`relative aspect-square rounded-lg overflow-hidden border transition-colors ${source === file.name ? 'border-accent-blue ring-1 ring-accent-blue' : 'border-border hover:border-border-light'}`}
                    title={file.name}
                  >
                    {file.thumbnail_url ? (
                      <img src={file.thumbnail_url} alt={file.name} className="w-full h-full object-cover" loading="lazy" />
                    ) : (
                      <div className="w-full h-full bg-bg-tertiary flex items-center justify-center"><Box size={16} className="text-text-muted" /></div>
                    )}
                    <div className="absolute inset-x-0 bottom-0 bg-black/60 px-1 py-0.5 text-[8px] text-white truncate">{file.name}</div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2"><label className="text-[10px] text-text-muted uppercase tracking-wider">Rig profile / skeleton</label><span className="text-[8px] text-text-muted">Hover or focus to animate</span></div>
            {capabilities.rig_profiles?.length ? <div className="grid grid-cols-2 gap-1.5">{capabilities.rig_profiles.map(profile => <RigProfilePreview key={profile.id} profile={profile} selected={rigProfileId === profile.id} onSelect={() => chooseRigProfile(profile.id)} />)}</div> : <select value={rigProfileId} disabled className="w-full rounded-lg border border-border bg-bg-tertiary px-2.5 py-2 text-xs text-text-primary opacity-60"><option value="prop">General / legacy backend</option></select>}
            {selectedProfile && (
              <div className="mt-1.5 rounded-lg border border-border bg-bg-tertiary p-2.5">
                <p className="text-[9px] leading-relaxed text-text-muted">{selectedProfile.description}</p>
                <p className="mt-1 text-[9px] text-text-muted/80">{engineId === 'procedural' ? 'Applies a tailored chain fit and shows only compatible motion clips. You can fine-tune the fit below.' : 'Filters the motion library for this body type. UniRig still predicts its own skeleton and skin weights.'}</p>
              </div>
            )}
          </div>

          <div>
            <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5 block">Engine</label>
            <div className="space-y-1">
              {capabilities.engines.map(item => (
                <label key={item.id} className={`flex items-start gap-2 rounded-lg border px-2.5 py-1.5 ${item.installed ? 'border-border bg-bg-tertiary cursor-pointer hover:border-border-light' : 'border-border/60 bg-bg-tertiary/50 cursor-not-allowed opacity-70'}`}>
                  <input type="radio" name="rig-engine" checked={engineId === item.id} disabled={!item.installed} onChange={() => setEngineId(item.id)} className="mt-0.5" />
                  <span>
                    <span className="block text-[11px] text-text-primary">{item.label}</span>
                    <span className="block text-[9px] text-text-muted">{item.description}</span>
                    {!item.installed && item.install_hint && <span className="block text-[9px] text-amber-400 mt-0.5">{item.install_hint}</span>}
                  </span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label className="text-[10px] text-text-muted uppercase tracking-wider">{selectedProfile?.label ?? 'Rig'} animations</label>
              <div className="flex gap-1">
                <button type="button" onClick={() => setSelectedClips(new Set(recommendedAnimationIds))} className="rounded border border-border px-1.5 py-0.5 text-[8px] text-text-muted hover:text-text-primary">Recommended</button>
                <button type="button" onClick={() => setSelectedClips(new Set(profileAnimations.map(animation => animation.id)))} className="rounded border border-border px-1.5 py-0.5 text-[8px] text-text-muted hover:text-text-primary">All</button>
              </div>
            </div>
            <div className="grid max-h-[620px] grid-cols-2 gap-1.5 overflow-y-auto pr-0.5">{profileAnimations.map(animation => <RigAnimationPreview key={animation.id} animation={animation} selected={selectedClips.has(animation.id)} recommended={Boolean(selectedProfile?.recommended_animations.includes(animation.id))} onSelect={() => toggleClip(animation.id)} />)}</div>
            <p className="mt-1.5 text-[8px] leading-relaxed text-text-muted">These previews visualize Loreframe Lab&apos;s generic procedural chain and its intended root motion, squash, turn and sway. They do not claim semantic limb animation.</p>
          </div>

          {engineId === 'procedural' && (
            <div className="rounded-lg border border-border bg-bg-tertiary p-2.5 space-y-2.5">
              <div>
                <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-text-secondary"><Bone size={11} /> Manual rig fit</div>
                <p className="mt-0.5 text-[9px] text-text-muted">Guide the procedural bone chain before generating. This adjusts the rig fit without pretending to be a full weight-painting editor.</p>
              </div>
              <label className="block text-[10px] text-text-muted">Skeleton direction
                <select value={axisMode} onChange={event => setAxisMode(event.target.value as typeof axisMode)} className="mt-1 w-full rounded border border-border bg-bg-primary px-2 py-1 text-xs">
                  <option value="auto">Auto — detect object direction</option>
                  <option value="y">Vertical — Y axis</option>
                  <option value="x">Horizontal — X axis</option>
                  <option value="z">Depth — Z axis</option>
                </select>
              </label>
              <label className="block text-[10px] text-text-muted uppercase tracking-wider">
                <span className="flex items-center justify-between"><span>Spine joints</span><span className="text-text-primary">{spineJoints}</span></span>
                <input type="range" min={2} max={9} value={spineJoints} onChange={event => setSpineJoints(Number(event.target.value))} className="mt-1.5 w-full" />
              </label>
              <label className="block text-[10px] text-text-muted uppercase tracking-wider">
                <span className="flex items-center justify-between"><span>Skin stiffness</span><span className="text-text-primary">{weightFalloff.toFixed(1)}</span></span>
                <input type="range" min={1} max={6} step={.25} value={weightFalloff} onChange={event => setWeightFalloff(Number(event.target.value))} className="mt-1.5 w-full" />
                <span className="mt-0.5 block normal-case tracking-normal text-[9px] text-text-muted/80">Low bends smoothly; high keeps sections more rigid. Useful for characters versus hard-surface props.</span>
              </label>
            </div>
          )}

          {job && (
            <div className={`rounded-lg border p-3 ${job.status === 'failed' ? 'border-red-500/30 bg-red-500/10' : 'border-border bg-bg-tertiary'}`}>
              <div className="flex items-center justify-between text-[10px]"><span className="text-text-secondary">{job.message}</span><span className="text-text-muted">{Math.round(job.progress * 100)}%</span></div>
              <div className="h-1.5 bg-bg-primary rounded-full overflow-hidden mt-2"><div className="h-full bg-accent-green transition-all" style={{ width: `${Math.max(2, job.progress * 100)}%` }} /></div>
              {job.error && <p className="text-[10px] text-red-300 mt-2 whitespace-pre-wrap max-h-24 overflow-y-auto">{job.error}</p>}
              {job.status === 'completed' && (
                <div className="mt-3 border-t border-border pt-3 space-y-1.5">
                  <button
                    onClick={() => void exportAnimatedGlb()}
                    disabled={exporting}
                    className="w-full rounded-lg border border-accent-green/40 bg-accent-green/10 px-3 py-2 text-[11px] font-medium text-accent-green hover:bg-accent-green/20 disabled:cursor-wait disabled:opacity-60 flex items-center justify-center gap-1.5 transition-colors"
                  >
                    {exporting ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                    {exporting ? 'Preparing GLB...' : 'Export animated GLB'}
                  </button>
                  <p className="text-[9px] text-text-muted text-center">Downloads the rigged model with its baked clips. It also remains available in Loreframe Lab&apos;s 3D gallery.</p>
                  {exportStatus && <p className="text-[9px] text-accent-green text-center break-all">{exportStatus}</p>}
                  {exportError && <p className="text-[9px] text-red-300 text-center whitespace-pre-wrap">{exportError}</p>}
                </div>
              )}
            </div>
          )}
          {error && !job?.error && <p className="text-[10px] text-red-400 whitespace-pre-wrap">{error}</p>}

          {isRunning ? (
            <button onClick={() => void cancel()} className="w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25 text-xs font-medium"><Square size={13} /> Cancel rigging</button>
          ) : (
            <button disabled={!canRun} onClick={() => void run()} className={`w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition-all ${canRun ? 'bg-cta hover:brightness-110 shadow-accent-glow text-white' : 'bg-bg-tertiary border border-border text-text-muted cursor-not-allowed'}`}><Play size={13} fill={canRun ? 'currentColor' : 'none'} /> Rig &amp; animate</button>
          )}
          <p className="text-[9px] text-text-muted text-center">{engineId === 'unirig' ? 'AI rigging uses the GPU; the first run downloads the UniRig weights (~2GB).' : 'Runs on CPU in seconds. The animated GLB plays its clips in the gallery viewer.'}</p>
        </>
      )}
    </div>
  )
}
