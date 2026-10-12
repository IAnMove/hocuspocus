import type { TFunction } from 'i18next'
import { Clapperboard, Type } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import { sectionId, type PartContext } from './context'
import { NumberInput, SelectInput, TextInput } from './fields'
import { grid, languageName, withField } from './model'
import { InspectorSection, type DraftProps } from './InspectorSection'

const FRAMINGS = ['wide', 'two', 'medium', 'close', 'insert', 'title'] as const
type Timing = { intro?: number; gap?: number; tail?: number }

/** The shot's length: from its lines, or the one it says. */
function planLength(t: TFunction<'seriesLab'>, context: PartContext): string {
  return context.script?.lines?.length ? t('inspector.plan.fromLines', { seconds: Number(context.shot.durationSeconds.toFixed(2)) })
    : t('inspector.plan.length', { seconds: context.script?.duration ?? context.shot.durationSeconds })
}

/** Framing, camera, length and pauses in words. */
function planSummary(t: TFunction<'seriesLab'>, context: PartContext): string {
  const script = context.script || {}
  const timing = (script.timing || {}) as Timing
  const framing = FRAMINGS.find(item => item === script.framing)
  const camera = (['push', 'static'] as const).find(item => item === script.camera)
  return [framing ? t(`approval.framings.${framing}`) : script.framing, camera ? t(`approval.cameras.${camera}`) : script.camera, planLength(t, context),
    ...(['intro', 'gap', 'tail'] as const).filter(key => typeof timing[key] === 'number').map(key => t(`inspector.plan.${key}Short`, { seconds: timing[key] })),
  ].filter(Boolean).join(' · ')
}

function PlanEditor({ draft, change, lines }: DraftProps & { lines: boolean }) {
  const { t } = useUiTranslation('seriesLab')
  const next = (draft.timing || {}) as Timing
  const setTiming = (key: keyof Timing, value: number | undefined) => {
    const updated = withField(next, key, value)
    change(withField(draft, 'timing', Object.keys(updated).length ? updated : undefined))
  }
  return <div className={grid}>
    <SelectInput title={t('approval.edit.framing')} value={draft.framing} empty={t('approval.edit.auto')} onChange={value => change(withField(draft, 'framing', value))}
      options={FRAMINGS.map(value => ({ value, label: t(`approval.framings.${value}`) }))} />
    <SelectInput title={t('approval.edit.camera')} value={draft.camera} empty={t('approval.edit.auto')} onChange={value => change(withField(draft, 'camera', value))}
      options={(['static', 'push'] as const).map(value => ({ value, label: t(`approval.cameras.${value}`) }))} />
    <NumberInput title={t('approval.edit.intro')} value={next.intro} min={0} max={6} onChange={value => setTiming('intro', value)} />
    <NumberInput title={t('inspector.plan.gap')} value={next.gap} min={0} max={6} onChange={value => setTiming('gap', value)} />
    <NumberInput title={t('approval.edit.tail')} value={next.tail} min={0} max={6} onChange={value => setTiming('tail', value)} />
    {!lines && <NumberInput title={t('inspector.plan.duration')} value={draft.duration} min={0.5} max={60} step={0.1}
      onChange={value => change(withField(draft, 'duration', value))} />}
  </div>
}

/** Framing, camera, the pauses around the lines and, for a shot without lines, its length. */
export function PlanPart({ context }: { context: PartContext }) {
  const { t } = useUiTranslation('seriesLab')
  return <InspectorSection id={sectionId(context.shot.id, 'plan')} inspector={context.inspector} shotId={context.shot.id} section="plan"
    script={context.script} draft={context.drafts.plan} save={context.save} icon={<Clapperboard size={14} />} title={t('inspector.plan.title')}
    summary={planSummary(t, context)} editor={props => <PlanEditor {...props} lines={Boolean(context.script?.lines?.length)} />} />
}

type Card = { kind?: string; [language: string]: unknown }
const CARD_KINDS = ['title', 'disclaimer', 'end'] as const

/** A title, disclaimer or end card: its kind and its title and body in each language. */
export function CardPart({ context }: { context: PartContext }) {
  const { t, i18n } = useUiTranslation('seriesLab')
  const card = context.script?.card as Card | undefined
  const kind = CARD_KINDS.find(item => item === card?.kind)
  const texts = (value: Card | undefined, language: string) => (Array.isArray(value?.[language]) ? value![language] : ['', '']) as string[]
  const languages = card ? Object.keys(card).filter(key => key !== 'kind' && Array.isArray(card[key])) : [context.language]
  return <InspectorSection id={sectionId(context.shot.id, 'card')} inspector={context.inspector} shotId={context.shot.id} section="card"
    script={context.script} draft={context.drafts.card} save={context.save} icon={<Type size={14} />} title={t('inspector.card.title')}
    summary={card ? `${kind ? t(`inspector.card.kinds.${kind}`) : String(card.kind)} · ${texts(card, context.language).filter(Boolean).join(' — ')}` : t('inspector.card.empty')}
    editor={({ draft, change }) => {
      const next = (draft.card || { kind: 'title', [context.language]: ['', ''] }) as Card
      const shown = languages.includes(context.language) ? languages : [context.language, ...languages]
      return <div className="space-y-2">
        <SelectInput title={t('inspector.card.kind')} value={next.kind} onChange={value => change({ ...draft, card: { ...next, kind: value } })}
          options={CARD_KINDS.map(value => ({ value, label: t(`inspector.card.kinds.${value}`) }))} />
        {shown.map(language => <div key={language} className="grid gap-2 @md:grid-cols-2">
          <TextInput title={t('inspector.card.cardTitle', { language: languageName(language, i18n.language) })} value={texts(next, language)[0]}
            onChange={value => change({ ...draft, card: { ...next, [language]: [value, texts(next, language)[1] || ''] } })} />
          <TextInput multiline title={t('inspector.card.body', { language: languageName(language, i18n.language) })} value={texts(next, language)[1]}
            onChange={value => change({ ...draft, card: { ...next, [language]: [texts(next, language)[0] || '', value] } })} />
        </div>)}
      </div>
    }} />
}
