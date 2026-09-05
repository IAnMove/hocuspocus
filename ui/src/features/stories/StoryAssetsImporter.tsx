import { type RefObject } from 'react'
import { Check, Loader2, Upload } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { button, panel, Field } from './storyLabChrome'
import { StoryAssetsProposalCard } from './StoryAssetsProposalCard'
import type { PendingSmartAsset } from './storyLabAssets'
import type { StoryProject } from './types'

export function StoryAssetsImporter({
  project, smartAssetBusy, smartAssetDescription, setSmartAssetDescription, smartAssetRef,
  pendingSmartAssets, setPendingSmartAssets, analyzeSmartAssets, applySmartAssets, patchPendingSmartAsset,
}: {
  project: StoryProject
  smartAssetBusy: boolean
  smartAssetDescription: string
  setSmartAssetDescription: (value: string) => void
  smartAssetRef: RefObject<HTMLInputElement | null>
  pendingSmartAssets: PendingSmartAsset[]
  setPendingSmartAssets: (value: PendingSmartAsset[]) => void
  analyzeSmartAssets: (files: File[]) => void
  applySmartAssets: () => void
  patchPendingSmartAsset: (index: number, patch: Partial<PendingSmartAsset>) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const analyzer = project.provider.writingProvider === 'maestro'
    ? t('assets.analyzerInternal')
    : t('assets.analyzerExternal', {
      provider: project.provider.writingProvider,
      model: project.provider.writingModel || t('assets.configuredModel'),
    })
  return (
    <>
      <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
        <div>
          <h2 className="text-lg font-semibold text-text-primary">{t('assets.title')}</h2>
          <p className="mt-1 max-w-3xl text-xs text-text-muted">{t('assets.description')}</p>
        </div>
        <div className="rounded-md border border-border bg-bg-tertiary px-3 py-2 text-[10px] text-text-muted">
          {analyzer}
        </div>
      </div>

      <div className={`${panel} mb-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]`}>
        <button
          type="button"
          disabled={smartAssetBusy}
          className="min-h-44 rounded-xl border-2 border-dashed border-border bg-bg-tertiary/40 p-6 text-center transition-colors hover:border-accent-blue hover:bg-accent-blue/5 disabled:opacity-50"
          onClick={() => smartAssetRef.current?.click()}
          onDragOver={event => event.preventDefault()}
          onDrop={event => {
            event.preventDefault()
            void analyzeSmartAssets(Array.from(event.dataTransfer.files))
          }}
        >
          {smartAssetBusy
            ? <Loader2 size={28} className="mx-auto mb-3 animate-spin text-accent-blue" />
            : <Upload size={28} className="mx-auto mb-3 text-accent-blue" />}
          <span className="block text-sm font-medium text-text-primary">
            {smartAssetBusy ? t('assets.uploading') : t('assets.drop')}
          </span>
          <span className="mt-2 block text-[10px] text-text-muted">{t('assets.dropHint')}</span>
        </button>
        <div>
          <Field
            label={t('assets.batchContext')}
            value={smartAssetDescription}
            onChange={setSmartAssetDescription}
            rows={6}
            placeholder={t('assets.batchContextPlaceholder')}
          />
          <p className="mt-2 text-[9px] text-text-muted">{t('assets.batchContextHint')}</p>
        </div>
      </div>

      {pendingSmartAssets.length > 0 && (
        <section className="mb-5">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 className="text-sm font-semibold text-text-primary">{t('assets.reviewTitle')}</h3>
              <p className="text-[10px] text-text-muted">{t('assets.reviewHint')}</p>
            </div>
            <div className="flex gap-2">
              <button className={button} onClick={() => setPendingSmartAssets([])}>{t('assets.discardBatch')}</button>
              <button className={`${button} border-emerald-500/50 text-emerald-300`}
                disabled={!pendingSmartAssets.some(item => item.selected && item.kind !== 'ignore')}
                onClick={applySmartAssets}>
                <Check size={13} /> {t('assets.applySelected')}
              </button>
            </div>
          </div>
          <div className="space-y-3">
            {pendingSmartAssets.map((item, index) => (
              <StoryAssetsProposalCard key={`${item.source}-${index}`} item={item} index={index} project={project} onPatch={patchPendingSmartAsset} />
            ))}
          </div>
        </section>
      )}
    </>
  )
}
