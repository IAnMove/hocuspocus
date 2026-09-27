import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'

/** Fit the picture inside the editor, independently of the output resolution. */
export function Scene3DPreview({ width, height, children }: { width: number; height: number; children: ReactNode }) {
  const { t } = useUiTranslation('scene3dEditor')
  const host = useRef<HTMLDivElement>(null)
  const frame = useRef<HTMLDivElement>(null)
  const [expanded, setExpanded] = useState(false)
  const [fallback, setFallback] = useState(false)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useEffect(() => {
    const update = () => setExpanded(document.fullscreenElement === host.current)
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setFallback(false) }
    document.addEventListener('fullscreenchange', update)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('fullscreenchange', update); document.removeEventListener('keydown', escape) }
  }, [])
  useEffect(() => {
    const node = frame.current
    if (!node) return
    const resize = () => {
      const rect = node.getBoundingClientRect()
      const ratio = Math.max(1, width) / Math.max(1, height)
      const w = Math.min(rect.width, rect.height * ratio)
      setSize({ width: w, height: w / ratio })
    }
    const observer = new ResizeObserver(resize)
    observer.observe(node); resize()
    return () => observer.disconnect()
  }, [width, height])
  const toggle = async () => {
    if (fallback) { setFallback(false); return }
    if (document.fullscreenElement === host.current) { await document.exitFullscreen(); return }
    try { await host.current?.requestFullscreen() } catch { setFallback(true) }
  }
  const full = expanded || fallback
  return <div ref={host} data-testid="scene3d-preview" className={`flex min-w-0 flex-col overflow-hidden rounded-xl border border-border bg-black ${fallback ? 'fixed inset-0 z-[1000]' : ''}`} style={full ? { height: '100dvh', width: '100%' } : undefined}>
    <div className="flex shrink-0 items-center justify-between gap-3 bg-bg-secondary px-3 py-2 text-sm text-text-primary">
      <span>{t('preview.title')} · {width} × {height}</span>
      <button type="button" onClick={() => void toggle()} className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3" aria-pressed={full}>
        {full ? <Minimize2 size={18} /> : <Maximize2 size={18} />}{full ? t('preview.exit') : t('preview.expand')}
      </button>
    </div>
    <div ref={frame} data-testid="scene3d-preview-matte" className={`flex min-h-0 w-full items-center justify-center bg-black ${full ? 'flex-1' : ''}`} style={full ? undefined : { height: 'clamp(260px, 48vh, 520px)' }}>
      <div data-testid="scene3d-preview-picture" className="relative shrink-0" style={{ width: size.width, height: size.height }}>{children}</div>
    </div>
  </div>
}
