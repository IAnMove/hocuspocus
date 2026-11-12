import { useCallback, useEffect, useState } from 'react'
import {
  cancelRealCharacter, fetchRealPresets, getRealCharacter, listRealCharacters, makeRealCharacter, realCharacterJob,
  REAL_ACTIVE, REAL_STEPS, type RealCharacterRow, type RealGender, type RealJob, type RealNote, type RealPreset, type RealPresets,
} from '../../api/realCharacter'
import { controlReason } from '../../i18n/controlLabel'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'

const FIELD = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1 text-xs text-text-primary'
const LABEL = 'text-[10px] text-text-muted'
const POLL_MS = 3000

const active = (job: RealJob | null) => !!job && REAL_ACTIVE.includes(job.status)
const fits = (item: RealPreset, gender: RealGender) => item.gender === 'any' || item.gender === gender

/** Follows a running job until it stops, then calls `onDone` once with the last state. */
function useRealJob(workspace: string, onDone: (job: RealJob) => void) {
  const [job, setJob] = useState<RealJob | null>(null)
  useEffect(() => {
    if (!job || !active(job)) return
    const timer = setTimeout(() => {
      void realCharacterJob(workspace, job.jobId).then(next => {
        setJob(next)
        if (!active(next)) onDone(next)
      }).catch(() => setJob({ ...job }))
    }, POLL_MS)
    return () => clearTimeout(timer)
  }, [job, workspace, onDone])
  return [job, setJob] as const
}

/** A realistic PS2-era person from two prompts: the same `model3d.real.make` job the Wizard and MCP start. A saved one reopens here to
 * change its clothes or its face; the server keeps whatever did not change. */
export function RealCharacterPanel() {
  const { t, i18n } = useUiTranslation('studio')
  const workspace = useStore(state => state.activeWorkspace)
  const setMediaFilter = useStore(state => state.setMediaFilter)
  const maybeRefreshGallery = useStore(state => state.maybeRefreshGallery)
  const [name, setName] = useState(() => t('makers.real.defaultName'))
  const [gender, setGender] = useState<RealGender>('man')
  const [outfit, setOutfit] = useState('')
  const [face, setFace] = useState('')
  const [seed, setSeed] = useState('')
  const [presets, setPresets] = useState<RealPresets | null>(null)
  const [saved, setSaved] = useState<RealCharacterRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [notes, setNotes] = useState<RealNote[]>([])
  // A job started elsewhere (the Wizard, an agent, before a reload) is picked up here while it runs.
  const [adopt, setAdopt] = useState<RealJob | null>(null)

  const reload = useCallback(() => {
    if (!workspace) return
    void listRealCharacters(workspace).then(listed => {
      setSaved(listed.characters)
      setAdopt(listed.jobs.find(active) ?? null)
    }).catch(() => setSaved([]))
  }, [workspace])
  const finished = useCallback((job: RealJob) => {
    reload()
    if (job.status !== 'completed') return
    setMediaFilter('model3d')
    void maybeRefreshGallery({ message: t('makers.real.ready'), force: true })
  }, [reload, setMediaFilter, maybeRefreshGallery, t])
  const [job, setJob] = useRealJob(workspace, finished)
  const [trackedWorkspace, setTrackedWorkspace] = useState(workspace)
  if (trackedWorkspace !== workspace) {
    setTrackedWorkspace(workspace)
    setJob(null)
    setNotes([])
  }

  useEffect(() => { void fetchRealPresets().then(setPresets).catch(() => setPresets(null)) }, [])
  useEffect(() => { reload() }, [reload])
  useEffect(() => { if (adopt) setJob(current => current && active(current) ? current : adopt) }, [adopt, setJob])

  const run = async (work: () => Promise<void>) => {
    setError(null)
    try { await work() } catch (err) { setError(err instanceof Error ? err.message : t('makers.real.failed')) }
  }
  const create = () => run(async () => {
    const chosen = seed.trim() ? Number(seed) : undefined
    const started = await makeRealCharacter({ workspace, name: name.trim() || t('makers.real.defaultName'), gender, outfitPrompt: outfit, facePrompt: face,
      ...(chosen !== undefined && Number.isInteger(chosen) ? { seed: chosen } : {}) })
    setNotes([])
    setJob(started)
    if (!active(started)) finished(started)
  })
  const open = (row: RealCharacterRow) => run(async () => {
    const recipe = await getRealCharacter(workspace, row.name)
    setName(recipe.name)
    setGender(recipe.input.gender ?? 'man')
    setOutfit(recipe.input.outfit_prompt ?? '')
    setFace(recipe.input.face_prompt ?? '')
    setSeed(recipe.input.seed !== undefined ? String(recipe.input.seed) : '')
    setNotes(recipe.warnings ?? [])
    setJob(null)
  })
  const stop = () => run(async () => { if (job) setJob(await cancelRealCharacter(workspace, job.jobId)) })

  const language = i18n.language?.startsWith('es') ? 'es' : 'en'
  const pick = (label: string, items: RealPreset[], set: (prompt: string) => void) => (
    <label className={LABEL}>{label}
      <select className={FIELD} value="" onChange={event => { const item = items.find(entry => entry.id === event.target.value); if (item) set(item.prompt) }}>
        <option value="">{t('makers.real.pick')}</option>
        {items.filter(item => fits(item, gender)).map(item => <option key={item.id} value={item.id}>{item.label[language]}</option>)}
      </select>
    </label>
  )
  const blocked = active(job) || !workspace
  return (
    <section className="rounded-lg border border-border p-3 flex flex-col gap-2" data-testid="real-character-panel">
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">{t('makers.real.title')}</h3>
      <p className="text-[10px] text-text-secondary">{t('makers.real.hint')}</p>
      <label className={LABEL}>{t('makers.name')}
        <input className={FIELD} value={name} maxLength={64} onChange={event => setName(event.target.value)} />
      </label>
      <label className={LABEL}>{t('makers.gender')}
        <select className={FIELD} value={gender} onChange={event => setGender(event.target.value as RealGender)}>
          {(['man', 'woman'] as const).map(item => <option key={item} value={item}>{t(`makers.real.genders.${item}`)}</option>)}
        </select>
      </label>
      {presets && pick(t('makers.real.outfitPick'), presets.outfits, setOutfit)}
      <label className={LABEL}>{t('makers.real.outfit')}
        <textarea className={FIELD} rows={3} maxLength={1200} value={outfit} onChange={event => setOutfit(event.target.value)} />
      </label>
      {presets && pick(t('makers.real.facePick'), presets.faces, setFace)}
      <label className={LABEL}>{t('makers.real.face')}
        <textarea className={FIELD} rows={3} maxLength={1200} value={face} onChange={event => setFace(event.target.value)} />
      </label>
      <label className={LABEL}>{t('makers.real.seed')}
        <input className={FIELD} inputMode="numeric" value={seed} placeholder={t('makers.real.seedRandom')} onChange={event => setSeed(event.target.value.replace(/[^0-9]/g, ''))} />
      </label>
      <button type="button" disabled={blocked} title={controlReason(blocked, 'disabled.actionInProgress')} onClick={() => void create()}
        className={`w-full px-4 py-2 rounded-lg text-xs font-medium ${blocked ? 'bg-bg-tertiary text-text-muted' : 'bg-cta text-white'}`}>
        {active(job) ? '…' : t('makers.real.make')}
      </button>
      {active(job) && <button type="button" onClick={() => void stop()} className="text-[10px] underline text-text-secondary self-start">{t('makers.real.cancel')}</button>}
      {error && <p className="text-[10px] text-red-300">{error}</p>}
      {job && <RealJobView job={job} />}
      {!job && notes.length > 0 && <NoteList notes={notes} />}
      <h4 className="text-[10px] font-semibold uppercase text-text-muted">{t('makers.real.saved')}</h4>
      {saved.length === 0 && <p className="text-[10px] text-text-muted">{t('makers.real.none')}</p>}
      <ul className="flex flex-col gap-1">
        {saved.map(row => (
          <li key={row.slug} className="flex items-center gap-2 text-[10px] text-text-secondary" data-testid={`real-saved-${row.slug}`}>
            {row.face_url && <img src={row.face_url} alt={t('makers.real.facePicture')} className="w-8 h-8 rounded object-cover" />}
            <span className="flex-1 truncate">{row.name}{row.missing ? ` · ${t('makers.real.missing')}` : ''}</span>
            <button type="button" disabled={blocked} title={controlReason(blocked, 'disabled.actionInProgress')} onClick={() => void open(row)} className="underline">{t('makers.real.open')}</button>
          </li>
        ))}
      </ul>
    </section>
  )
}

/** The job's steps, then the made character with its warnings. */
function RealJobView({ job }: { job: RealJob }) {
  const { t } = useUiTranslation('studio')
  const result = job.status === 'completed' ? job.result : undefined
  return (
    <>
      <ol className="text-[10px] text-text-secondary" aria-label={t('makers.real.progress')}>
        <li>{t(`makers.real.job.${job.status}`, { defaultValue: job.status })}</li>
        {REAL_STEPS.map(id => {
          const step = job.steps.find(item => item.id === id)
          return <li key={id} data-testid={`real-step-${id}`}>{t(`makers.real.steps.${id}`)}: {t(`makers.real.status.${step?.status ?? 'waiting'}`, { defaultValue: step?.status ?? '' })}</li>
        })}
        {job.error && <li className="text-red-300">{job.error}</li>}
      </ol>
      {result && (
        <div className="flex flex-col gap-1" data-testid="real-result">
          {result.preview && <img src={result.preview} alt={t('makers.real.facePicture')} className="w-24 rounded border border-border" />}
          <p className="text-[10px] text-text-secondary">{t('makers.real.made', { file: result.rigged_file, kit: result.kit_id ?? '—' })}</p>
          {result.warnings.length > 0 && <NoteList notes={result.warnings} />}
        </div>
      )}
    </>
  )
}

/** What went wrong quietly in a make (the server's notes: a code and a sentence). */
function NoteList({ notes }: { notes: RealNote[] }) {
  const { t } = useUiTranslation('studio')
  return (
    <ul className="text-[10px] text-amber-300" aria-label={t('makers.real.warnings')}>
      {notes.map((item, index) => <li key={`${item.code}-${index}`}>{item.code}: {item.message}</li>)}
    </ul>
  )
}
