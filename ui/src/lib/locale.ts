export type AppLocale = string
export type AppAction = 'added' | 'finished' | 'updated'

const ACTION_LABELS: Record<'en' | 'es', Record<AppAction, string>> = {
  en: { added: 'Added', finished: 'Finished', updated: 'Updated' },
  es: { added: 'Añadido', finished: 'Finalizado', updated: 'Actualizado' },
}

export function getApplicationLocale(): AppLocale {
  if (typeof document !== 'undefined') {
    const documentLocale = document.documentElement.lang.trim()
    if (documentLocale) return documentLocale
  }
  if (typeof navigator !== 'undefined' && navigator.language) return navigator.language
  return 'en'
}

function timestampToMilliseconds(value: number | null | undefined): number | null {
  if (!Number.isFinite(value) || !value || value <= 0) return null
  return value < 1_000_000_000_000 ? value * 1000 : value
}

export function formatAppTimestamp(
  value: number | null | undefined,
  options: { locale?: AppLocale; timeZone?: string } = {},
): string | null {
  const milliseconds = timestampToMilliseconds(value)
  if (milliseconds === null) return null
  const date = new Date(milliseconds)
  if (Number.isNaN(date.getTime())) return null
  return new Intl.DateTimeFormat(options.locale || getApplicationLocale(), {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    ...(options.timeZone ? { timeZone: options.timeZone } : {}),
  }).format(date)
}

export function formatAppAction(action: AppAction, locale = getApplicationLocale()): string {
  const language = locale.toLowerCase().split('-')[0] === 'es' ? 'es' : 'en'
  return ACTION_LABELS[language][action]
}
