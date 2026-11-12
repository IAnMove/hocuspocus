import { Maximize2, MousePointer2, Move3D, Rotate3D } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { TransformMode } from './transformGizmo'

const modes = [
  { id: 'select', Icon: MousePointer2 },
  { id: 'translate', Icon: Move3D },
  { id: 'rotate', Icon: Rotate3D },
  { id: 'scale', Icon: Maximize2 },
] as const

/** Select, move, rotate and scale. One set, drawn on the viewport. */
export function Scene3DViewportTools({ mode, disabled, onMode, caption, captionNote }: {
  mode: TransformMode
  disabled: boolean
  onMode: (mode: TransformMode) => void
  caption?: string
  captionNote?: string
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return (
    <div
      data-testid="scene3d-viewport-tools"
      role="toolbar"
      aria-label={t('desk.tools')}
      className="pointer-events-none absolute left-1/2 top-2 z-10 flex max-w-[calc(100%-1rem)] -translate-x-1/2 flex-col items-center gap-0.5 rounded-lg border border-cyan-300/40 bg-black/80 p-1"
    >
      {caption && <p className="max-w-full truncate px-2 text-center text-[10px] leading-4 text-cyan-200" title={captionNote || caption}>{caption}{captionNote && <span className="mt-0.5 block truncate text-amber-100/90">{captionNote}</span>}</p>}
      <div className="flex gap-1">
      {modes.map(({ id, Icon }) => (
        <button
          key={id}
          type="button"
          disabled={disabled}
          aria-pressed={mode === id}
          data-testid={`scene3d-tool-${id}`}
          onClick={() => onMode(id)}
          className={`pointer-events-auto inline-flex min-h-10 items-center gap-1 rounded-md px-2 text-xs font-semibold disabled:opacity-40 ${mode === id ? 'bg-cyan-300 text-slate-950' : 'text-cyan-50'}`}
        >
          <Icon size={15} />{id === 'select' ? t('desk.select') : t(id)}
        </button>
      ))}
      </div>
    </div>
  )
}
