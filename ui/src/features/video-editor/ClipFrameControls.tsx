import type { PointerEvent as ReactPointerEvent } from 'react'
import { useUiTranslation } from '../../i18n'
import { focusPercent } from './clipFrame'
import type { ClipFit, EditorClip } from './editorClipNormalization'

const FIT_MODES: { value: ClipFit; labelKey: 'inspector.fit' | 'inspector.fill' | 'inspector.blur' }[] = [
  { value: 'fit', labelKey: 'inspector.fit' },
  { value: 'fill', labelKey: 'inspector.fill' },
  { value: 'blur', labelKey: 'inspector.blur' },
]

export function BlurFillBackdrop({ fit, src }: { fit: ClipFit; src: string }) {
  if (fit !== 'blur' || !src) return null
  return (
    <img
      src={src}
      alt=""
      aria-hidden
      className="pointer-events-none absolute inset-0 h-full w-full scale-110 object-cover blur-2xl brightness-75"
    />
  )
}

function placeFocus(event: ReactPointerEvent<HTMLDivElement>, onChange: (patch: Partial<EditorClip>) => void) {
  const rect = event.currentTarget.getBoundingClientRect()
  onChange({
    focusX: focusPercent(event.clientX, rect.left, rect.width),
    focusY: focusPercent(event.clientY, rect.top, rect.height),
  })
}

function FocusPad({ clip, onChange }: { clip: EditorClip; onChange: (patch: Partial<EditorClip>) => void }) {
  const { t } = useUiTranslation('videoEditor')
  const focusX = clip.focusX ?? 50
  const focusY = clip.focusY ?? 50
  return (
    <div>
      <p className="mb-1 text-[10px] text-text-muted">{t('inspector.focusHint')}</p>
      <div
        role="application"
        aria-label={t('inspector.focus')}
        className="relative h-24 cursor-crosshair overflow-hidden rounded border border-border bg-black"
        onPointerDown={event => {
          event.currentTarget.setPointerCapture(event.pointerId)
          placeFocus(event, onChange)
        }}
        onPointerMove={event => {
          if (event.currentTarget.hasPointerCapture(event.pointerId)) placeFocus(event, onChange)
        }}
      >
        <img
          src={clip.thumbnailUrl}
          alt=""
          draggable={false}
          className="h-full w-full object-cover"
          style={{ objectPosition: `${focusX}% ${focusY}%` }}
        />
        <span
          className="pointer-events-none absolute h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-accent-blue/80"
          style={{ left: `${focusX}%`, top: `${focusY}%` }}
        />
      </div>
    </div>
  )
}

function BlurSliders({ clip, onChange }: { clip: EditorClip; onChange: (patch: Partial<EditorClip>) => void }) {
  const { t } = useUiTranslation('videoEditor')
  const blurAmount = clip.blurAmount ?? 0.65
  const backgroundDim = clip.backgroundDim ?? 0.4
  return (
    <div className="space-y-2">
      <label className="block text-[10px] text-text-muted">
        {t('inspector.blurAmount')}
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={blurAmount}
          aria-label={t('inspector.blurAmount')}
          onChange={event => onChange({ blurAmount: Number(event.target.value) })}
          className="mt-1 block w-full"
        />
      </label>
      <label className="block text-[10px] text-text-muted">
        {t('inspector.backgroundDim')}
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={backgroundDim}
          aria-label={t('inspector.backgroundDim')}
          onChange={event => onChange({ backgroundDim: Number(event.target.value) })}
          className="mt-1 block w-full"
        />
      </label>
    </div>
  )
}

export function ClipFrameControls({
  clip,
  onChange,
}: {
  clip: EditorClip
  onChange: (patch: Partial<EditorClip>) => void
}) {
  const { t } = useUiTranslation('videoEditor')
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-3 gap-1.5" role="group" aria-label={t('inspector.frame')}>
        {FIT_MODES.map(mode => (
          <button
            key={mode.value}
            type="button"
            aria-pressed={clip.fit === mode.value}
            onClick={() => onChange({ fit: mode.value })}
            className={`rounded border px-1 py-1.5 text-[10px] leading-tight ${
              clip.fit === mode.value
                ? 'border-accent-blue bg-accent-blue/10 text-accent-blue'
                : 'border-border text-text-muted hover:text-text-secondary'
            }`}
          >
            {t(mode.labelKey)}
          </button>
        ))}
      </div>
      {clip.fit === 'fill' && <FocusPad clip={clip} onChange={onChange} />}
      {clip.fit === 'blur' && <BlurSliders clip={clip} onChange={onChange} />}
    </div>
  )
}
