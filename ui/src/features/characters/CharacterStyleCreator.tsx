import { useEffect, useRef, useState } from 'react'
import { Loader2, Mic, Plus, WandSparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { cancelJob } from '../../api/client'
import { fetchCharacterKitLibrary, rigFlatCharacter, saveCharacterKit, type FlatRigResult } from '../../api/characters'
import { createCharacterKit, type CharacterKit, type CharacterKitAsset } from '../../lib/characterKit'
import type { CharacterStyle } from '../../lib/characterStyles'
import { flaggedRigPoses, isWarpRigged } from '../../lib/flatRigMouth'
import { randomUuid } from '../../lib/uuid'
import { generateKeyedCandidates, type KeyedCandidate } from './characterCandidates'
import { CharacterVoiceDesigner } from './CharacterVoiceDesigner'
import type { CustomCharacterVoice } from '../../lib/characterVoice'
import type { SpokenLanguage } from '../../lib/speechLanguage'

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'
const checker = 'bg-[conic-gradient(#e5e7eb_25%,#f9fafb_0_50%,#e5e7eb_0_75%,#f9fafb_0)] bg-[length:16px_16px]'

type Step = 'options' | 'rig' | 'pose' | 'addPose'

const poseId = (description: string) => description.toLowerCase().normalize('NFKD').replace(/[^a-z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '').slice(0, 40) || `pose-${randomUuid().slice(0, 6)}`

function keyedAsset(id: string, name: string, source: string, workspace: string, prompt: string, model: string): CharacterKitAsset {
  return { id, name, source, kind: 'image', alphaStatus: 'transparent', reviewState: 'approved', workspace, prompt, model }
}

function Candidates({ candidates, picked, onPick, disabled }: {
  candidates: KeyedCandidate[]; picked?: string; onPick: (candidate: KeyedCandidate) => void; disabled: boolean
}) {
  const { t } = useUiTranslation('characters')
  return <div className="grid grid-cols-3 gap-2" data-testid="character-candidates">
    {candidates.map((candidate, index) => <button key={candidate.id} type="button" disabled={disabled || candidate.status !== 'ready'}
      onClick={() => onPick(candidate)} aria-pressed={picked === candidate.id} aria-label={t('styleCreator.option', { number: index + 1 })}
      className={`relative aspect-[3/4] overflow-hidden rounded-lg border-2 ${picked === candidate.id ? 'border-cyan-300' : 'border-border'} ${checker}`}>
      {candidate.keyed || candidate.raw
        ? <img src={candidate.keyed || candidate.raw} alt="" className="h-full w-full object-contain" />
        : null}
      {candidate.status === 'generating' || candidate.status === 'keying'
        ? <span className="absolute inset-0 flex items-center justify-center bg-black/30 text-xs text-white">
          <Loader2 size={16} className="mr-1 animate-spin" />{t(candidate.status === 'keying' ? 'styleCreator.keying' : 'styleCreator.generating')}</span>
        : null}
      {candidate.status === 'failed' && <span role="alert" className="absolute inset-x-1 bottom-1 rounded bg-red-950/80 p-1 text-[11px] text-red-100">
        {t('styleCreator.failed', { error: candidate.error })}</span>}
      {candidate.status === 'ready' && candidate.haze !== undefined && <span className="absolute inset-x-1 bottom-1 rounded bg-amber-950/80 p-1 text-[11px] text-amber-100">
        {t('styleCreator.haze', { percent: Math.round(candidate.haze * 100) })}</span>}
    </button>)}
  </div>
}

type RigShown = Pick<FlatRigResult, 'review' | 'unwipedPoses' | 'warnings'>

/** The rig's review sheet and what to look at: warp mouths (their mouth line) or painted mouths not found. */
function RigReview({ workspace, kit, rig, blocked, onUseVoice }: {
  workspace: string; kit: CharacterKit; rig: RigShown; blocked: boolean
  onUseVoice: (language: SpokenLanguage, voice: CustomCharacterVoice) => Promise<void>
}) {
  const { t } = useUiTranslation('characters')
  const [designing, setDesigning] = useState(false)
  const warp = isWarpRigged(kit), flagged = flaggedRigPoses(rig.warnings)
  const note = 'text-xs text-amber-200'
  return <div className="space-y-2" data-testid="character-rig-review">
    <img src={rig.review} alt={t('styleCreator.reviewAlt')} className="max-h-72 rounded-lg border border-border bg-white object-contain" />
    {warp && <p className="text-xs text-text-muted">{t('styleCreator.warpReview')}</p>}
    {!warp && rig.unwipedPoses.length > 0 && <p className={note}>{t('styleCreator.unwiped', { poses: rig.unwipedPoses.join(', ') })}</p>}
    {flagged.mouthLine.length > 0 && <p className={note} data-testid="character-rig-mouth-line">{t('styleCreator.mouthLine', { poses: flagged.mouthLine.join(', '), name: kit.name })}</p>}
    {flagged.other.length > 0 && <p className={note}>{t('styleCreator.checkPoses', { poses: flagged.other.join(', '), name: kit.name })}</p>}
    <button type="button" disabled={blocked} aria-expanded={designing} onClick={() => setDesigning(open => !open)} className={`${control} inline-flex items-center gap-2`}><Mic size={15} />{t('styleCreator.designVoice')}</button>
    {designing && <CharacterVoiceDesigner workspace={workspace} characterName={kit.name} disabled={blocked} onUse={onUseVoice} />}
  </div>
}

function NewPose({ pose, onPose, candidates, picked, onPick, blocked, onCreate, onAdd }: {
  pose: string; onPose: (value: string) => void; candidates: KeyedCandidate[]; picked?: string
  onPick: (id: string) => void; blocked: boolean; onCreate: () => void; onAdd: () => void
}) {
  const { t } = useUiTranslation('characters')
  return <div className="space-y-2 rounded-lg border border-border p-3" data-testid="character-new-pose">
    <label className="block text-xs text-text-secondary">{t('styleCreator.newPose')}<input value={pose} maxLength={200} disabled={blocked} onChange={event => onPose(event.target.value)} placeholder={t('styleCreator.posePlaceholder')} className={`${control} mt-1 w-full`} /></label>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={blocked || !pose.trim()} onClick={onCreate} className={`${control} inline-flex items-center gap-2`}><Plus size={15} />{t('styleCreator.createPose')}</button>
      {picked && <button type="button" disabled={blocked} onClick={onAdd} className={`${control} text-emerald-200`}>{t('styleCreator.addPose')}</button>}
    </div>
    {candidates.length > 0 && <Candidates candidates={candidates} picked={picked} onPick={item => onPick(item.id)} disabled={blocked} />}
  </div>
}

function Status({ busy, message, error }: { busy: '' | Step; message: string; error: string }) {
  const { t } = useUiTranslation('characters')
  return <>
    {busy && <p role="status" className="text-sm text-text-muted">{t(`styleCreator.busy.${busy}`)}</p>}
    {message && <p role="status" className="text-sm text-emerald-200">{message}</p>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </>
}

/** Description → three keyed options → pick → saved kit that already talks (flat rig) → more poses. */
export function CharacterStyleCreator({ workspace, style, model, disabled }: {
  workspace: string; style: CharacterStyle; model: string; disabled?: boolean
}) {
  const { t } = useUiTranslation('characters')
  const [name, setName] = useState(''), [description, setDescription] = useState('')
  const [candidates, setCandidates] = useState<KeyedCandidate[]>([]), [picked, setPicked] = useState<string>()
  const [kit, setKit] = useState<CharacterKit>(), [rig, setRig] = useState<RigShown>()
  const [pose, setPose] = useState(''), [poseCandidates, setPoseCandidates] = useState<KeyedCandidate[]>([]), [pickedPose, setPickedPose] = useState<string>()
  const [busy, setBusy] = useState<'' | Step>(''), [error, setError] = useState(''), [message, setMessage] = useState('')
  const operation = useRef<AbortController | null>(null), jobs = useRef<string[]>([])
  // A failed rig keeps the saved draft; trying another option updates that same kit.
  const draftId = useRef(`character-${randomUuid()}`)
  useEffect(() => () => { operation.current?.abort(); jobs.current.forEach(id => void cancelJob(id).catch(() => {})) }, [])

  const run = async (label: Step, task: (signal: AbortSignal) => Promise<void>) => {
    if (operation.current || disabled) return
    const controller = new AbortController(); operation.current = controller
    setBusy(label); setError(''); setMessage('')
    try { await task(controller.signal) } catch (cause) { if (!controller.signal.aborted) setError((cause as Error).message) }
    finally { if (!controller.signal.aborted) { operation.current = null; jobs.current = []; setBusy('') } }
  }
  const stop = () => {
    operation.current?.abort(); operation.current = null
    jobs.current.forEach(id => void cancelJob(id).catch(() => {})); jobs.current = []
    setBusy(''); setMessage(t('imageCreator.cancelled'))
  }
  const options = (kind: 'character' | 'pose', text: string, references: string[] | undefined, onUpdate: (items: KeyedCandidate[]) => void) =>
    (signal: AbortSignal) => generateKeyedCandidates({ workspace, style, kind, description: text, model, references, signal, onUpdate,
      onJobSubmitted: id => { jobs.current.push(id) } }).then(found => {
      setMessage(found.some(item => item.status === 'ready') ? t('styleCreator.pick') : t('styleCreator.noneReady'))
    })

  const createOptions = () => run('options', async signal => {
    setPicked(undefined); setKit(undefined); setRig(undefined)
    await options('character', description.trim(), undefined, setCandidates)(signal)
    void useStore.getState().loadOutputs().catch(() => {})
  })
  const saveAndRig = () => run('rig', async signal => {
    const chosen = candidates.find(candidate => candidate.id === picked)
    if (!chosen?.keyed) return
    const draft = createCharacterKit(name.trim()); draft.id = draftId.current
    draft.style = style.kitStyle as CharacterKit['style']
    draft.base = keyedAsset(`${draft.id}-base`, draft.name, chosen.keyed, workspace, description.trim(), model)
    draft.identityReference = { ...draft.base, id: `${draft.id}-identity` }
    draft.lookNotes = description.trim()
    draft.provenance = [{ method: 'character-style-create', style: style.id, source: chosen.raw, keyed: chosen.keyed, model, seed: chosen.seed }]
    const library = await fetchCharacterKitLibrary(workspace); signal.throwIfAborted()
    const saved = await saveCharacterKit(workspace, library, draft); signal.throwIfAborted()
    const rigged = await rigFlatCharacter({ workspace, kitId: draft.id, baseRevision: saved.revision, style: style.rig }); signal.throwIfAborted()
    setKit(rigged.character); setRig(rigged); setMessage(t('styleCreator.ready'))
  })
  const createPoseOptions = () => run('pose', async signal => {
    if (!kit) return
    setPickedPose(undefined)
    const identity = kit.identityReference?.source || kit.base?.source
    await options('pose', pose.trim(), identity ? [identity] : undefined, setPoseCandidates)(signal)
  })
  const addPose = () => run('addPose', async signal => {
    const chosen = poseCandidates.find(candidate => candidate.id === pickedPose)
    if (!kit || !chosen?.keyed) return
    const id = poseId(pose)
    const library = await fetchCharacterKitLibrary(workspace); signal.throwIfAborted()
    const current = library.kits[kit.id] ?? kit
    const next: CharacterKit = { ...current, poses: { ...current.poses,
      [id]: keyedAsset(`${kit.id}-${id}`.slice(0, 120), `${kit.name} ${pose.trim()}`.slice(0, 240), chosen.keyed, workspace, pose.trim(), model) } }
    const saved = await saveCharacterKit(workspace, library, next); signal.throwIfAborted()
    const rigged = await rigFlatCharacter({ workspace, kitId: kit.id, baseRevision: saved.revision, style: style.rig, poses: ['base', id] })
    signal.throwIfAborted()
    setKit(rigged.character); setRig(rigged)
    setPose(''); setPoseCandidates([]); setMessage(t('styleCreator.poseAdded'))
  })

  /** The first designed voice also becomes the default voice for every other language. */
  const saveVoice = async (language: SpokenLanguage, voice: CustomCharacterVoice) => {
    if (!kit) return
    const library = await fetchCharacterKitLibrary(workspace)
    const current = library.kits[kit.id] ?? kit
    const saved = await saveCharacterKit(workspace, library, { ...current, voice: current.voice ?? voice,
      voicesByLanguage: { ...current.voicesByLanguage, [language]: voice } })
    setKit(saved.kits[kit.id])
  }

  const blocked = Boolean(busy) || Boolean(disabled)
  return <div className="space-y-4" data-testid="character-style-creator">
    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_16rem]">
      <div className="space-y-3">
        <label className="block text-xs text-text-secondary">{t('imageCreator.name')}<input value={name} maxLength={80} disabled={blocked || Boolean(kit)} onChange={event => setName(event.target.value)} className={`${control} mt-1 w-full`} /></label>
        <label className="block text-xs text-text-secondary">{t('imageCreator.description')}<textarea value={description} maxLength={2000} rows={3} disabled={blocked || Boolean(kit)} onChange={event => setDescription(event.target.value)} placeholder={t('styleCreator.placeholder')} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-3 text-sm" /></label>
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={blocked || Boolean(kit) || !model || !name.trim() || !description.trim()} onClick={() => void createOptions()} className={`${control} inline-flex items-center gap-2 text-cyan-200`}>
            {busy === 'options' ? <Loader2 size={15} className="animate-spin" /> : <WandSparkles size={15} />}{t('styleCreator.createOptions')}</button>
          {(busy === 'options' || busy === 'pose') && <button type="button" onClick={stop} className={control}>{t('lips.cancel')}</button>}
          {!kit && picked && <button type="button" disabled={blocked} onClick={() => void saveAndRig()} className={`${control} text-emerald-200`}>
            {busy === 'rig' ? <Loader2 size={15} className="mr-1 inline animate-spin" /> : null}{t('styleCreator.saveAndRig')}</button>}
        </div>
      </div>
      {candidates.length ? <Candidates candidates={candidates} picked={picked} onPick={item => setPicked(item.id)} disabled={blocked || Boolean(kit)} />
        : <div className="flex min-h-36 items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-text-muted">{t('styleCreator.empty')}</div>}
    </div>
    {kit && rig && <RigReview workspace={workspace} kit={kit} rig={rig} blocked={blocked} onUseVoice={saveVoice} />}
    {kit && <NewPose pose={pose} onPose={setPose} candidates={poseCandidates} picked={pickedPose} onPick={setPickedPose} blocked={blocked}
      onCreate={() => void createPoseOptions()} onAdd={() => void addPose()} />}
    <Status busy={busy} message={message} error={error} />
  </div>
}
