import { useStore } from '../../stores/useStore'
import type { AspectRatio } from '../../types'

const standardRatios: { value: AspectRatio; icon: string }[] = [
  { value: '21:9', icon: '▭' },
  { value: '16:9', icon: '▬' },
  { value: '9:16', icon: '▮' },
  { value: '1:1', icon: '◼' },
  { value: '4:3', icon: '▭' },
  { value: '3:4', icon: '▯' },
]

/**
 * Studio aspect-ratio selector. Without props it edits Studio's own state;
 * other surfaces (Story Lab) pass `value`/`onChange` and the ratios they allow.
 */
export function AspectRatioGrid({ value, onChange, ratios: allowed, disabled = false }: {
  value?: AspectRatio
  onChange?: (ratio: AspectRatio) => void
  ratios?: AspectRatio[]
  disabled?: boolean
} = {}) {
  const storeAspect = useStore(s => s.aspectRatio)
  const setStoreAspect = useStore(s => s.setAspectRatio)
  const generationMode = useStore(s => s.generationMode)
  const modelOptions = useStore(s => s.modelOptions)
  const controlled = onChange !== undefined
  const aspectRatio = controlled ? value ?? '16:9' : storeAspect
  const setAspectRatio = controlled ? onChange : setStoreAspect
  const isImage = generationMode === 'image'

  const ratios = allowed?.length
    ? standardRatios.filter(r => allowed.includes(r.value))
    : isImage || modelOptions?.supports_auto_aspect
      ? [{ value: 'auto' as AspectRatio, icon: '⊞' }, ...standardRatios]
      : standardRatios

  return (
    <div>
      <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">Aspect Ratio</label>
      <div className="flex gap-1">
        {ratios.map(r => (
          <button
            key={r.value}
            type="button"
            disabled={disabled}
            aria-pressed={aspectRatio === r.value}
            onClick={() => setAspectRatio(r.value)}
            className={`flex-1 flex flex-col items-center gap-0.5 py-2 rounded-lg border text-[10px] transition-all disabled:opacity-50 ${
              aspectRatio === r.value
                ? 'border-accent-blue bg-bg-active text-text-primary'
                : 'border-border text-text-muted hover:border-border-light hover:text-text-secondary'
            }`}
          >
            <span className="text-sm leading-none">{r.icon}</span>
            <span>{r.value === 'auto' ? 'Auto' : r.value}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
