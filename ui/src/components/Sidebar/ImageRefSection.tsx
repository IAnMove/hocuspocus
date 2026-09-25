import { useState, useCallback, useEffect, useRef } from 'react'
import { X } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { fileFromStudioOutput } from '../../lib/studioInputsPick.ts'
import { useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'
import { EditableImageReference } from './EditableImageReference'
import { forgetLocalImage, localEditFile } from '../../lib/localEditImages'

export function ImageRefSection() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const modelOptions = useStore(s => s.modelOptions)
  const imageMode = useStore(s => Number(s.params.image_mode ?? 1))
  const imageRefs = useStore(s => s.imageRefs)
  const imageRefType = useStore(s => s.imageRefType)
  const removeBackgroundRefs = useStore(s => s.removeBackgroundRefs)
  const addImageRef = useStore(s => s.addImageRef)
  const removeImageRef = useStore(s => s.removeImageRef)
  const reorderImageRefs = useStore(s => s.reorderImageRefs)
  const setImageRefType = useStore(s => s.setImageRefType)
  const setRemoveBackgroundRefs = useStore(s => s.setRemoveBackgroundRefs)
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null)
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
    if (imageRefs.length > 0 && imageRefType === '') {
      setImageRefType(defaultRefType)
    } else if (imageRefs.length === 0 && imageRefType !== '') {
      setImageRefType('')
    }
  }, [config, defaultRefType, imageRefs.length, imageRefType, setImageRefType])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    // If it's a reorder drag (has our index data), ignore — handled by item onDrop
    if (e.dataTransfer.getData('ref-index')) return
    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'))
    addFiles(files)
  }, [addFiles])

  const chooseImage = useCallback((item: ApiOutput) => {
    const before = useStore.getState()
    const local = localEditFile(item.url)
    setError('')
    void (local ? Promise.resolve(local) : fileFromStudioOutput(item)).then(file => {
      if (local) forgetLocalImage(item.url)
      const state = useStore.getState()
      if (!mounted.current || state.activeWorkspace !== before.activeWorkspace
        || state.imageStudioIntent !== before.imageStudioIntent || state.generationMode !== before.generationMode) return
      if (maxRefs == null || state.imageRefs.length < maxRefs) state.addImageRef(file)
    }).catch(() => { if (mounted.current) setError(tCommon('picker.uploadFailed')) })
  }, [maxRefs, tCommon])

  if (!config) return null

  return (
    <div className="space-y-2">
      <label className="text-[11px] text-text-muted uppercase tracking-wider block">
        {t('imageRef.title')}
      </label>

      {/* Thumbnails + add button in a unified row */}
      <div className="flex flex-wrap gap-1.5">
        {imageRefs.map((file, i) => (
          <div
            key={`${i}-${file.name}`}
            draggable
            onDragStart={e => {
              e.dataTransfer.setData('ref-index', String(i))
              e.dataTransfer.effectAllowed = 'move'
            }}
            onDragOver={e => {
              e.preventDefault()
              e.dataTransfer.dropEffect = 'move'
              setDragOverIndex(i)
            }}
            onDragLeave={() => setDragOverIndex(null)}
            onDrop={e => {
              e.preventDefault()
              e.stopPropagation()
              setDragOverIndex(null)
              const from = parseInt(e.dataTransfer.getData('ref-index'), 10)
              if (!isNaN(from) && from !== i) reorderImageRefs(from, i)
            }}
            className={`relative w-[90px] h-[90px] rounded-lg overflow-hidden border group cursor-grab active:cursor-grabbing transition-colors ${
              dragOverIndex === i ? 'border-accent-blue border-2' : 'border-border'
            }`}
          >
            <EditableImageReference key={`${activeWorkspace}:${file.name}:${file.lastModified}`} file={file} />
            {i === 0 && imageRefs.length > 1 && hasLandscapeMode && imageRefType === 'KI' && (
              <div className="pointer-events-none absolute top-4 left-0 right-0 bg-black/60 text-[8px] text-white text-center py-0.5">
                {t('imageRef.main')}
              </div>
            )}
            {/* Position number */}
            <span className="absolute top-0.5 left-0.5 bg-black/60 text-white text-[8px] px-1 rounded pointer-events-none">
              {i + 1}
            </span>
            <button
              onClick={() => removeImageRef(i)}
              className="absolute top-0.5 right-0.5 bg-bg-primary/80 rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity hover:bg-bg-hover"
            >
              <X size={10} />
            </button>
          </div>
        ))}

        {/* Add button / drop zone */}
        {canAddMore && (
          <div className="min-w-[10rem]" onDrop={handleDrop} onDragOver={e => e.preventDefault()}>
            <AssetInput
              label={tCommon('actions.add')}
              placeholder={tCommon('actions.add')}
              items={imageItems}
              accept=".png,.jpg,.jpeg,.webp,.bmp,image/*"
              workspaceId={activeWorkspace}
              keepLocal
              constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
              onChoose={item => { if (item) chooseImage(item) }}
            />
          </div>
        )}
      </div>

      {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}

      {maxRefs != null && (
        <p className="text-[9px] text-text-muted">
          {t('imageRef.max', { count: maxRefs })}
        </p>
      )}

      {/* Focus mode toggle — only when images present and model supports both modes */}
      {imageRefs.length > 0 && hasLandscapeMode && hasPeopleMode && (
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

      {/* Hint text */}
      {imageRefs.length > 0 && hasLandscapeMode && imageRefType === 'KI' && (
        <p className="text-[10px] text-text-muted">
          {t('imageRef.hint')}
        </p>
      )}

      {/* Background removal toggle */}
      {imageRefs.length > 0 && bgLabel && (
        <label className="flex items-start gap-2 cursor-pointer">
          <input
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
