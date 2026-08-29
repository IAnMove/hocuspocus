import { Zap } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { InfoTooltip } from './InfoTooltip'

/** Experimental FastVideo FastH3 Preview v1: 4-step T2VA. */
export function MiniMaxH3FastH3Toggle() {
  const option = useStore(s => s.modelOptions?.minimax_h3_fasth3)
  const turboOption = useStore(s => s.modelOptions?.minimax_h3_turbo)
  const enabled = useStore(s => s.params.minimax_h3_fasth3_mode === true)
  const turboEnabled = useStore(s => s.params.minimax_h3_turbo_mode === true)
  const currentSteps = useStore(s => s.params.num_inference_steps)
  const defaultSteps = useStore(s => s.modelOptions?.default_num_inference_steps)
  const activatedLoras = useStore(s => s.params.activated_loras)
  const setParam = useStore(s => s.setParam)
  const toggleLora = useStore(s => s.toggleLora)
  const setLoraWeight = useStore(s => s.setLoraWeight)

  if (!option) return null

  const handleChange = (checked: boolean) => {
    setParam('minimax_h3_fasth3_mode', checked)
    if (checked) {
      if (turboEnabled && turboOption) {
        setParam('minimax_h3_turbo_mode', false)
        if (activatedLoras.includes(turboOption.filename)) toggleLora(turboOption.filename)
      }
      if (!useStore.getState().params.activated_loras.includes(option.filename)) {
        toggleLora(option.filename)
      }
      setLoraWeight(option.filename, 0, option.weight)
      setParam('num_inference_steps', option.steps)
      setParam('image_prompt_type', '')
    } else {
      if (useStore.getState().params.activated_loras.includes(option.filename)) {
        toggleLora(option.filename)
      }
      if (currentSteps === option.steps && defaultSteps != null) {
        setParam('num_inference_steps', defaultSteps)
      }
    }
  }

  return (
    <div className={`rounded-lg border px-3 py-2 transition-colors ${
      enabled
        ? 'border-amber-500/50 bg-amber-500/10'
        : 'border-border bg-bg-tertiary/50'
    }`}>
      <div className="flex items-center gap-2">
        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 select-none">
          <input
            type="checkbox"
            checked={enabled}
            onChange={event => handleChange(event.target.checked)}
            className="accent-amber-500"
          />
          <Zap size={13} className={enabled ? 'text-indicator-warning' : 'text-text-muted'} />
          <span className="text-[11px] font-medium text-text-primary">
            {option.label}
          </span>
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[8px] font-medium uppercase tracking-wider text-indicator-warning">
            Experimental
          </span>
        </label>
        <InfoTooltip label="About FastH3 Preview" text={option.guide} />
      </div>
      {enabled && (
        <p className="mt-1.5 text-[9px] leading-relaxed text-indicator-warning">
          4-step T2VA trial from FastVideo. Text only — no start/end frame, no Omni Ref. FastVideo trained this for VSA-H3 sparse attention; Maestro still uses dense attention, so quality is unproven.
        </p>
      )}
    </div>
  )
}
