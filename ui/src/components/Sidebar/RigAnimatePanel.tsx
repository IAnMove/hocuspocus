import { useCallback, useEffect, useState } from 'react'
import { Bone, Box, Loader2, PersonStanding, Play, RefreshCw, Square } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import {
  cancelRigJob,
  fetchOutputs,
  fetchRigCapabilities,
  fetchRigJob,
  startRigJob,
  type RigCapabilities,
  type RigJob,
} from '../../api/client'

type RigSource = { name: string; thumbnail_url?: string | null }

/** Rig & Animate: adds a procedural skeleton + looping clips to a generated
 *  3D output. Complements the 3D tab (which creates static meshes) and the
 *  scene animator (which moves the camera, not the mesh). */
export function RigAnimatePanel() {
  const loadOutputs = useStore(state => state.loadOutputs)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const [sources, setSources] = useState<RigSource[]>([])
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [capabilities, setCapabilities] = useState<RigCapabilities | null>(null)
  const [capabilityError, setCapabilityError] = useState<string | null>(null)
  const [source, setSource] = useState<string | null>(null)
  const [selectedClips, setSelectedClips] = useState<Set<string>>(new Set())
  const [spineJoints, setSpineJoints] = useState(5)
  const [job, setJob] = useState<RigJob | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchRigCapabilities().then(caps => {
      setCapabilities(caps)
      setSpineJoints(caps.default_spine_joints)
      setSelectedClips(new Set(caps.animations.map(animation => animation.id)))
    }).catch(err => {
      setCapabilityError(err instanceof Error ? err.message : 'Could not load rig capabilities')
    })
  }, [])

  // The gallery store paginates (newest 100), which can hide older GLB
  // outputs entirely — fetch the complete .glb list straight from the
  // backend's search filter instead (it bypasses pagination).
  const loadSources = useCallback(async () => {
    setSourcesLoading(true)
    try {
      const { outputs: files } = await fetchOutputs(0, 0, { search: '.glb' })
      setSources(files
        .filter(file => file.type === 'model3d' && /\.glb$/i.test(file.name) && !file.name.includes('_rigged_'))
        .map(file => ({ name: file.name, thumbnail_url: file.thumbnail_url })))
    } catch {
      setSources([])
    } finally {
      setSourcesLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadSources()
  }, [loadSources])

  const engine = capabilities?.engines.find(item => item.id === 'procedural')
  const installed = !!engine?.installed
  const isRunning = job?.status === 'queued' || job?.status === 'running'
  const canRun = installed && !!source && selectedClips.size > 0 && !isRunning

  useEffect(() => {
    if (!job || (job.status !== 'queued' && job.status !== 'running')) return
    let disposed = false
    let failures = 0
    const poll = async () => {
      try {
        const next = await fetchRigJob(job.job_id)
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
  }, [job?.job_id, job?.status])

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

  const run = async () => {
    if (!source) return
    setError(null)
    try {
      setJob(await startRigJob({
        source,
        engine: 'procedural',
        animations: Array.from(selectedClips),
        spine_joints: spineJoints,
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

  if (capabilityError) return <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-300">{capabilityError}</div>

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary"><PersonStanding size={15} className="text-accent-blue" /> Rig &amp; Animate</div>
        <p className="text-[10px] text-text-muted mt-1">Give a generated 3D object a simple skeleton and looping animations. The result is saved as a new GLB in the gallery.</p>
      </div>

      {!capabilities ? (
        <div className="flex items-center justify-center py-8 text-xs text-text-muted"><Loader2 size={15} className="animate-spin mr-2" /> Loading...</div>
      ) : !installed ? (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
          <p className="text-xs font-medium text-amber-300">Rig runtime is not installed</p>
          <p className="text-[10px] text-text-muted mt-1 leading-relaxed">{engine?.install_hint}</p>
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
            <label className="text-[10px] text-text-muted uppercase tracking-wider mb-1.5 block">Animations</label>
            <div className="space-y-1">
              {capabilities.animations.map(animation => (
                <label key={animation.id} className="flex items-start gap-2 rounded-lg border border-border bg-bg-tertiary px-2.5 py-1.5 cursor-pointer hover:border-border-light">
                  <input type="checkbox" checked={selectedClips.has(animation.id)} onChange={() => toggleClip(animation.id)} className="mt-0.5" />
                  <span>
                    <span className="block text-[11px] text-text-primary">{animation.label}</span>
                    <span className="block text-[9px] text-text-muted">{animation.description}</span>
                  </span>
                </label>
              ))}
            </div>
          </div>

          <label className="text-[10px] text-text-muted uppercase tracking-wider block">
            <span className="flex items-center gap-1.5"><Bone size={11} /> Spine joints: <span className="text-text-primary">{spineJoints}</span></span>
            <input type="range" min={2} max={9} value={spineJoints} onChange={event => setSpineJoints(Number(event.target.value))} className="mt-1.5 w-full" />
          </label>

          {job && (
            <div className={`rounded-lg border p-3 ${job.status === 'failed' ? 'border-red-500/30 bg-red-500/10' : 'border-border bg-bg-tertiary'}`}>
              <div className="flex items-center justify-between text-[10px]"><span className="text-text-secondary">{job.message}</span><span className="text-text-muted">{Math.round(job.progress * 100)}%</span></div>
              <div className="h-1.5 bg-bg-primary rounded-full overflow-hidden mt-2"><div className="h-full bg-accent-green transition-all" style={{ width: `${Math.max(2, job.progress * 100)}%` }} /></div>
              {job.error && <p className="text-[10px] text-red-300 mt-2 whitespace-pre-wrap max-h-24 overflow-y-auto">{job.error}</p>}
            </div>
          )}
          {error && !job?.error && <p className="text-[10px] text-red-400 whitespace-pre-wrap">{error}</p>}

          {isRunning ? (
            <button onClick={() => void cancel()} className="w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 bg-red-500/15 border border-red-500/30 text-red-300 hover:bg-red-500/25 text-xs font-medium"><Square size={13} /> Cancel rigging</button>
          ) : (
            <button disabled={!canRun} onClick={() => void run()} className={`w-full px-4 py-2.5 rounded-lg flex items-center justify-center gap-1.5 text-xs font-medium transition-all ${canRun ? 'bg-cta hover:brightness-110 shadow-accent-glow text-white' : 'bg-bg-tertiary border border-border text-text-muted cursor-not-allowed'}`}><Play size={13} fill={canRun ? 'currentColor' : 'none'} /> Rig &amp; animate</button>
          )}
          <p className="text-[9px] text-text-muted text-center">Runs on CPU in seconds. The animated GLB plays its clips in the gallery viewer.</p>
        </>
      )}
    </div>
  )
}
