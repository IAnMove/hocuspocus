import { Check, Trash2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, input, panel } from './storyLabChrome'
import type { StoryProject, StoryVisualAsset } from './types'

export function StoryAssetsLibrary({
  project, styleAssetIds, setStyleAssetIds, selectedDraftAssetIds, styleConversionBusy,
  deleteSelectedDraftAssets, toggleStyleAsset, patchVisualAsset, visualAssetsNewestFirst,
}: {
  project: StoryProject
  styleAssetIds: string[]
  setStyleAssetIds: (ids: string[]) => void
  selectedDraftAssetIds: string[]
  styleConversionBusy: boolean
  deleteSelectedDraftAssets: () => void
  toggleStyleAsset: (id: string) => void
  patchVisualAsset: (id: string, patch: Partial<StoryVisualAsset>) => void
  visualAssetsNewestFirst: StoryVisualAsset[]
}) {
  const { t } = useUiTranslation('storyLab')
  const assetIds = Object.keys(project.assets)
  const approvedCount = Object.values(project.assets).filter(asset => asset.approval === 'approved').length
  const allSelected = styleAssetIds.length === assetIds.length
  return (
    <section>
      <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{t('assets.libraryTitle', { count: assetIds.length })}</h3>
          <p className="mt-0.5 text-[9px] text-text-muted">
            {t('assets.libraryHint', { approved: approvedCount })}
          </p>
        </div>
        {assetIds.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <button
              className={button}
              onClick={() => setStyleAssetIds(allSelected ? [] : assetIds)}
            >
              {allSelected ? t('assets.clearSelection') : t('assets.selectAll')}
            </button>
            <button
              className={`${button} border-red-500/60 text-red-300`}
              disabled={!selectedDraftAssetIds.length || styleConversionBusy}
              onClick={deleteSelectedDraftAssets}
              title={t('assets.deleteDraftsTitle')}
            >
              <Trash2 size={13} /> {t('assets.deleteDrafts', { count: selectedDraftAssetIds.length })}
            </button>
          </div>
        )}
      </div>
      {assetIds.length ? (
        <div className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3">
          {visualAssetsNewestFirst.map(asset => (
            <div key={asset.id} className={`${panel} p-2.5 ${asset.approval === 'approved' ? 'border-emerald-500/40' : ''}`}>
              <div className="relative">
                <img src={asset.source} alt={asset.name} className="h-44 w-full rounded-md border border-border object-cover" />
                <label className="absolute left-2 top-2 flex items-center gap-1.5 rounded bg-black/75 px-2 py-1 text-[9px] text-white">
                  <input type="checkbox" checked={styleAssetIds.includes(asset.id)} onChange={() => toggleStyleAsset(asset.id)} />
                  {t('assets.select')}
                </label>
                <span className={`absolute right-2 top-2 rounded border px-1.5 py-0.5 text-[9px] ${asset.approval === 'approved'
                  ? 'border-emerald-400/70 bg-emerald-950/80 text-emerald-200'
                  : 'border-amber-400/60 bg-amber-950/80 text-amber-200'}`}>
                  {asset.approval === 'approved' ? t('status.approved') : t('status.draft')}
                </span>
              </div>
              <input className={`${input} mt-2`} value={asset.name}
                onChange={event => patchVisualAsset(asset.id, { name: event.target.value })}
                aria-label={t('assets.nameAria', { name: asset.name })} />
              <div className="mt-1 flex flex-wrap items-center gap-1 text-[9px] uppercase tracking-wide text-text-muted">
                <span>{asset.assetKind || asset.provider}</span>
                <span>·</span>
                <span>{asset.variantKind === 'styled' ? t('assets.styledVariant') : t('assets.original')}</span>
                {asset.model && <><span>·</span><span>{asset.provider}/{asset.model}</span></>}
                <span>·</span><span>{new Date(asset.createdAt).toLocaleString()}</span>
              </div>
              <textarea className={`${input} mt-2 min-h-16 resize-y`} value={asset.description || ''}
                onChange={event => patchVisualAsset(asset.id, { description: event.target.value })}
                placeholder={t('assets.descriptionPlaceholder')} aria-label={t('assets.descriptionAria', { name: asset.name })} />
              <textarea className={`${input} mt-2 min-h-20 resize-y`} value={asset.prompt}
                onChange={event => patchVisualAsset(asset.id, { prompt: event.target.value })}
                placeholder={t('assets.promptPlaceholder')} aria-label={t('assets.promptAria', { name: asset.name })} />
              {asset.stylePrompt && <p className="mt-1 text-[9px] text-violet-200">{t('assets.styleLabel', { style: asset.stylePrompt })}</p>}
              <button
                className={`${button} mt-2 w-full ${asset.approval === 'approved' ? 'border-emerald-500/60 text-emerald-300' : 'border-amber-500/50 text-amber-200'}`}
                onClick={() => patchVisualAsset(asset.id, {
                  approval: asset.approval === 'approved' ? 'draft' : 'approved',
                })}
              >
                <Check size={13} /> {asset.approval === 'approved' ? t('assets.approvedProduction') : t('assets.approveProduction')}
              </button>
            </div>
          ))}
        </div>
      ) : <div className={`${panel} py-10 text-center text-xs text-text-muted`}>{t('assets.empty')}</div>}
    </section>
  )
}
