import { useUiTranslation } from '../../i18n'
import type { SeriesShot } from './types'
import type { seriesShotReferences, SeriesReferenceRoom } from './shotReferences'
import { seriesAssetUrl } from './referenceImages'
import { secondaryButton, selectClass } from './styles'

type ReferenceProps = {
  references: ReturnType<typeof seriesShotReferences>
  shot: SeriesShot
  busy: boolean
  onChange: (shot: SeriesShot) => void
}

function SeriesShotLocationFields({ references, shot, busy, onChange }: ReferenceProps) {
  const { t } = useUiTranslation('seriesLab')
  return <>
<label className="block text-xs text-text-secondary">{t('production.assets.location')}
          <select className={`${selectClass} mt-1`} value={shot.locationId || ''} disabled={busy}
            onChange={event => onChange({ ...shot, locationId: event.target.value, locationVariantId: '', referenceManifest: undefined })}>
            <option value="">{t('production.assets.chooseLocation')}</option>
            {shot.locationId && !references.location && <option value={shot.locationId}>{shot.locationId}</option>}
            {references.locations.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}
          </select>
        </label>
        {Boolean(references.location?.variants.length) && <label className="block text-xs text-text-secondary">{t('production.assets.locationVariant')}
          <select className={`${selectClass} mt-1`} value={shot.locationVariantId || ''} disabled={busy}
            onChange={event => onChange({ ...shot, locationVariantId: event.target.value, referenceManifest: undefined })}>
            <option value="">{t('production.assets.baseLocation')}</option>
            {references.location!.variants.map(variant => <option key={variant.id} value={variant.id}>{variant.label}</option>)}
          </select>
        </label>}
  </>
}

export function SeriesShotReferencePanel({ references, shot, busy, onChange, onOpenReferences, onOpenEpisode }: ReferenceProps & {
  onOpenReferences?: (room: SeriesReferenceRoom) => void
  onOpenEpisode?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  return <fieldset className="space-y-3 rounded-lg border border-border p-3">
        <legend className="px-1 text-xs font-semibold text-text-primary">{t('production.assets.title')}</legend>
        <SeriesShotLocationFields references={references} shot={shot} busy={busy} onChange={onChange} />
        <ul className="space-y-2 text-xs">{[
          { id: 'location', name: `${t('production.assets.location')}: ${references.location?.name || t('production.assets.chooseLocation')}`, asset: references.background, state: references.locationState },
          ...references.people,
        ].map(item => <li key={item.id} className="flex items-center gap-2">
          {item.asset && <img className="h-12 w-16 shrink-0 rounded border border-border object-contain" src={seriesAssetUrl(item.asset)} alt={item.name} />}
          <div className="min-w-0"><p className="break-words text-text-primary">{item.name}</p><p className={item.state === 'ready' ? 'text-emerald-300' : 'text-amber-300'}>{t(`production.assets.states.${item.state}`)}</p></div>
        </li>)}</ul>
        {!references.people.length && <p className="text-xs text-text-muted">{t('production.assets.emptyCast')}</p>}
        {!references.ready && <p role="status" className="text-xs text-amber-200">{t('production.assets.completeFirst')}</p>}
        <div className="flex flex-wrap gap-2">
          {onOpenReferences && <><button type="button" className={secondaryButton} disabled={busy} onClick={() => onOpenReferences('locations')}>{t('production.assets.prepareLocations')}</button>
            <button type="button" className={secondaryButton} disabled={busy} onClick={() => onOpenReferences('characters')}>{t('production.assets.prepareCharacters')}</button></>}
          {onOpenEpisode && <button type="button" className={secondaryButton} disabled={busy} onClick={onOpenEpisode}>{t('production.assets.updateEpisode')}</button>}
        </div>
      </fieldset>
}
