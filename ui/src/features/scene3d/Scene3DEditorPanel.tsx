import { useEffect, useRef, useState } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { Scene3DWorkspace } from './Scene3DWorkspace.tsx'

export function Scene3DEditorPanel() {
  const { t } = useUiTranslation('scene3dEditor')
  const host = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [error, setError] = useState(false)
  useEffect(() => {
    const update = () => setExpanded(document.fullscreenElement === host.current)
    document.addEventListener('fullscreenchange', update)
    return () => document.removeEventListener('fullscreenchange', update)
  }, [])
  const toggle = async () => {
    try {
      if (document.fullscreenElement === host.current) await document.exitFullscreen()
      else await host.current?.requestFullscreen()
      setError(false)
    } catch { setError(true) }
  }
  const focusLabel = expanded ? t('exitFocus') : t('focusEditor')
  return (
    <div ref={host} className={`flex min-h-0 w-full min-w-0 flex-1 flex-col bg-bg-primary ${expanded ? 'h-screen overflow-hidden p-2' : 'h-full'}`} data-testid="world3d-editor">
      {error && <p role="status" className="text-xs text-amber-200">{t('fullscreenUnavailable')}</p>}
      <Scene3DWorkspace
        width={1280}
        height={720}
        fill
        topBarExtra={(
          <button type="button" aria-label={focusLabel} title={focusLabel} onClick={() => void toggle()} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-lg border border-border px-2 text-xs text-text-primary">
            {expanded ? <Minimize2 size={15} aria-hidden="true" /> : <Maximize2 size={15} aria-hidden="true" />}
            <span>{focusLabel}</span>
          </button>
        )}
      />
    </div>
  )
}
