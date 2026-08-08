import { useStore } from '../../stores/useStore'
import { ChoiceControl } from '../shared/ChoiceControl'

export function ModelOptionsPanel() {
  const modelOptions = useStore(s => s.modelOptions)
  const params = useStore(s => s.params)
  const setParam = useStore(s => s.setParam)

  if (!modelOptions) return null

  const {
    sample_solvers,
    flow_shift,
    guidance_max_phases,
    lock_guidance_phases,
    self_refiner,
  } = modelOptions

  const hasAnyOption = sample_solvers ||
    flow_shift || (guidance_max_phases > 1 && !lock_guidance_phases) || self_refiner

  if (!hasAnyOption) return null

  return (
    <div className="space-y-4">
      {/* Sampler / Solver */}
      {sample_solvers && sample_solvers.length > 0 && (
        <ChoiceControl
          config={{ choices: sample_solvers, label: 'Sampler' }}
          value={params.video_prompt_type || sample_solvers[0]?.[1] || ''}
          onChange={val => setParam('video_prompt_type', val)}
          label="Sampler"
        />
      )}

      {/* Guidance Phases */}
      {guidance_max_phases > 1 && !lock_guidance_phases && (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
            Guidance Phases
          </label>
          <select
            value={params.guidance_phases ?? 1}
            onChange={e => setParam('guidance_phases', Number(e.target.value))}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            {Array.from({ length: guidance_max_phases }, (_, i) => i + 1).map(n => (
              <option key={n} value={n}>
                {n === 1 ? 'One Phase' : n === 2 ? 'Two Phases' : 'Three Phases'}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Flow Shift */}
      {flow_shift && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{modelOptions.architecture === 'minimax_h3' ? 'Video Sigma Shift' : 'Flow Shift'}</label>
            <input
              type="number"
              value={params.flow_shift ?? 3.0}
              onChange={e => setParam('flow_shift', Number(e.target.value))}
              step={0.5}
              className="w-14 bg-bg-tertiary border border-border rounded px-2 py-0.5 text-xs text-text-primary text-center focus:outline-none"
            />
          </div>
          <input
            type="range"
            min={0}
            max={20}
            step={0.5}
            value={params.flow_shift ?? 3.0}
            onChange={e => setParam('flow_shift', Number(e.target.value))}
          />
        </div>
      )}

      {modelOptions.architecture === 'minimax_h3' && (
        <div className="space-y-4">
          <div>
            <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">Conditioning Mode</label>
            <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-bg-tertiary p-1">
              <button type="button" onClick={() => setParam('h3_reference_mode', 'first_frame')}
                className={`rounded-md px-2 py-1.5 text-[11px] transition-colors ${(params.h3_reference_mode ?? 'first_frame') === 'first_frame' ? 'bg-accent-blue text-white' : 'text-text-secondary hover:bg-bg-hover'}`}>
                Exact frame · FL2VA
              </button>
              <button type="button" onClick={() => setParam('h3_reference_mode', 'references')}
                className={`rounded-md px-2 py-1.5 text-[11px] transition-colors ${params.h3_reference_mode === 'references' ? 'bg-cyan-600 text-white' : 'text-text-secondary hover:bg-bg-hover'}`}>
                References · Ref2VA
              </button>
            </div>
            <p className="text-[10px] text-text-muted mt-1">
              FL2VA preserves the supplied first frame. Ref2VA composes a new shot from image/video/audio references and cannot guarantee an exact opening frame.
            </p>
          </div>
          <div>
            <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">4090 Model Profile</label>
            <select
              value={params.h3_model_profile ?? 'quality'}
              onChange={e => setParam('h3_model_profile', e.target.value as 'balanced' | 'quality' | 'low_memory')}
              className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
            >
              <option value="quality">Quality 4090 · INT8 (recommended)</option>
              <option value="balanced">Legacy Balanced · INT8</option>
              <option value="low_memory">Low VRAM fallback · INT4</option>
            </select>
            <p className="text-[10px] text-text-muted mt-1">INT4 is retried automatically only if INT8 runs out of VRAM. The selected FL2VA or Ref2VA checkpoint downloads on first use.</p>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] text-text-muted uppercase tracking-wider">Audio Sigma Shift</label>
              <input type="number" value={params.h3_audio_shift ?? 3.0}
                onChange={e => setParam('h3_audio_shift', Number(e.target.value))} step={0.1}
                className="w-14 bg-bg-tertiary border border-border rounded px-2 py-0.5 text-xs text-text-primary text-center focus:outline-none" />
            </div>
            <input type="range" min={0.1} max={20} step={0.1} value={params.h3_audio_shift ?? 3.0}
              onChange={e => setParam('h3_audio_shift', Number(e.target.value))} />
            <p className="text-[10px] text-text-muted mt-1">Official default: video 12, audio 3.</p>
          </div>
          <div>
            <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">Audio Direction</label>
            <textarea
              rows={3}
              value={params.h3_audio_prompt ?? ''}
              onChange={e => setParam('h3_audio_prompt', e.target.value)}
              placeholder="Ambience, dialogue, music and sound effects for the clip"
              className="w-full resize-y bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:border-accent-blue"
            />
            <p className="text-[10px] text-text-muted mt-1">Appended as <code>Audio:</code> when the main prompt has no audio clause. Director adds each shot's planned ambience, effects and dialogue automatically.</p>
          </div>
        </div>
      )}

      {/* Self Refiner */}
      {self_refiner && (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
            Self Refiner
          </label>
          <select
            value={params.self_refiner_setting ?? 0}
            onChange={e => setParam('self_refiner_setting', Number(e.target.value))}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            <option value={0}>Disabled</option>
            <option value={1}>Enabled with P1-Norm</option>
            <option value={2}>Enabled with P2-Norm</option>
          </select>
        </div>
      )}
    </div>
  )
}
