import { useUiTranslation } from '../../i18n'
import type { DirectorLightingContinuity, DirectorReferenceAnchorMode, ServicesConfig } from '../../types'

const SELECT_CLASS = 'w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue'

/** Settings › Services › Director: shared reference, light and clothes.
 *  Each is the default of a Director run; a request can still override it. */
export function DirectorReferenceSettings({ config, onChange }: {
  config: ServicesConfig
  onChange: (partial: Partial<ServicesConfig>) => void
}) {
  const { t } = useUiTranslation('settings')
  const keepWardrobe = config.director_keep_reference_wardrobe !== false
  return (
    <>
      <div>
        <label htmlFor="director-reference-anchor" className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {t('services.referenceAnchor')}
        </label>
        <select
          id="director-reference-anchor"
          value={config.director_reference_anchor || 'always'}
          onChange={event => onChange({ director_reference_anchor: event.target.value as DirectorReferenceAnchorMode })}
          className={SELECT_CLASS}
        >
          <option value="always">{t('services.referenceAnchorAlways')}</option>
          <option value="no_cast_refs">{t('services.referenceAnchorNoCast')}</option>
          <option value="off">{t('services.referenceAnchorOff')}</option>
        </select>
        <p className="text-[10px] text-text-muted mt-1">{t('services.referenceAnchorHint')}</p>
      </div>

      <div>
        <label htmlFor="director-lighting-continuity" className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {t('services.lightingContinuity')}
        </label>
        <select
          id="director-lighting-continuity"
          value={config.director_lighting_continuity || 'auto'}
          onChange={event => onChange({ director_lighting_continuity: event.target.value as DirectorLightingContinuity })}
          className={SELECT_CLASS}
        >
          <option value="auto">{t('services.lightingAuto')}</option>
          <option value="reference">{t('services.lightingReference')}</option>
          <option value="per_shot">{t('services.lightingPerShot')}</option>
        </select>
        <p className="text-[10px] text-text-muted mt-1">{t('services.lightingContinuityHint')}</p>
      </div>

      <label className="flex items-center justify-between cursor-pointer group">
        <div className="flex-1 mr-3 min-w-0">
          <div className="text-sm text-text-primary group-hover:text-accent-blue transition-colors">
            {t('services.keepWardrobe')}
          </div>
          <div className="text-[10px] text-text-muted mt-0.5">{t('services.keepWardrobeHint')}</div>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={keepWardrobe}
          aria-label={t('services.keepWardrobe')}
          onClick={() => onChange({ director_keep_reference_wardrobe: !keepWardrobe })}
          className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${
            keepWardrobe ? 'bg-accent-blue' : 'bg-bg-tertiary border border-border'
          }`}
        >
          <span className={`absolute top-0.5 left-0 w-4 h-4 rounded-full bg-white border border-border shadow transition-transform ${
            keepWardrobe ? 'translate-x-4' : 'translate-x-0.5'
          }`} />
        </button>
      </label>
    </>
  )
}
