import { useUiTranslation } from '../../i18n'
import { input, panel, Field } from './storyLabChrome'
import { storyAssetKey, type PendingSmartAsset } from './storyLabAssets'
import type { StoryAssetKind, StoryProject } from './types'

export function StoryAssetsProposalCard({
  item, index, project, onPatch,
}: {
  item: PendingSmartAsset
  index: number
  project: StoryProject
  onPatch: (index: number, patch: Partial<PendingSmartAsset>) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const newKey = storyAssetKey(`${item.name}-${index}`)
  const targetOptions = item.kind === 'character'
    ? [
      ...project.characters.map(character => ({ id: character.id, label: t('assets.existingNamed', { name: character.name }) })),
      { id: item.targetId.startsWith('new-character:') ? item.targetId : `new-character:${newKey}`, label: t('assets.newCharacter', { name: item.name }) },
    ]
    : item.kind === 'location'
      ? [
        ...project.world.locations.map(location => ({ id: location.id, label: t('assets.existingNamed', { name: location.name }) })),
        { id: item.targetId.startsWith('new-location:') ? item.targetId : `new-location:${newKey}`, label: t('assets.newLocation', { name: item.name }) },
      ]
      : [{
        id: 'world',
        label: item.kind === 'prop' ? t('assets.worldProp') : item.kind === 'style' ? t('assets.worldStyle') : t('assets.worldRefs'),
      }]
  return (
    <article className={`${panel} ${item.selected ? '' : 'opacity-60'}`}>
      <div className="grid gap-3 lg:grid-cols-[140px_minmax(0,1fr)_minmax(260px,0.7fr)]">
        <div>
          <img src={item.source} alt={item.name} className="h-32 w-full rounded-lg border border-border object-cover" />
          <label className="mt-2 flex items-center gap-2 text-[10px] text-text-secondary">
            <input type="checkbox" checked={item.selected}
              onChange={event => onPatch(index, { selected: event.target.checked })} />
            {t('assets.importThis')}
          </label>
          <p className="mt-1 truncate text-[9px] text-text-muted" title={item.nameOriginal}>{item.nameOriginal}</p>
        </div>
        <div className="space-y-3">
          <Field label={t('assets.editableName')} value={item.name}
            onChange={name => onPatch(index, { name })} />
          <Field label={t('assets.contains')} value={item.description}
            onChange={description => onPatch(index, { description })} rows={3} />
          <Field label={t('assets.visualPrompt')} value={item.visualPrompt}
            onChange={visualPrompt => onPatch(index, { visualPrompt })} rows={3} />
        </div>
        <div className="space-y-3">
          <label className="block text-[10px] text-text-muted">{t('assets.assetType')}
            <select className={`${input} mt-1`} value={item.kind} onChange={event => {
              const kind = event.target.value as StoryAssetKind
              const targetId = kind === 'character'
                ? (project.characters[0]?.id || `new-character:${newKey}`)
                : kind === 'location'
                  ? (project.world.locations[0]?.id || `new-location:${newKey}`)
                  : 'world'
              onPatch(index, { kind, targetId, selected: kind !== 'ignore' })
            }}>
              <option value="character">{t('assets.typeCharacter')}</option>
              <option value="location">{t('assets.typeLocation')}</option>
              <option value="world">{t('assets.typeWorld')}</option>
              <option value="prop">{t('assets.typeProp')}</option>
              <option value="style">{t('assets.typeStyle')}</option>
              <option value="ignore">{t('assets.typeIgnore')}</option>
            </select>
          </label>
          {item.kind !== 'ignore' && (
            <label className="block text-[10px] text-text-muted">{t('assets.destination')}
              <select className={`${input} mt-1`} value={targetOptions.some(option => option.id === item.targetId) ? item.targetId : targetOptions[0]?.id}
                onChange={event => onPatch(index, { targetId: event.target.value })}>
                {targetOptions.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
            </label>
          )}
          <div className="rounded-md border border-border bg-bg-tertiary/60 p-2 text-[9px] text-text-muted">
            <p>{t('assets.confidence', { percent: Math.round(item.confidence * 100) })}</p>
            <p className="mt-1">{item.reason}</p>
          </div>
        </div>
      </div>
    </article>
  )
}
