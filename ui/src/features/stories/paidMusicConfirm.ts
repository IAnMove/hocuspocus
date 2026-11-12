import i18n from '../../i18n'
import { isPaidMinimaxMusicModel } from '../../lib/musicGenerationSpec'

/**
 * Story Lab asks before every request to the paid MiniMax API, naming how many
 * requests it sends. A local model needs no question.
 */
export function confirmPaidStoryMusic(
  model: string,
  count = 1,
  ask: (message: string) => boolean = message => window.confirm(message),
): boolean {
  if (!isPaidMinimaxMusicModel(model)) return true
  return ask(i18n.t('music.paidConfirm', { ns: 'storyLab', model, count }))
}
