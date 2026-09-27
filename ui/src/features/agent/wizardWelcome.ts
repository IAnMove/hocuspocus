import i18n, { resources } from '../../i18n'

/** Recognize only the built-in greeting, including greetings in older saved chats. */
const greetings = new Set(Object.values(resources).map(resource => resource.wizard.welcome))

export function wizardWelcomeText(): string {
  return i18n.t('welcome', { ns: 'wizard' })
}

/** Presentation only: preserve conversation IDs, cards and authored messages. */
export function localizeWizardWelcome<T extends { role: string; text: string; language?: string }>(message: T): T {
  if (message.role !== 'assistant' || !greetings.has(message.text)) return message
  return { ...message, text: wizardWelcomeText(), language: i18n.resolvedLanguage || i18n.language }
}
