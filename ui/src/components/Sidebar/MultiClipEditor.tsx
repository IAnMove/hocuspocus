import { useEffect, useMemo } from 'react'
import { ImagePlus, Upload, X } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'

function useAssetPreview(file: File | null, path: string | null) {
  const url = useMemo(
    () => file ? URL.createObjectURL(file) : (path ? api.getStoredAssetUrl(path) : null),
    [file, path],
  )
  useEffect(() => {
    if (!file || !url) return
    return () => URL.revokeObjectURL(url)
  }, [file, url])
  return url
}

function ClipDropZone({ file, path, onFile, onClear }: {
  file: File | null
  path: string | null
  onFile: (f: File) => void
  onClear: () => void
}) {
  const { t } = useUiTranslation('studio')
  const previewUrl = useAssetPreview(file, path)
  return (
    <div
      className="relative border border-dashed border-border rounded-lg p-2 flex items-center justify-center gap-1 cursor-pointer hover:border-border-light transition-colors min-h-[60px]"
      onDrop={e => {
        e.preventDefault()
        const f = e.dataTransfer.files[0]
        if (f && f.type.startsWith('image/')) onFile(f)
      }}
      onDragOver={e => e.preventDefault()}
      onClick={() => {
        const input = document.createElement('input')
        input.type = 'file'
        input.accept = 'image/*'
        input.onchange = (ev) => {
          const f = (ev.target as HTMLInputElement).files?.[0]
          if (f) onFile(f)
        }
        input.click()
      }}
    >
      {previewUrl ? (
        <>
          <img
            src={previewUrl}
            alt="clip"
            className="w-full h-full object-cover rounded absolute inset-0"
          />
          <button
            onClick={e => { e.stopPropagation(); onClear() }}
            className="absolute top-1 right-1 bg-bg-primary/80 rounded-full p-0.5 hover:bg-bg-hover z-10"
          >
            <X size={10} />
          </button>
        </>
      ) : (
        <>
          <Upload size={14} className="text-text-muted" />
          <span className="text-[10px] text-text-muted">{t('multiClip.startImage')}</span>
        </>
      )}
    </div>
  )
}

export function MultiClipEditor() {
  const { t } = useUiTranslation('studio')
  const { t: tCommon } = useUiTranslation('common')
  const clips = useStore(s => s.clips)
  const singlePromptMode = useStore(s => s.singlePromptMode)
  const setSinglePromptMode = useStore(s => s.setSinglePromptMode)
  const focusedClipIndex = useStore(s => s.studioFocusedClipIndex)
  const setFocusedClipIndex = useStore(s => s.setStudioFocusedClipIndex)
  const setClipPrompt = useStore(s => s.setClipPrompt)
  const setClipStartImage = useStore(s => s.setClipStartImage)
  const addClipKeyframe = useStore(s => s.addClipKeyframe)
  const removeClipKeyframe = useStore(s => s.removeClipKeyframe)
  const slidingWindowSeconds = useStore(s => s.slidingWindowSeconds)
  const openIndex = focusedClipIndex

  if (clips.length === 0) return null

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
        <input
          type="checkbox"
          checked={singlePromptMode}
          onChange={e => setSinglePromptMode(e.target.checked)}
          className="rounded border-border accent-accent-blue"
        />
        {t('multiClip.samePrompt')}
      </label>

      <div className="space-y-2">
        {clips.map((clip, i) => (
          <div key={i} className="border border-border rounded-lg p-2 space-y-2">
            <button
              type="button"
              className="flex w-full items-center gap-2 text-left"
              onClick={() => setFocusedClipIndex(openIndex === i ? -1 : i)}
            >
              <span className="text-[11px] text-text-muted uppercase tracking-wider font-medium">
                {t('multiClip.shot', { n: i + 1 })}
              </span>
              <span className="min-w-0 flex-1 truncate text-[10px] text-text-muted">
                {(singlePromptMode && i > 0 ? clips[0].prompt : clip.prompt) || t('multiClip.emptyPrompt')}
              </span>
              <span className="text-[10px] text-text-muted">
                {clip.durationFrames ? `${clip.durationFrames}f` : `${slidingWindowSeconds}s`}
              </span>
            </button>
            {openIndex !== i ? null : (
            <>
            <ClipDropZone
              file={clip.startImage}
              path={clip.startImagePath}
              onFile={f => setClipStartImage(i, f)}
              onClear={() => setClipStartImage(i, null)}
            />

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-text-muted">
                  {t('multiClip.keyframes', { count: clip.keyframes.length })}
                </span>
                <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-1.5 py-1 text-[10px] text-text-secondary hover:border-border-light">
                  <ImagePlus size={12} />
                  {tCommon('actions.add')}
                  <input
                    type="file"
                    accept="image/*"
                    className="hidden"
                    onChange={event => {
                      const file = event.target.files?.[0]
                      if (file) addClipKeyframe(i, file)
                      event.currentTarget.value = ''
                    }}
                  />
                </label>
              </div>
              {clip.keyframes.length > 0 && (
                <div className="grid grid-cols-4 gap-1.5">
                  {clip.keyframes.map((keyframe, keyframeIndex) => (
                    <KeyframeThumbnail
                      key={`${keyframe.path || keyframe.file?.name || 'keyframe'}-${keyframeIndex}`}
                      file={keyframe.file}
                      path={keyframe.path}
                      onRemove={() => removeClipKeyframe(i, keyframeIndex)}
                    />
                  ))}
                </div>
              )}
            </div>

            <textarea
              value={singlePromptMode && i > 0 ? clips[0].prompt : clip.prompt}
              onChange={e => {
                if (singlePromptMode) {
                  setClipPrompt(0, e.target.value)
                } else {
                  setClipPrompt(i, e.target.value)
                }
              }}
              disabled={singlePromptMode && i > 0}
              placeholder={t('multiClip.placeholder', { n: i + 1 })}
              rows={8}
              className="w-full min-h-[10rem] bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted resize-y focus:outline-none focus:border-accent-blue transition-colors disabled:opacity-40"
            />
            </>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function KeyframeThumbnail({ file, path, onRemove }: {
  file: File | null
  path: string | null
  onRemove: () => void
}) {
  const { t } = useUiTranslation('studio')
  const previewUrl = useAssetPreview(file, path)
  if (!previewUrl) return null
  return (
    <div className="group relative aspect-video overflow-hidden rounded border border-border bg-bg-tertiary">
      <img src={previewUrl} alt={t('multiClip.keyframeAlt')} className="h-full w-full object-cover" />
      <button
        type="button"
        onClick={onRemove}
        className="absolute right-0.5 top-0.5 rounded-full bg-bg-primary/85 p-0.5 opacity-80 hover:opacity-100"
        aria-label={t('multiClip.removeKeyframe')}
      >
        <X size={10} />
      </button>
    </div>
  )
}
