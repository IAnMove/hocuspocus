import { lazy, Suspense, useEffect, useState } from 'react'
import { shotTarget, type ShotTarget } from './target'

const ShotLoader = lazy(() => import('./ProductionShotsPanel').then(module => ({
  default: module.ShotLoader,
})))

export function LazyProductionShotsOverlay() {
  const [target, setTarget] = useState<ShotTarget | null>(null)
  const [everOpened, setEverOpened] = useState(false)
  useEffect(() => {
    const openPanel = (event: Event) => {
      const next = shotTarget((event as CustomEvent).detail)
      if (!next) return
      setEverOpened(true)
      setTarget(next)
    }
    const closePanel = () => setTarget(null)
    window.addEventListener('hocuspocus:production-shots-open', openPanel)
    window.addEventListener('hocuspocus:production-shots-close', closePanel)
    return () => {
      window.removeEventListener('hocuspocus:production-shots-open', openPanel)
      window.removeEventListener('hocuspocus:production-shots-close', closePanel)
    }
  }, [])
  if (!everOpened || !target) return null
  return <Suspense fallback={null}>
    <ShotLoader
      key={`${target.workspace}:${target.productionId}`}
      workspace={target.workspace}
      productionId={target.productionId}
      onClose={() => setTarget(null)}
    />
  </Suspense>
}
