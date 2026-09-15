import { useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { MAX_IMAGE_WINDOWS, MAX_WINDOW_POINTS, parseImageWindows, type ImageWindow } from './imageWindows'

export function Scene3DWindowControls({ sourceUrl, windows = [], disabled, onChange }: {
  sourceUrl: string; windows?: ImageWindow[]; disabled: boolean; onChange: (windows: ImageWindow[] | undefined) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const [draft, setDraft] = useState<ImageWindow>([])
  const [editing, setEditing] = useState<number | null>(null)
  const dragging = useRef<number | null>(null)
  const justDragged = useRef(false)
  const valid = parseImageWindows([draft])?.[0]
  const commit = () => {
    if (!valid || disabled || (editing === null && windows.length >= MAX_IMAGE_WINDOWS)) return
    onChange(editing === null ? [...windows, valid] : windows.map((value, i) => i === editing ? valid : value))
    setDraft([]); setEditing(null)
  }
  const coords = (event: React.PointerEvent<SVGSVGElement> | React.MouseEvent<SVGSVGElement>): [number, number] => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return [Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)), Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))]
  }
  const points = (polygon: ImageWindow) => polygon.map(([x, y]) => `${x * 1000},${y * 1000}`).join(' ')
  return <details className="my-2 rounded border border-border p-3" data-testid="scene3d-window-controls">
    <summary className="cursor-pointer text-sm font-medium">{t('windows.title', { count: windows.length })}</summary>
    <p className="my-2 text-xs text-text-muted">{t('windows.help')}</p>
    <fieldset disabled={disabled} className="space-y-2">
      <div className="relative mx-auto max-w-72 bg-black">
        <img src={sourceUrl} alt={t('windows.image')} className="block h-auto w-full" draggable={false} />
        <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" role="img" aria-label={t('windows.draw')} className="absolute inset-0 h-full w-full touch-none cursor-crosshair"
          onClick={event => {
            if (disabled || justDragged.current) { justDragged.current = false; return }
            if (draft.length < MAX_WINDOW_POINTS) setDraft([...draft, coords(event)])
          }}
          onPointerMove={event => {
            if (disabled || dragging.current === null) return
            const point = coords(event)
            setDraft(current => current.map((p, i) => i === dragging.current ? point : p))
          }}
          onPointerUp={() => { if (dragging.current !== null) justDragged.current = true; dragging.current = null }}
          onPointerCancel={() => { dragging.current = null }}>
          {windows.map((polygon, i) => i !== editing && <polygon key={i} points={points(polygon)} fill="#22d3ee55" stroke="#22d3ee" strokeWidth="2" />)}
          <polygon points={points(draft)} fill="#facc1533" stroke="#facc15" strokeWidth="3" />
          {draft.map(([x, y], i) => <circle key={i} cx={x * 1000} cy={y * 1000} r="10" fill="#facc15" onPointerDown={event => {
            if (disabled) return
            event.stopPropagation(); dragging.current = i
            event.currentTarget.ownerSVGElement?.setPointerCapture(event.pointerId)
          }} />)}
        </svg>
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <button type="button" className="min-h-10 rounded border border-border px-3" disabled={!valid || (editing === null && windows.length >= MAX_IMAGE_WINDOWS)} onClick={commit}>{t('windows.save')}</button>
        <button type="button" className="min-h-10 rounded border border-border px-3" disabled={!draft.length} onClick={() => setDraft(draft.slice(0, -1))}>{t('windows.undo')}</button>
        <button type="button" className="min-h-10 rounded border border-border px-3" disabled={!draft.length && editing === null} onClick={() => { setDraft([]); setEditing(null) }}>{t('windows.cancel')}</button>
      </div>
      {windows.map((_, i) => <div key={i} className="flex items-center gap-2 text-xs"><span>{t('windows.item', { number: i + 1 })}</span>
        <button type="button" className="min-h-9 rounded border border-border px-3" onClick={() => { setEditing(i); setDraft(windows[i].map(p => [...p])) }}>{t('windows.edit')}</button>
        <button type="button" className="min-h-9 rounded border border-border px-3" onClick={() => { onChange(parseImageWindows(windows.filter((_, j) => j !== i))); setDraft([]); setEditing(null) }}>{t('windows.remove')}</button>
      </div>)}
    </fieldset>
  </details>
}
