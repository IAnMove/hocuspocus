import { useState } from 'react'
import { useUiTranslation } from '../i18n'

type RuntimeIdentity = { instance_id: string; ui_build_id: string }

export function RuntimeUpdateNotice({ identity }: { identity?: RuntimeIdentity }) {
  const { t } = useUiTranslation('common')
  const [initial, setInitial] = useState('')
  const [dismissed, setDismissed] = useState('')
  const current = identity?.ui_build_id && identity.ui_build_id !== 'missing'
    ? `${identity.instance_id}:${identity.ui_build_id}` : ''
  if (current && !initial) setInitial(current)
  if (!initial || !current || initial === current || dismissed === current) return null
  return <div role="status" className="fixed right-4 top-16 z-[120] max-w-sm rounded-lg border border-border bg-bg-secondary p-4 text-xs text-text-primary shadow-xl">
    <p>{t('runtimeUpdate.message')}</p>
    <div className="mt-3 flex gap-3">
      <button type="button" className="text-accent-blue" onClick={() => window.location.reload()}>{t('runtimeUpdate.reload')}</button>
      <button type="button" onClick={() => setDismissed(current)}>{t('runtimeUpdate.later')}</button>
    </div>
  </div>
}
