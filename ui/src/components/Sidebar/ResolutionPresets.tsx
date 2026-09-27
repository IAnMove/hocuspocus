import { useStore } from '../../stores/useStore'
import type { ModelOptions, ResolutionPreset } from '../../types'

/**
 * Studio resolution selector. Without props it edits Studio's own state;
 * other surfaces (Story Lab) pass `value`/`onChange` and their model options.
 */
export function ResolutionPresets({ value, onChange, options, presets: allowed, disabled = false }: {
  value?: ResolutionPreset
  onChange?: (preset: ResolutionPreset) => void
  options?: ModelOptions | null
  /** Restrict the buttons to these presets (controlled use only). */
  presets?: ResolutionPreset[]
  disabled?: boolean
} = {}) {
  const storeResolution = useStore(s => s.resolutionPreset)
  const setStoreResolution = useStore(s => s.setResolutionPreset)
  const generationMode = useStore(s => s.generationMode)
  const storeOptions = useStore(s => s.modelOptions)
  const controlled = onChange !== undefined
  const resolutionPreset = controlled ? value ?? '540p' : storeResolution
  const setResolutionPreset = controlled ? onChange : setStoreResolution
  const modelOptions = controlled ? options ?? null : storeOptions
  const isEdit = !controlled && generationMode === 'avatar'

  const isImage = !controlled && generationMode === 'image'
  // Model-specific lists take precedence so a family can label its native
  // tier and clearly identify higher-cost experimental canvases.
  const presets: ResolutionPreset[] = allowed?.length
    ? allowed
    : modelOptions?.resolution_preset_order?.length
      ? modelOptions.resolution_preset_order
      : (isEdit || isImage)
        ? ['auto', '480p', '540p', '720p', '1080p']
        : ['480p', '540p', '720p', '1080p']
  const selectedModelPreset = modelOptions?.resolution_presets?.[resolutionPreset]

  return (
    <div>
      <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">Resolution</label>
      <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
        {presets.map(p => (
          <button
            key={p}
            type="button"
            disabled={disabled}
            aria-pressed={resolutionPreset === p}
            onClick={() => setResolutionPreset(p)}
            className={`flex-1 text-xs py-1.5 rounded-md transition-all capitalize disabled:opacity-50 ${
              resolutionPreset === p
                ? 'bg-bg-active text-text-primary'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {p === 'auto'
              ? 'Auto'
              : modelOptions?.resolution_presets?.[p]?.label || p}
          </button>
        ))}
      </div>
      {resolutionPreset === 'auto' && (
        <p className="text-[9px] text-text-muted mt-0.5">
          {isEdit ? 'Uses source clip resolution' : isImage ? 'Matches reference image aspect ratio' : 'Auto resolution'}
        </p>
      )}
      {selectedModelPreset?.hint && (
        <p className={`mt-1 text-[9px] leading-relaxed ${
          selectedModelPreset.experimental ? 'text-indicator-warning' : 'text-text-muted'
        }`}>
          {selectedModelPreset.hint}
        </p>
      )}
    </div>
  )
}
