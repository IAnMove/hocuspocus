import { useUiTranslation } from '../../i18n'
import { panel } from './storyLabChrome'

export const TRAILER_ARC = [
  { key: 'impact', start: 0, end: 10 },
  { key: 'promise', start: 10, end: 30 },
  { key: 'rupture', start: 30, end: 50 },
  { key: 'escalation', start: 50, end: 80 },
  { key: 'breath', start: 80, end: 90 },
  { key: 'hook', start: 90, end: 100 },
] as const

export function StoryTrailerTimeline({ trailerDuration }: { trailerDuration: number }) {
  const { t } = useUiTranslation('storyLab')
  const arcCopy: Record<(typeof TRAILER_ARC)[number]['key'], { label: string; detail: string }> = {
    impact: { label: t('trailer.arcImpact'), detail: t('trailer.arcImpactDetail') },
    promise: { label: t('trailer.arcPromise'), detail: t('trailer.arcPromiseDetail') },
    rupture: { label: t('trailer.arcRupture'), detail: t('trailer.arcRuptureDetail') },
    escalation: { label: t('trailer.arcEscalation'), detail: t('trailer.arcEscalationDetail') },
    breath: { label: t('trailer.arcBreath'), detail: t('trailer.arcBreathDetail') },
    hook: { label: t('trailer.arcHook'), detail: t('trailer.arcHookDetail') },
  }
  return (
    <div className={`${panel} space-y-3`}>
      <div><h3 className="text-sm font-semibold text-text-primary">{t('trailer.timeline')}</h3><p className="mt-1 text-[10px] text-text-muted">{t('trailer.timelineHint')}</p></div>
      {TRAILER_ARC.map((phase, index) => {
        const start = Math.round(trailerDuration * phase.start / 100)
        const end = Math.round(trailerDuration * phase.end / 100)
        const copy = arcCopy[phase.key]
        return <div key={phase.key} className="grid grid-cols-[2rem_minmax(0,1fr)_3.5rem] items-start gap-2 rounded-lg border border-border bg-bg-primary/35 p-2.5">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/15 text-[10px] font-semibold text-amber-200">{index + 1}</span>
          <span><span className="block text-[10px] font-medium text-text-primary">{copy.label}</span><span className="mt-0.5 block text-[9px] leading-relaxed text-text-muted">{copy.detail}</span></span>
          <span className="text-right text-[9px] font-medium text-amber-200">{start}–{end}s</span>
        </div>
      })}
    </div>
  )
}
