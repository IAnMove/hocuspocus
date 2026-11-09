import { lazy, Suspense, useState, useCallback, useEffect, useRef } from 'react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { fileFromStudioOutput } from '../../lib/studioInputsPick.ts'
import { useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'
import { imageReferenceJobs } from '../../features/studio/imageBatch'
import { ExtraReferenceRows, ReferenceItem } from './ImageRefRows'
import { hasReferenceFiles, referenceDragProps } from './imageRefRowHelpers'
import { forgetLocalImage, localEditFile } from '../../lib/localEditImages'

const AssetExplorerDialog = lazy(() => import('../common/AssetExplorerDialog').then(module => ({ default: module.AssetExplorerDialog })))

const rowButton = 'min-h-11 rounded border border-border px-3 text-xs text-text-secondary'

export function ImageRefSection() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const modelOptions = useStore(s => s.modelOptions)
  const imageMode = useStore(s => Number(s.params.image_mode ?? 1))
  const imageRefs = useStore(s => s.imageRefs)
  const imageRefRows = useStore(s => s.imageRefRows)
  const imageRefType = useStore(s => s.imageRefType)
  const removeBackgroundRefs = useStore(s => s.removeBackgroundRefs)
  const addImageRef = useStore(s => s.addImageRef)
  const removeImageRef = useStore(s => s.removeImageRef)
  const reorderImageRefs = useStore(s => s.reorderImageRefs)
  const cloneImageRef = useStore(s => s.cloneImageRef)
  const replaceImageRef = useStore(s => s.replaceImageRef)
  const addImageRefRow = useStore(s => s.addImageRefRow)
  const replaceImageRefInRow = useStore(s => s.replaceImageRefInRow)
  const splitImageRefsIntoRows = useStore(s => s.splitImageRefsIntoRows)
  const separateEdits = useStore(s => s.imageStudioIntent === 'edit' && Boolean(s.imageBatch?.enabled))
  const perLine = useStore(s => Boolean(s.imageBatch?.perLine))
  const prompt = useStore(s => String(s.params.prompt || ''))
  const setImageRefType = useStore(s => s.setImageRefType)
  const setRemoveBackgroundRefs = useStore(s => s.setRemoveBackgroundRefs)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
  const [libraryTarget, setLibraryTarget] = useState<{ row: number; index: number } | null>(null)
  const replaceAt = useRef<{ row: number; index: number } | null>(null)
  const replaceFile = useRef<HTMLInputElement>(null)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const imageItems = useWorkspaceOutputs(activeWorkspace, 'image')
  const mounted = useRef(true)
  const [error, setError] = useState('')
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  const config = modelOptions?.image_ref_choices
  const bgLabel = modelOptions?.background_removal_label
  // max_image_refs is the model's total conditioning-image budget. In Edit
  // mode the uploaded source already consumes one slot.
  const configuredMaxRefs = modelOptions?.max_image_refs ?? null
  const imageGuide = useStore(s => s.params.image_guide)
  const usesEditSource = Boolean(imageGuide) || imageMode === 2
  const maxRefs = configuredMaxRefs == null ? null : Math.max(0, configuredMaxRefs - (usesEditSource ? 1 : 0))
  const canAddMore = maxRefs == null || imageRefs.length < maxRefs
  const hasRefs = hasReferenceFiles(imageRefs, imageRefRows)

  const addFiles = useCallback((files: File[]) => {
    const room = maxRefs == null ? files.length : Math.max(0, maxRefs - imageRefs.length)
    files.slice(0, room).forEach(addImageRef)
  }, [addImageRef, imageRefs.length, maxRefs])

  // Determine available modes from choices
  const hasLandscapeMode = config?.choices?.some(([, v]: [string, string]) => v.includes('K')) ?? false
  const hasPeopleMode = config?.choices?.some(([, v]: [string, string]) => v === 'I') ?? false
  const defaultRefType = hasLandscapeMode ? 'KI' : hasPeopleMode ? 'I' : ''

  // Auto-set ref type when images are added/removed
  useEffect(() => {
    if (!config) return
    if (hasRefs && imageRefType === '') {
      setImageRefType(defaultRefType)
    } else if (!hasRefs && imageRefType !== '') {
      setImageRefType('')
    }
  }, [config, defaultRefType, hasRefs, imageRefType, setImageRefType])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    // If it's a reorder drag (has our index data), ignore — handled by item onDrop
    if (e.dataTransfer.getData('ref-index')) return
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'))
    addFiles(files)
  }, [addFiles])

  const fileFromItem = useCallback((item: ApiOutput) => {
    const local = localEditFile(item.url)
    return (local ? Promise.resolve(local) : fileFromStudioOutput(item)).then(file => {
      if (local) forgetLocalImage(item.url)
      return file
    })
  }, [])

  const stillSameForm = (before: ReturnType<typeof useStore.getState>) => {
    const state = useStore.getState()
    return mounted.current && state.activeWorkspace === before.activeWorkspace
      && state.imageStudioIntent === before.imageStudioIntent && state.generationMode === before.generationMode
  }

  const chooseImage = useCallback((row: number, item: ApiOutput) => {
    const before = useStore.getState()
    setError('')
    void fileFromItem(item).then(file => {
      if (!stillSameForm(before)) return
      const state = useStore.getState()
      const files = row < 0 ? state.imageRefs : state.imageRefRows[row] || []
      if (maxRefs != null && files.length >= maxRefs) return
      if (row < 0) state.addImageRef(file)
      else state.addImageRefToRow(row, file)
    }).catch(() => { if (mounted.current) setError(tCommon('picker.uploadFailed')) })
  }, [fileFromItem, maxRefs, tCommon])

  const replaceFromLibrary = useCallback((row: number, index: number, item: ApiOutput) => {
    const before = useStore.getState()
    setError('')
    void fileFromItem(item).then(file => {
      if (!stillSameForm(before)) return
      const state = useStore.getState()
      if (row < 0) state.replaceImageRef(index, file)
      else state.replaceImageRefInRow(row, index, file)
    }).catch(() => { if (mounted.current) setError(tCommon('picker.uploadFailed')) })
  }, [fileFromItem, tCommon])

  const referenceJobCount = separateEdits ? 0 : imageReferenceJobs(prompt, perLine, { primary: imageRefs, rows: imageRefRows }).length

  if (!config) return null

  return (
    <div className="space-y-2">
      <label className="text-[11px] text-text-muted uppercase tracking-wider block">
        {t('imageRef.title')}
      </label>
      <p className="text-xs text-text-primary">{t('imageRef.row', { count: 1 })}</p>

      <ul className="space-y-2">
        {imageRefs.map((file, i) => (
          <ReferenceItem
            key={`${i}-${file.name}-${file.lastModified}`}
            file={file} index={i} count={imageRefs.length}
            badge={i === 0 && imageRefs.length > 1 && hasLandscapeMode && imageRefType === 'KI' ? t('imageRef.main') : undefined}
            workspace={activeWorkspace} canClone={canAddMore} highlighted={dragOverIndex === i}
            liProps={referenceDragProps(i, setDragOverIndex, reorderImageRefs)}
            onMove={to => reorderImageRefs(i, to)}
            onClone={() => cloneImageRef(i)}
            onReplace={() => { replaceAt.current = { row: -1, index: i }; replaceFile.current?.click() }}
            onLibrary={() => setLibraryTarget({ row: -1, index: i })}
            onRemove={() => removeImageRef(i)}
          />
        ))}
      </ul>

      <input
        ref={replaceFile}
        aria-label={t('imageRef.replace')}
        type="file"
        accept=".png,.jpg,.jpeg,.webp,.bmp,image/*"
        className="hidden"
        onChange={event => {
          const file = event.target.files?.[0]
          const target = replaceAt.current
          if (file && target) {
            if (target.row < 0) replaceImageRef(target.index, file)
            else replaceImageRefInRow(target.row, target.index, file)
          }
          event.target.value = ''
        }}
      />
      <Suspense fallback={null}>
        {libraryTarget != null && (
          <AssetExplorerDialog
            open
            title={t('imageRef.replace')}
            items={imageItems}
            workspaceId={activeWorkspace}
            remote
            constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
            onChoose={item => {
              if (item && libraryTarget) replaceFromLibrary(libraryTarget.row, libraryTarget.index, item)
              setLibraryTarget(null)
            }}
            onClose={() => setLibraryTarget(null)}
          />
        )}
      </Suspense>

      {canAddMore && (
        <div onDrop={handleDrop} onDragOver={e => e.preventDefault()}>
          <p className="mb-1 text-xs text-text-primary">{t('imageRef.add')}</p>
          <AssetInput
            label={t('imageRef.add')}
            placeholder={t('imageRef.add')}
            items={imageItems}
            accept=".png,.jpg,.jpeg,.webp,.bmp,image/*"
            workspaceId={activeWorkspace}
            keepLocal
            constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
            onChoose={item => { if (item) chooseImage(-1, item) }}
          />
        </div>
      )}

      {!separateEdits && (
        <ExtraReferenceRows
          maxRefs={maxRefs} workspace={activeWorkspace} items={imageItems}
          onChoose={chooseImage}
          onReplace={(row, index) => { replaceAt.current = { row, index }; replaceFile.current?.click() }}
          onLibrary={(row, index) => setLibraryTarget({ row, index })}
        />
      )}

      {!separateEdits && (
        <div className="flex flex-wrap gap-1">
          <button type="button" className={rowButton} onClick={() => addImageRefRow()}>{t('imageRef.addRow')}</button>
          {(imageRefs.length > 1 || (imageRefRows || []).some(files => files.length > 1)) && (
            <button type="button" className={rowButton} onClick={() => splitImageRefsIntoRows()}>{t('imageRef.split')}</button>
          )}
        </div>
      )}

      {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}

      {maxRefs != null && (
        <p className="text-[9px] text-text-muted">
          {t('imageRef.max', { count: maxRefs })}
        </p>
      )}

      {/* Focus mode toggle — only when images present and model supports both modes */}
      {hasRefs && hasLandscapeMode && hasPeopleMode && (
        <div className="flex bg-bg-tertiary rounded-lg p-0.5 border border-border">
          <button
            onClick={() => setImageRefType('KI')}
            className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
              imageRefType === 'KI'
                ? 'bg-bg-active text-text-primary'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {t('inputs.subjectLandscape')}
          </button>
          <button
            onClick={() => setImageRefType('I')}
            className={`flex-1 text-[10px] py-1.5 rounded-md transition-all ${
              imageRefType === 'I'
                ? 'bg-bg-active text-text-primary'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {t('inputs.peopleObjects')}
          </button>
        </div>
      )}

      <p className="text-[10px] text-text-muted">{t('imageRef.hint')}</p>
      {!separateEdits && <p className="text-[10px] text-text-muted">{t('imageRef.rowsHint')}</p>}
      {referenceJobCount > 1 && (
        <p role="status" className="text-xs text-text-secondary">
          {t('imageRef.jobs', { count: referenceJobCount })}
        </p>
      )}

      {/* Background removal toggle */}
      {hasRefs && bgLabel && (
        <label className="flex items-start gap-2 cursor-pointer">
          <input aria-label={bgLabel}
            type="checkbox"
            checked={removeBackgroundRefs}
            onChange={e => setRemoveBackgroundRefs(e.target.checked)}
            className="mt-0.5 w-3.5 h-3.5 rounded border-border bg-bg-tertiary accent-accent-blue shrink-0"
          />
          <span className="text-[10px] text-text-secondary leading-tight">{bgLabel}</span>
        </label>
      )}
    </div>
  )
}
