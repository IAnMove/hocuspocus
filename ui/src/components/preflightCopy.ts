import i18n from '../i18n'
import type { PreflightCheck } from '../api/client'

/** Server checks have a stable id. The English message stays on the wire. */
export function preflightText(check: Pick<PreflightCheck, 'id' | 'level' | 'message'>): string {
  if (check.id === 'ffmpeg') return i18n.t('preflight.ffmpeg', { ns: 'shell' })
  if (check.id === 'cuda') return i18n.t('preflight.cuda', { ns: 'shell' })
  if (check.id === 'torch') return i18n.t('preflight.torch', { ns: 'shell' })
  if (check.id === 'disk') {
    const gb = /(\d+(?:\.\d+)?)\s*GB/i.exec(check.message)?.[1]
    if (!gb) return i18n.t('preflight.diskUnknown', { ns: 'shell' })
    return check.level === 'error'
      ? i18n.t('preflight.diskError', { ns: 'shell', gb })
      : i18n.t('preflight.diskWarn', { ns: 'shell', gb })
  }
  return check.message
}
