import { useEffect, useMemo } from 'react'
import { X } from 'lucide-react'
import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { studioMediaPath, useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'

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

function imageOutputFromPath(path: string | null, workspace: string): ApiOutput | undefined {
  if (!path) return undefined
  const name = path.replace(/\\/g, '/').split('/').pop() || path
  const url = api.getStoredAssetUrl(path)
  return {
    name,
    type: 'image',
    mode: null,
    size: 0,
    created_at: 0,
    url,
    thumbnail_url: url,
    workspace_id: workspace,
    path,
  }
}

function imageOutputFromClip(file: File | null, path: string | null, workspace: string): ApiOutput | undefined {
  const fromPath = imageOutputFromPath(path, workspace)
  if (fromPath) return fromPath
  if (!file) return undefined
  return {
    name: file.name,
    type: 'image',
    mode: null,
    size: file.size,
    created_at: 0,
    url: '',
    thumbnail_url: '',
    workspace_id: workspace,
    path: '',
  }
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
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const imageItems = useWorkspaceOutputs(activeWorkspace, 'image')
  const openIndex = focusedClipIndex

  const chooseStart = (clipIndex: number, item: ApiOutput | null) => {
    const live = useStore.getState().clips
    if (!live[clipIndex]) return
    if (!item) {
      setClipStartImage(clipIndex, null)
      return
    }
    setClipStartImage(clipIndex, null, studioMediaPath(item))
  }

  const chooseKeyframe = (clipIndex: number, item: ApiOutput | null) => {
    if (!item) return
    const live = useStore.getState().clips
    if (!live[clipIndex]) return
    addClipKeyframe(clipIndex, null, studioMediaPath(item))
  }

  if (clips.length === 0) return null

  return (
    <div className="space-y-3">
      <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
        <input aria-label={t('multiClip.samePrompt')}
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
            <AssetInput
              label={t('multiClip.startImage')}
              placeholder={t('multiClip.startImage')}
              items={imageItems}
              value={imageOutputFromClip(clip.startImage, clip.startImagePath, activeWorkspace)}
              accept="image/*"
              workspaceId={activeWorkspace}
              optional={Boolean(clip.startImagePath || clip.startImage)}
              constraints={{ kinds: ['image'], maxCount: 1, optional: true }}
              onChoose={item => chooseStart(i, item)}
            />

            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] uppercase tracking-wider text-text-muted">
                  {t('multiClip.keyframes', { count: clip.keyframes.length })}
                </span>
                <div className="min-w-[8rem]">
                  <AssetInput
                    label={tCommon('actions.add')}
                    placeholder={tCommon('actions.add')}
                    items={imageItems}
                    accept="image/*"
                    workspaceId={activeWorkspace}
                    constraints={{ kinds: ['image'], maxCount: 1, optional: false }}
                    onChoose={item => chooseKeyframe(i, item)}
                  />
                </div>
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

            <textarea aria-label={t('multiClip.placeholder', { n: i + 1 })}
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
