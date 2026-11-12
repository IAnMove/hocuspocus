import { Bot } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { reviewedByAgent, type KitAnimation } from '../../lib/characterAnimations'

/** «Aprobada por el agente»: an animation reviewed in «Modo un solo disparo» says so, with the agent's note as its tooltip, so the owner can
 * audit it. Approve and Reject on the card take the decision back (they set the review as a person's). Nothing shows for a person's review. */
export function AnimationAgentBadge({ animation }: { animation: Pick<KitAnimation, 'reviewState' | 'reviewedBy' | 'reviewNote'> }) {
  const { t } = useUiTranslation('characters')
  if (!reviewedByAgent(animation)) return null
  const label = t(animation.reviewState === 'approved' ? 'animations.agent.approved' : 'animations.agent.rejected')
  const note = animation.reviewNote?.trim()
  return <span data-testid="animation-agent-badge" title={note || label} aria-label={note ? `${label}: ${note}` : label}
    className="inline-flex shrink-0 items-center gap-1 rounded border border-violet-400/40 px-1.5 py-0.5 text-[10px] text-violet-200">
    <Bot size={10} aria-hidden="true" />{label}
  </span>
}
