import { useState } from 'react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ApiOutput } from '../../api/outputs'
import { AssetInput } from '../../features/asset-picker/AssetInput.tsx'
import { studioMediaPath, useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'

/**
 * The clips picked in this session, by guide URL. The panel unmounts on every sub-tab change
 * while the guide stays in the form, and an uploaded clip is not among the workspace outputs
 * the panel falls back to, so it used to come back as a raw URL. A guide restored from a
 * sidecar is not here and keeps the visible-and-removable URL fallback below.
 */
const pickedGuides = new Map<string, ApiOutput>()

/**
 * SFX mode controls for MMAudio — sound effects generation.
 * User can optionally upload a video clip, plus prompt/neg prompt and duration.
 */
export function SfxControls() {
  const { t } = useUiTranslation('studio')
  const params = useStore(s => s.params)
  const setParam = useStore(s => s.setParam)
  const durationSeconds = useStore(s => s.durationSeconds)
  const setDurationSeconds = useStore(s => s.setDurationSeconds)
  const [chosenVideo, setChosenVideo] = useState<ApiOutput | null>(null)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const videoItems = useWorkspaceOutputs(activeWorkspace, 'video')
  const videoGuide = typeof params.video_guide === 'string' ? params.video_guide : ''
  const matchesGuide = (item: ApiOutput) => Boolean(videoGuide) && [item.asset_id, item.url, studioMediaPath(item)].includes(videoGuide)
  const selectedVideo = chosenVideo && matchesGuide(chosenVideo)
    ? chosenVideo : videoItems.find(matchesGuide) ?? pickedGuides.get(videoGuide)
  const { t: common } = useUiTranslation('common')

  const sfxPrompt = ((params as unknown as Record<string, unknown>).MMAudio_prompt as string) || ''
  const sfxNegPrompt = ((params as unknown as Record<string, unknown>).MMAudio_neg_prompt as string) || ''
  const textWeight = ((params as unknown as Record<string, unknown>).sfx_text_weight as number) ?? 1.0

  const chooseVideo = (item: ApiOutput | null) => {
    // Keep the selected source identity, including its original workspace.
    // The server inspects its duration when preparing the command.
    setParam('video_guide', item?.url)
    if (item) pickedGuides.set(item.url, item)
    setChosenVideo(item)
  }

  return (
    <div className="space-y-3">
      {/* Video clip upload (optional) */}
      <div>
        <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {t('sfx.videoClip')} <span className="normal-case text-text-muted">({t('chrome.optional')})</span>
        </label>
        <AssetInput
          key={activeWorkspace}
          value={selectedVideo}
          label={t('sfx.dropVideo')}
          placeholder={t('sfx.dropVideo')}
          items={videoItems}
          accept=".mp4,.webm,.avi,.mov,.mkv,video/*"
          workspaceId={activeWorkspace}
          optional
          constraints={{ kinds: ['video'], maxCount: 1, optional: true }}
          onChoose={chooseVideo}
        />
        {videoGuide && !selectedVideo && (
          <div className="text-[10px] text-text-secondary break-all">
            <span>{videoGuide}</span>
            <button type="button" className="ml-2 underline" onClick={() => chooseVideo(null)}>
              {common('picker.remove')}
            </button>
          </div>
        )}
        <p className="text-[9px] text-text-muted mt-1">
          {t('sfx.hint')}
        </p>
      </div>

      {/* Duration (shown when no video — max 20s, MMAudio single-pass limit) */}
      {!videoGuide && (
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[11px] text-text-muted uppercase tracking-wider">{t('sfx.duration')}</label>
            <span className="text-xs text-text-secondary">{Math.min(durationSeconds, 20)}s</span>
          </div>
          <input
            type="range"
            min={1}
            max={20}
            step={1}
            value={Math.min(durationSeconds, 20)}
            onChange={e => setDurationSeconds(Number(e.target.value))}
          />
        </div>
      )}

      {/* SFX Prompt */}
      <div>
        <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {t('sfx.description')}
        </label>
        <textarea
          value={sfxPrompt}
          onChange={e => setParam('MMAudio_prompt' as keyof typeof params, e.target.value)}
          placeholder={t('sfx.promptPlaceholder')}
          rows={2}
          className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
          style={{ resize: 'vertical', minHeight: 48 }}
        />
      </div>

      {/* Negative prompt */}
      <div>
        <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {t('sfx.negative')}
        </label>
        <input
          type="text"
          value={sfxNegPrompt}
          onChange={e => setParam('MMAudio_neg_prompt' as keyof typeof params, e.target.value)}
          placeholder={t('sfx.negativePlaceholder')}
          className="w-full bg-bg-tertiary border border-border rounded px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
        />
      </div>

      {/* Text prompt weight */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-[11px] text-text-muted uppercase tracking-wider">
            {t('sfx.strength')}
          </label>
          <span className="text-xs text-text-secondary">{textWeight.toFixed(1)}x</span>
        </div>
        <input
          type="range"
          min={0}
          max={5}
          step={0.1}
          value={textWeight}
          onChange={e => setParam('sfx_text_weight' as keyof typeof params, parseFloat(e.target.value))}
        />
        <p className="text-[9px] text-text-muted mt-0.5">
          {t('sfx.strengthHint')}
        </p>
      </div>
    </div>
  )
}
