import { lazy, Suspense, useState } from 'react'
import { useUiTranslation } from '../../i18n'

const Panel = lazy(() => import('./CharacterAnimationsPanel').then(module => ({ default: module.CharacterAnimationsPanel })))

/** Closing the drawer keeps its state; first opening is the only lazy load. */
export function CharacterAnimationsEntry({ workspace }: { workspace: string }) {
  const { t } = useUiTranslation('characters')
  const [visited, setVisited] = useState(false)
  return <details className="mx-auto mb-4 max-w-5xl rounded-lg border border-cyan-400/30 p-3" onToggle={event => { if (event.currentTarget.open) setVisited(true) }}>
    <summary className="cursor-pointer text-sm font-medium text-cyan-100">{t('animations.title')}</summary>
    {visited && <div className="mt-3"><Suspense fallback={<p role="status">{t('animations.loading')}</p>}><Panel workspace={workspace} /></Suspense></div>}
  </details>
}
