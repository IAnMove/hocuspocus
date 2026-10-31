import i18n from './index'

/** The same text for an icon control's `aria-label` and `title`. */
export function controlLabel(key: string, options?: Record<string, unknown>) {
  return String(i18n.t(key, key, { ns: 'common', ...options }))
}

/** That text while `active`, and nothing otherwise. The branch stays here. */
export function controlReason(active: boolean | undefined, key: string, options?: Record<string, unknown>) {
  if (!active) return undefined
  return controlLabel(key, options)
}

/** One label or the other. The branch stays here. */
export function controlChoice(active: boolean | undefined, whenActive: string, whenIdle: string) {
  return controlLabel(active ? whenActive : whenIdle)
}

/** The first cause that is true, in the order given. */
export function firstControlReason(causes: ReadonlyArray<readonly [boolean | undefined, string]>) {
  for (const [active, key] of causes) {
    if (active) return controlLabel(key)
  }
  return undefined
}
