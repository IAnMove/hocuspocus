import { useUiTranslation } from '../../i18n'
import { h3CatalogEntry } from '../../lib/h3Catalog'
import { resolveModelCatalog, type ModelCatalogInput } from '../../lib/modelCatalog'
import { H3ModelInfo } from './H3ModelInfo'

export function ModelCatalogInfo({ model }: { model: ModelCatalogInput }) {
  const { t } = useUiTranslation('studio')
  if (h3CatalogEntry(model.model_type)) {
    return <H3ModelInfo modelType={model.model_type} />
  }
  const entry = resolveModelCatalog(model)
  const { requirements } = entry
  return (
    <div className="mt-1 ml-6 mb-2 text-[11px] text-text-muted leading-snug">
      <p>{t(`modelCatalog.${entry.variant}Hint`)}</p>
      <p>{t(`modelCatalog.capability.${entry.capability}`)}</p>
      <details className="mt-1">
        <summary className="cursor-pointer">{t('modelCatalog.requirements')}</summary>
        {requirements.vram_gb != null && (
          <p>{t('modelCatalog.vram', { vram: requirements.vram_gb })}</p>
        )}
        {requirements.comfortable_vram_gb != null
          && requirements.comfortable_vram_gb !== requirements.vram_gb && (
          <p>{t('modelCatalog.vramComfort', { vram: requirements.comfortable_vram_gb })}</p>
        )}
        {requirements.ram_gb != null && (
          <p>{t('modelCatalog.ram', { ram: requirements.ram_gb })}</p>
        )}
        {requirements.storage_gb != null && (
          <p>{t('modelCatalog.storage', { storage: requirements.storage_gb })}</p>
        )}
        <p>{t('modelCatalog.limit')}</p>
      </details>
    </div>
  )
}
