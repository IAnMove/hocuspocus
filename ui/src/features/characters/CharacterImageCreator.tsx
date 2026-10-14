import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { CharacterKitAsset } from '../../lib/characterKit'
import { characterImageModels, preferredCharacterImageModel } from '../../lib/characterImageModels'
import { characterStyle, characterStyleLabel, characterStyles, characterStyleSummary } from '../../lib/characterStyles'
import { useCreatorSession } from './characterCreatorSession'
import { CharacterFreeCreator } from './CharacterFreeCreator'
import { CharacterStyleCreator } from './CharacterStyleCreator'

const control = 'min-h-10 rounded-lg border border-border bg-bg-primary px-3 text-sm disabled:opacity-40'

/** The pictures a run draws are workspace outputs: the gallery reads them again. */
const loadPictures = () => { void useStore.getState().loadOutputs().catch(() => {}) }

/** Generate an identity first; saving it makes it available to Lips Creator. The style, model and what was typed belong to the
 * workspace's creator session, so they are still there when the tab is left and reopened. */
export function CharacterImageCreator({ workspace, disabled, onUseReference }: {
  workspace: string; disabled?: boolean
  onUseReference: (asset: CharacterKitAsset, description: string, signal: AbortSignal) => Promise<void>
}) {
  const { t, i18n } = useUiTranslation('characters')
  const models = useStore(state => state.models)
  const { session, view } = useCreatorSession(workspace)
  const style = characterStyle(view.styleId)
  const imageModels = characterImageModels(models, false)
  const imageModel = imageModels.some(item => item.model_type === view.model) ? view.model : preferredCharacterImageModel(imageModels, false)
  const modelPicker = (blocked: boolean) => <label className="block max-w-md text-xs text-text-secondary">{t('lips.imageModel')}
    <select value={imageModel} disabled={blocked} onChange={event => session.edit({ model: event.target.value })} className={`${control} mt-1 w-full`}>
      {!imageModels.length && <option value="">{t('lips.noImageModel')}</option>}{imageModels.map(item => <option key={item.model_type} value={item.model_type}>{item.name}</option>)}
    </select></label>
  return <section data-testid="character-image-creator" className="mx-auto mb-5 max-w-5xl space-y-4 rounded-xl border border-cyan-400/30 bg-bg-secondary p-4">
    <div><h3 className="text-base font-semibold">{t('imageCreator.title')}</h3><p className="mt-1 text-sm text-text-muted">{t(style ? 'styleCreator.hint' : 'imageCreator.hint')}</p></div>
    <label className="block max-w-md text-xs text-text-secondary">{t('styleCreator.style')}
      <select value={view.styleId} disabled={Boolean(view.busy) || disabled} onChange={event => session.setStyle(event.target.value)} className={`${control} mt-1 w-full`} data-testid="character-style">
        <option value="">{t('styleCreator.free')}</option>
        {characterStyles.map(item => <option key={item.id} value={item.id}>{characterStyleLabel(item, i18n.language)}</option>)}
      </select>
      {style && <span className="mt-1 block text-text-muted">{characterStyleSummary(style, i18n.language)}</span>}
    </label>
    {style ? <>
      {modelPicker(Boolean(disabled))}
      <CharacterStyleCreator workspace={workspace} style={style} model={imageModel} disabled={disabled} />
    </> : <CharacterFreeCreator workspace={workspace} model={imageModel} modelPicker={modelPicker} disabled={disabled} onPictures={loadPictures}
      onCreateMouths={() => useStore.getState().setMediaFilter('lips')} onUseReference={onUseReference} />}
  </section>
}
