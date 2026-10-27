import i18n from './index'

/** The same text for an icon control's `aria-label` and `title`. */
export function controlLabel(key: string, options?: Record<string, unknown>) {
  return String(i18n.t(key, key, { ns: 'common', ...options }))
}
