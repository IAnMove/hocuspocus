import type { ReactNode } from 'react'
import type { ParseKeys } from 'i18next'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import type { RigAnimation, RigCapabilities, RigJob } from '../../api/model3d'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { HumanoidAnimateSection } from './HumanoidAnimateSection'
import { clampBpm, clipGroups, refusalKey, rigHelpKey, warningKeys } from './humanoidRig'

/** Keys built from ids that the catalogs define; ``defaultValue`` covers anything new. */
const key = (value: string) => value as ParseKeys<'scene3d'>

/** Tempo and the three things a model needs before the humanoid engine can rig it. */
export function HumanoidOptions({ bpm, onBpm }: { bpm: number; onBpm: (bpm: number) => void }) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div className="space-y-2.5 rounded-lg border border-border bg-bg-tertiary p-2.5">
      <label className="block text-[10px] uppercase tracking-wider text-text-muted">
        <span className="flex items-center justify-between"><span>{t('rig.bpm')}</span><span className="text-text-primary">{bpm}</span></span>
        <input type="range" min={60} max={180} step={1} value={bpm} onChange={event => onBpm(clampBpm(Number(event.target.value)))} className="mt-1.5 w-full" />
        <span className="mt-0.5 block normal-case tracking-normal text-[9px] text-text-muted/80">{t('rig.bpmHelp')}</span>
      </label>
      <div className="rounded border border-accent-blue/20 bg-accent-blue/5 p-2">
        <div className="flex items-center gap-1 text-[10px] font-medium text-text-secondary"><Info size={11} className="text-accent-blue" /> {t('rig.prepTitle')}</div>
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[9px] leading-relaxed text-text-muted">
          <li>{t('rig.prepPose')}</li>
          <li>{t('rig.prepGaps')}</li>
          <li>{t('rig.prepPrompt')}</li>
        </ul>
      </div>
    </div>
  )
}

/** Engine help, tempo and preparation tips; nothing for the other engines. */
export function HumanoidEngineIntro({ engineId, bpm, onBpm }: { engineId: string; bpm: number; onBpm: (bpm: number) => void }) {
  const { t } = useUiTranslation('scene3d')
  if (engineId !== 'humanoid') return null
  return (
    <>
      <p className="-mt-2 text-[9px] text-text-muted/80">{t(rigHelpKey(engineId))}</p>
      <HumanoidOptions bpm={bpm} onBpm={onBpm} />
    </>
  )
}

/** The job's error, or the humanoid refusal and result. */
export function HumanoidJobNotes({ job }: { job: RigJob }) {
  return (
    <>
      {job.error && !refusalKey(job) && <p className="mt-2 max-h-24 overflow-y-auto whitespace-pre-wrap text-[10px] text-red-300">{job.error}</p>}
      <HumanoidRefusal job={job} />
      {job.status === 'completed' && <HumanoidResult job={job} />}
    </>
  )
}

/** The "add animations" card, when the humanoid engine is installed. Keyed by workspace so a switch starts it fresh. */
export function HumanoidAnimateSlot({ capabilities, job }: { capabilities: RigCapabilities; job: RigJob | null }) {
  const workspace = useStore(state => state.activeWorkspace) || 'default'
  if (!capabilities.engines.some(item => item.id === 'humanoid' && item.installed)) return null
  return <HumanoidAnimateSection key={workspace} clips={capabilities.humanoid_animations ?? []} refreshKey={job?.status === 'completed' ? job.filename : null} />
}

/** What the engine detected and which clips the new GLB holds. */
export function HumanoidResult({ job }: { job: RigJob }) {
  const { t } = useUiTranslation('scene3d')
  const summary = job.humanoid
  if (!summary) return null
  const warnings = warningKeys(summary.warnings)
  return (
    <div className="mt-2 space-y-1.5 rounded border border-accent-green/25 bg-accent-green/5 p-2 text-[9px] text-text-muted">
      {summary.pose && (
        <p className="flex items-center gap-1 text-text-secondary"><CheckCircle2 size={11} className="text-accent-green" />
          {t(summary.pose === 'a' ? 'rig.detectedA' : 'rig.detectedT', { angle: Math.round(summary.arm_drop ?? 0) })}
        </p>
      )}
      {warnings.map(item => <p key={item} className="flex items-start gap-1 text-amber-300/90"><AlertTriangle size={10} className="mt-0.5 shrink-0" /> {t(key(item))}</p>)}
      {summary.clips?.length ? (
        <p>{t('rig.clipsInGlb')}: {summary.clips.map(clip => `${clip.index} · ${clip.name}`).join(', ')}</p>
      ) : null}
    </div>
  )
}

/** A refused mesh: the reason in plain words and how to fix the model. */
export function HumanoidRefusal({ job }: { job: RigJob | null }) {
  const { t } = useUiTranslation('scene3d')
  const reason = refusalKey(job)
  if (!reason) return null
  return (
    <div className="mt-2 rounded border border-amber-500/30 bg-amber-500/10 p-2 text-[10px] text-amber-200">
      <p className="font-medium">{t('rig.refusalTitle')}</p>
      <p className="mt-0.5 text-amber-100/90">{t(key(reason))}</p>
      <p className="mt-1 text-[9px] text-amber-100/70">{t('rig.refusalFix')}</p>
    </div>
  )
}

/** Humanoid clips grouped by category; ``renderClip`` draws one card. */
export function HumanoidClipGroups({ animations, renderClip }: { animations: RigAnimation[]; renderClip: (animation: RigAnimation) => ReactNode }) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div className="max-h-[620px] space-y-2 overflow-y-auto pr-0.5">
      {clipGroups(animations).map(group => (
        <div key={group.category}>
          <p className="mb-1 text-[9px] uppercase tracking-wider text-text-muted">{t(key(`rig.clipCategory.${group.category}`), { defaultValue: group.category })}</p>
          <div className="grid grid-cols-2 gap-1.5">{group.clips.map(renderClip)}</div>
        </div>
      ))}
    </div>
  )
}
