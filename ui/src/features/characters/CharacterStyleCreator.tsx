import { useEffect, useState } from 'react'
import { Loader2, Mic, Plus, RotateCcw, WandSparkles } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import type { CharacterKit } from '../../lib/characterKit'
import type { CharacterStyle } from '../../lib/characterStyles'
import { flaggedRigPoses, isWarpRigged } from '../../lib/flatRigMouth'
import { CANDIDATE_COUNT, type KeyedCandidate } from './characterCandidates'
import { useCreatorSession, type CreatorMessage, type RigShown, type Step } from './characterCreatorSession'
import { CandidateGrid } from './CandidateGrid'
import { CharacterVoiceDesigner } from './CharacterVoiceDesigner'
import type { CustomCharacterVoice } from '../../lib/characterVoice'
import type { SpokenLanguage } from '../../lib/speechLanguage'

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'

/** The pictures a run draws are workspace outputs: the gallery reads them again. */
const loadPictures = () => { void useStore.getState().loadOutputs().catch(() => {}) }

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

function NewPose({ pose, onPose, candidates, picked, pickedReady, onPick, blocked, locked, onCreate, onAdd }: {
  pose: string; onPose: (value: string) => void; candidates: KeyedCandidate[]; picked?: string; pickedReady: boolean
  onPick: (candidate: KeyedCandidate) => void; blocked: boolean; locked: boolean; onCreate: () => void; onAdd: () => void
}) {
  const { t } = useUiTranslation('characters')
  return <div className="space-y-2 rounded-lg border border-border p-3" data-testid="character-new-pose">
    <label className="block text-xs text-text-secondary">{t('styleCreator.newPose')}<input value={pose} maxLength={200} disabled={blocked} onChange={event => onPose(event.target.value)} placeholder={t('styleCreator.posePlaceholder')} className={`${control} mt-1 w-full`} /></label>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={blocked || !pose.trim()} onClick={onCreate} className={`${control} inline-flex items-center gap-2`}><Plus size={15} />{t('styleCreator.createPose')}</button>
      {picked && <button type="button" disabled={blocked || !pickedReady} onClick={onAdd} className={`${control} text-emerald-200`}>{t('styleCreator.addPose')}</button>}
    </div>
    {candidates.length > 0 && <CandidateGrid candidates={candidates} picked={picked} onPick={onPick} locked={locked} />}
  </div>
}

function Status({ busy, message, error }: { busy: '' | Step; message: '' | CreatorMessage; error: string }) {
  const { t } = useUiTranslation('characters')
  return <>
    {busy && <p role="status" className="text-sm text-text-muted">{t(`styleCreator.busy.${busy}`)}</p>}
    {message && <p role="status" className="text-sm text-emerald-200">{t(message)}</p>}
    {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
  </>
}

/** How many options to make: one to three. */
function CountPicker({ count, disabled, onChange }: { count: number; disabled: boolean; onChange: (count: number) => void }) {
  const { t } = useUiTranslation('characters')
  return <div role="group" aria-label={t('styleCreator.count')} className="flex items-center gap-2 text-xs text-text-secondary">
    {t('styleCreator.count')}
    {Array.from({ length: CANDIDATE_COUNT }, (_, index) => index + 1).map(number => <button key={number} type="button" disabled={disabled} aria-pressed={count === number}
      onClick={() => onChange(number)} className={`${control} min-w-10 ${count === number ? 'border-cyan-300 text-cyan-200' : ''}`}>{number}</button>)}
  </div>
}

type Session = ReturnType<typeof useCreatorSession>['session']
type View = ReturnType<typeof useCreatorSession>['view']
type Context = Parameters<Session['createOptions']>[0]

/** Create, Cancel, Save and Start over: what can be done next with the options. */
function OptionsButtons({ session, view, context, blocked, disabled }: { session: Session; view: View; context: Context; blocked: boolean; disabled: boolean }) {
  const { t } = useUiTranslation('characters')
  const { kit, busy } = view
  const pickedReady = view.candidates.find(item => item.id === view.picked)?.status === 'ready'
  const working = busy === 'options' || busy === 'keying' || busy === 'pose'
  return <div className="flex flex-wrap gap-2">
    <button type="button" disabled={blocked || Boolean(kit) || !context.model || !view.name.trim() || !view.description.trim()} onClick={() => void session.createOptions(context)} className={`${control} inline-flex items-center gap-2 text-cyan-200`}>
      {busy === 'options' ? <Loader2 size={15} className="animate-spin" /> : <WandSparkles size={15} />}{t('styleCreator.createOptions', { count: view.count })}</button>
    {working && <button type="button" onClick={() => session.cancel()} className={control}>{t('lips.cancel')}</button>}
    {!kit && view.picked && <button type="button" disabled={blocked || !pickedReady} onClick={() => void session.saveAndRig(context)} className={`${control} text-emerald-200`}>
      {busy === 'rig' ? <Loader2 size={15} className="mr-1 inline animate-spin" /> : null}{t('styleCreator.saveAndRig')}</button>}
    {!busy && (view.candidates.length > 0 || kit) && <button type="button" disabled={disabled} onClick={() => session.reset()} className={`${control} inline-flex items-center gap-2`}>
      <RotateCcw size={14} />{t('styleCreator.startOver')}</button>}
  </div>
}

/** The name, the description, how many options, and what to do with them. */
function OptionsForm({ session, view, context, blocked, disabled }: { session: Session; view: View; context: Context; blocked: boolean; disabled: boolean }) {
  const { t } = useUiTranslation('characters')
  const frozen = blocked || Boolean(view.kit)
  return <div className="max-w-xl space-y-3">
    <label className="block text-xs text-text-secondary">{t('imageCreator.name')}<input value={view.name} maxLength={80} disabled={frozen} onChange={event => session.edit({ name: event.target.value })} className={`${control} mt-1 w-full`} /></label>
    <label className="block text-xs text-text-secondary">{t('imageCreator.description')}<textarea value={view.description} maxLength={2000} rows={3} disabled={frozen} onChange={event => session.edit({ description: event.target.value })} placeholder={t('styleCreator.placeholder')} className="mt-1 w-full rounded-lg border border-border bg-bg-primary p-3 text-sm" /></label>
    <CountPicker count={view.count} disabled={frozen} onChange={count => session.edit({ count })} />
    <OptionsButtons session={session} view={view} context={context} blocked={blocked} disabled={disabled} />
  </div>
}

/** Description → options → pick → saved kit that already talks (flat rig) → more poses. The work is the session's (it goes on when this
 * screen is left and is kept for the next visit); this only shows it and asks for the next step. */
export function CharacterStyleCreator({ workspace, style, model, disabled }: {
  workspace: string; style: CharacterStyle; model: string; disabled?: boolean
}) {
  const { t } = useUiTranslation('characters')
  const { session, view } = useCreatorSession(workspace)
  const context = { style, model, onPictures: loadPictures }
  useEffect(() => { session.resume({ style, model, onPictures: loadPictures }) }, [session, style, model])

  const { kit, rig, busy } = view
  const blocked = Boolean(busy) || Boolean(disabled)
  const poseReady = view.poseCandidates.find(item => item.id === view.pickedPose)?.status === 'ready'
  return <div className="space-y-4" data-testid="character-style-creator">
    <OptionsForm session={session} view={view} context={context} blocked={blocked} disabled={Boolean(disabled)} />
    {view.candidates.length
      ? <CandidateGrid candidates={view.candidates} picked={view.picked} onPick={item => session.pick('candidates', item.id)} locked={Boolean(disabled) || Boolean(kit) || busy === 'rig'} />
      : <div className="flex min-h-36 max-w-xl items-center justify-center rounded-lg border border-dashed border-border p-4 text-center text-xs text-text-muted">{t('styleCreator.empty')}</div>}
    {kit && rig && <RigReview workspace={workspace} kit={kit} rig={rig} blocked={blocked} onUseVoice={(language, voice) => session.saveVoice(language, voice)} />}
    {kit && <NewPose pose={view.pose} onPose={pose => session.edit({ pose })} candidates={view.poseCandidates} picked={view.pickedPose} pickedReady={poseReady}
      onPick={item => session.pick('poseCandidates', item.id)} blocked={blocked} locked={Boolean(disabled) || busy === 'addPose'}
      onCreate={() => void session.createPoseOptions(context)} onAdd={() => void session.addPose(context)} />}
    <Status busy={busy} message={view.message} error={view.error} />
  </div>
}
