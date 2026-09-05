import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { ChoiceControl } from '../shared/ChoiceControl'

export function ModelOptionsPanel() {
  const { t } = useUiTranslation('settings')
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
          config={{ choices: sample_solvers, label: t('modelOptions.sampler') }}
          value={params.video_prompt_type || sample_solvers[0]?.[1] || ''}
          onChange={val => setParam('video_prompt_type', val)}
          label={t('modelOptions.sampler')}
        />
      )}

      {/* Guidance Phases */}
      {guidance_max_phases > 1 && !lock_guidance_phases && (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
            {t('modelOptions.guidancePhases')}
          </label>
          <select
            value={params.guidance_phases ?? 1}
            onChange={e => setParam('guidance_phases', Number(e.target.value))}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            {Array.from({ length: guidance_max_phases }, (_, i) => i + 1).map(n => (
              <option key={n} value={n}>
                {n === 1 ? t('modelOptions.onePhase') : n === 2 ? t('modelOptions.twoPhases') : t('modelOptions.threePhases')}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Flow Shift */}
      {flow_shift && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{modelOptions.architecture === 'minimax_h3' ? t('modelOptions.videoSigmaShift') : t('modelOptions.flowShift')}</label>
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
            <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('modelOptions.conditioningMode')}</label>
            <div className="grid grid-cols-2 gap-1 rounded-lg border border-border bg-bg-tertiary p-1">
              <button type="button" onClick={() => setParam('h3_reference_mode', 'first_frame')}
                className={`rounded-md px-2 py-1.5 text-[11px] transition-colors ${(params.h3_reference_mode ?? 'first_frame') === 'first_frame' ? 'bg-accent-blue text-white' : 'text-text-secondary hover:bg-bg-hover'}`}>
                {t('modelOptions.exactFrame')}
              </button>
              <button type="button" onClick={() => setParam('h3_reference_mode', 'references')}
                className={`rounded-md px-2 py-1.5 text-[11px] transition-colors ${params.h3_reference_mode === 'references' ? 'bg-cyan-600 text-white' : 'text-text-secondary hover:bg-bg-hover'}`}>
                {t('modelOptions.references')}
              </button>
            </div>
            <p className="text-[10px] text-text-muted mt-1">
              {t('modelOptions.conditioningHint')}
            </p>
          </div>
          <div>
            <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('modelOptions.profile4090')}</label>
            <select
              value={params.h3_model_profile ?? 'quality'}
              onChange={e => setParam('h3_model_profile', e.target.value as 'balanced' | 'quality' | 'low_memory')}
              className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
            >
              <option value="quality">{t('modelOptions.quality4090')}</option>
              <option value="balanced">{t('modelOptions.legacyBalanced')}</option>
              <option value="low_memory">{t('modelOptions.lowVram')}</option>
            </select>
            <p className="text-[10px] text-text-muted mt-1">{t('modelOptions.profileHint')}</p>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('modelOptions.audioSigmaShift')}</label>
              <input type="number" value={params.h3_audio_shift ?? 3.0}
                onChange={e => setParam('h3_audio_shift', Number(e.target.value))} step={0.1}
                className="w-14 bg-bg-tertiary border border-border rounded px-2 py-0.5 text-xs text-text-primary text-center focus:outline-none" />
            </div>
            <input type="range" min={0.1} max={20} step={0.1} value={params.h3_audio_shift ?? 3.0}
              onChange={e => setParam('h3_audio_shift', Number(e.target.value))} />
            <p className="text-[10px] text-text-muted mt-1">{t('modelOptions.officialDefault')}</p>
          </div>
          <div>
            <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">{t('modelOptions.audioDirection')}</label>
            <textarea
              rows={3}
              value={params.h3_audio_prompt ?? ''}
              onChange={e => setParam('h3_audio_prompt', e.target.value)}
              placeholder={t('modelOptions.audioPlaceholder')}
              className="w-full resize-y bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-xs text-text-primary placeholder:text-text-muted/50 focus:outline-none focus:border-accent-blue"
            />
            <p className="text-[10px] text-text-muted mt-1">{t('modelOptions.audioHint')}</p>
          </div>
        </div>
      )}

      {/* Self Refiner */}
      {self_refiner && (
        <div>
          <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
            {t('modelOptions.selfRefiner')}
          </label>
          <select
            value={params.self_refiner_setting ?? 0}
            onChange={e => setParam('self_refiner_setting', Number(e.target.value))}
            className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
          >
            <option value={0}>{t('modelOptions.disabled')}</option>
            <option value={1}>{t('modelOptions.p1')}</option>
            <option value={2}>{t('modelOptions.p2')}</option>
          </select>
        </div>
      )}
    </div>
  )
}
