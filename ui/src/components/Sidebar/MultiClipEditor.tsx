import { useEffect, useMemo } from 'react'
import { ImagePlus, Upload, X } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'

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
          <span className="text-[10px] text-text-muted">Start Image</span>
        </>
      )}
    </div>
  )
}

export function MultiClipEditor() {
  const clips = useStore(s => s.clips)
  const singlePromptMode = useStore(s => s.singlePromptMode)
  const setSinglePromptMode = useStore(s => s.setSinglePromptMode)
  const setClipPrompt = useStore(s => s.setClipPrompt)
  const setClipStartImage = useStore(s => s.setClipStartImage)
  const addClipKeyframe = useStore(s => s.addClipKeyframe)
  const removeClipKeyframe = useStore(s => s.removeClipKeyframe)
  const slidingWindowSeconds = useStore(s => s.slidingWindowSeconds)

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
        Same prompt for all clips
      </label>

      <div className="space-y-2">
        {clips.map((clip, i) => (
          <div key={i} className="border border-border rounded-lg p-2 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-text-muted uppercase tracking-wider font-medium">
                Clip {i + 1}
              </span>
              <span className="text-[10px] text-text-muted ml-auto">
                {slidingWindowSeconds}s
              </span>
            </div>

            <ClipDropZone
              file={clip.startImage}
              path={clip.startImagePath}
              onFile={f => setClipStartImage(i, f)}
              onClear={() => setClipStartImage(i, null)}
            />

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider text-text-muted">
                  Keyframes · {clip.keyframes.length}
                </span>
                <label className="inline-flex cursor-pointer items-center gap-1 rounded border border-border px-1.5 py-1 text-[10px] text-text-secondary hover:border-border-light">
                  <ImagePlus size={12} />
                  Add
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
              placeholder={`Describe clip ${i + 1}...`}
              rows={2}
              className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted resize-none focus:outline-none focus:border-accent-blue transition-colors disabled:opacity-40"
            />
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
  const previewUrl = useAssetPreview(file, path)
  if (!previewUrl) return null
  return (
    <div className="group relative aspect-video overflow-hidden rounded border border-border bg-bg-tertiary">
      <img src={previewUrl} alt="Clip keyframe" className="h-full w-full object-cover" />
      <button
        type="button"
        onClick={onRemove}
        className="absolute right-0.5 top-0.5 rounded-full bg-bg-primary/85 p-0.5 opacity-80 hover:opacity-100"
        aria-label="Remove keyframe"
      >
        <X size={10} />
      </button>
    </div>
  )
}
