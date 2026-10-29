import { useState, useCallback, useEffect, useMemo } from 'react'
import { X } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { VideoTimelineSelector } from '../shared/VideoTimelineSelector'
import { OutpaintCanvas } from './OutpaintCanvas'
import { StudioSourceField } from '../../lib/StudioSourceField.tsx'
import { applyChosenStudioMedia, useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'

/**
 * Outpaint mode controls.
 *
 * Layout when a clip is loaded:
 *   1. Film-strip timeline with start/end trim markers (same component
 *      as inpaint mode for consistency).
 *   2. Interactive canvas composer (OutpaintCanvas) — black canvas at
 *      the chosen aspect ratio with the source clip draggable +
 *      resizable on top. Embeds its own 6-button aspect picker.
 *   3. Output Quality button group (replaces the legacy dropdown).
 *   4. Advanced section (collapsed by default) — mask preservation,
 *      preserve audio, and sliding-window cleanup.
 *
 * The previous version exposed per-side padding sliders + a separate
 * aspect-ratio dropdown that drove those sliders. The interactive
 * canvas replaces both: the user drags / resizes the video inside the
 * canvas and the pads are derived at submit time (see useStore.submit
 * outpaint branch). Backwards-compat: the legacy `outpaintPadding`
 * field in the store is still mirrored on submit so older sidecars
 * keep round-tripping.
 */

const QUALITY_OPTIONS = [
  { v: 'auto', labelKey: 'outpaint.auto', hintKey: 'outpaint.autoHint' },
  { v: '480p', label: '480p', hintKey: 'outpaint.p480' },
  { v: '540p', label: '540p', hintKey: 'outpaint.p540' },
  { v: '720p', label: '720p', hintKey: '' },
  { v: '1080p', label: '1080p', hintKey: 'outpaint.p1080' },
] as const

type Quality = (typeof QUALITY_OPTIONS)[number]['v']

export function OutpaintControls() {
  const { t } = useUiTranslation('studio')
  const editVideoFile = useStore(s => s.editVideoFile)
  const editVideoUrl = useStore(s => s.editVideoUrl)
  const editVideoDuration = useStore(s => s.editVideoDuration)
  const editVideoResolution = useStore(s => s.editVideoResolution)
  const setEditVideo = useStore(s => s.setEditVideo)
  const clearEditVideo = useStore(s => s.clearEditVideo)

  // Trim window — outpaint has its own trim state separate from the
  // inpaint flow's editStartTime/editEndTime so the two modes don't
  // step on each other when a user toggles between them.
  const trimStart = useStore(s => s.outpaintTrimStart)
  const trimEnd = useStore(s => s.outpaintTrimEnd)
  const setTrimStart = useStore(s => s.setOutpaintTrimStart)
  const setTrimEnd = useStore(s => s.setOutpaintTrimEnd)

  const outpaintResolutionPreset = useStore(s => s.outpaintResolutionPreset)
  const setOutpaintResolutionPreset = useStore(s => s.setOutpaintResolutionPreset)
  const outpaintMaskPreserving = useStore(s => s.outpaintMaskPreserving)
  const setOutpaintMaskPreserving = useStore(s => s.setOutpaintMaskPreserving)
  const outpaintPreserveSourceAudio = useStore(s => s.outpaintPreserveSourceAudio)
  const setOutpaintPreserveSourceAudio = useStore(s => s.setOutpaintPreserveSourceAudio)
  const outpaintTrimSmear = useStore(s => s.outpaintTrimSmear)
  const setOutpaintTrimSmear = useStore(s => s.setOutpaintTrimSmear)
  const windowSize = useStore(s => s.slidingWindowSeconds)
  const setWindowSize = useStore(s => s.setSlidingWindowSeconds)
  const windowLocked = useStore(s => s.slidingWindowLocked)

  const [error, setError] = useState<string | null>(null)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const library = useWorkspaceOutputs(activeWorkspace)
  const mediaItems = useMemo(
    () => library.filter(item => item.type === 'image' || item.type === 'video'),
    [library],
  )

  // Source pixel dimensions parsed from editVideoResolution (e.g. "1280x720").
  // OutpaintCanvas needs these to:
  //   - render the canvas in canvas-pixel-space (so output dims match aspect)
  //   - letterbox-fit the source video into the canvas on aspect change
  // Falls back to {0,0} when no resolution string is set yet (placeholder
  // dimensions OutpaintCanvas treats as "not ready" and renders nothing).
  const { srcW, srcH } = useMemo(() => {
    if (!editVideoResolution) return { srcW: 0, srcH: 0 }
    const m = /^(\d+)x(\d+)$/.exec(editVideoResolution)
    if (!m) return { srcW: 0, srcH: 0 }
    return { srcW: parseInt(m[1], 10), srcH: parseInt(m[2], 10) }
  }, [editVideoResolution])

  const handleChoose = useCallback((item: import('../../api/outputs').ApiOutput) => {
    setError(null)
    applyChosenStudioMedia(item, next => {
      setEditVideo(next.file, next.path, next.url, next.duration, `${next.width}x${next.height}`)
      if (item.type === 'video') {
        setTrimStart(0)
        setTrimEnd(next.duration)
      }
    })
  }, [setEditVideo, setTrimStart, setTrimEnd])

  const isVideoFile = editVideoFile?.type.startsWith('video/')
  const selectedDuration = trimEnd > trimStart
    ? trimEnd - trimStart
    : editVideoDuration

  // Match Studio Frames mode: an unlocked window follows a short clip with
  // a one-second quantization buffer, up to the model's ~20-second limit.
  // Outpaint has a trim timeline instead of DurationSlider, so it needs the
  // same tracking behavior here.
  useEffect(() => {
    if (windowLocked || !isVideoFile || selectedDuration <= 0) return
    if (selectedDuration <= 20) {
      const nextWindow = Math.min(21, Math.ceil(selectedDuration) + 1)
      if (windowSize !== nextWindow) setWindowSize(nextWindow)
    } else if (windowSize < 10) {
      setWindowSize(20)
    }
  }, [isVideoFile, selectedDuration, windowLocked]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-3">
      {/* Upload zone — shown only when no clip loaded. Same dashed-border
          + drop-target treatment as the other Edit-mode flows. */}
      {!editVideoFile ? (
        <StudioSourceField
          label={t('outpaint.drop')}
          items={mediaItems}
          accept="video/*,image/*"
          kinds={['image', 'video']}
          workspaceId={activeWorkspace}
          onChoose={handleChoose}
        />
      ) : (
        <>
          {/* Header: filename + remove button. The X mirrors the inpaint
              flow — clears the loaded clip and resets the canvas state
              implicitly (OutpaintCanvas will re-fit on next mount when
              srcW/srcH return to 0). */}
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] text-text-muted truncate flex-1">{editVideoFile.name}</p>
            <button
              onClick={() => clearEditVideo()}
              className="shrink-0 p-1 rounded text-text-muted hover:bg-bg-hover hover:text-red-400 transition-colors"
              title={t('outpaint.removeClip')} aria-label={t('outpaint.removeClip')}
            >
              <X size={14} />
            </button>
          </div>

          {/* Film-strip timeline with start/end trim markers — only meaningful
              for actual videos. Images skip this since there's no time axis. */}
          {isVideoFile && editVideoDuration > 0 && (
            <VideoTimelineSelector
              videoUrl={editVideoUrl}
              duration={editVideoDuration}
              startTime={trimStart}
              endTime={trimEnd}
              onStartChange={setTrimStart}
              onEndChange={setTrimEnd}
            />
          )}

          {/* Interactive composer — embeds its own 6-button aspect picker
              (16:9 / 9:16 / 1:1 / 4:3 / 3:4 / source). Drives outpaintAspect
              and outpaintVideoBox in the store; useStore.submit reads both
              at submit time and derives pad_top/bottom/left/right pixels. */}
          {srcW > 0 && srcH > 0 && editVideoUrl && (
            <OutpaintCanvas
              videoUrl={editVideoUrl}
              srcW={srcW}
              srcH={srcH}
            />
          )}
        </>
      )}

      {error && <p className="text-[10px] text-red-400">{error}</p>}

      {/* Output Quality button group (replaces the legacy dropdown).
          Always shown — the chosen quality applies to whatever clip is
          loaded next, so it's useful to set even before upload. */}
      <div>
        <label className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
          {t('outpaint.quality')}
        </label>
        <div className="grid grid-cols-5 gap-1">
          {QUALITY_OPTIONS.map(q => (
            <button
              key={q.v}
              onClick={() => setOutpaintResolutionPreset(q.v as Quality)}
              title={q.hintKey ? t(q.hintKey) : undefined}
              className={`px-1 py-1.5 rounded text-[10px] border transition-colors ${
                outpaintResolutionPreset === q.v
                  ? 'border-accent-blue bg-accent-blue/15 text-accent-blue'
                  : 'border-border text-text-muted hover:border-border-light hover:text-text-secondary'
              }`}
            >
              {'labelKey' in q ? t(q.labelKey) : q.label}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-text-muted mt-1">
          {t('outpaint.qualityHint')}
        </p>
      </div>

      {/* Advanced remains collapsed so the default workflow stays simple. */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-[10px] text-text-muted hover:text-text-primary transition-colors"
      >
        {showAdvanced ? '▾' : '▸'} {t('chrome.advanced')}
      </button>
      {showAdvanced && (
        <div className="space-y-3 pl-2 border-l border-border/50">
          <label
            className="flex items-start gap-2 cursor-pointer"
            title={t('outpaint.preserveTitle')}
          >
            <input aria-label={t('outpaint.preserveScene')}
              type="checkbox"
              checked={outpaintMaskPreserving}
              onChange={e => setOutpaintMaskPreserving(e.target.checked)}
              className="w-3 h-3 mt-0.5 rounded border-border accent-accent-blue shrink-0"
            />
            <div className="flex-1">
              <span className="text-[10px] text-text-secondary">
                {t('outpaint.preserveScene')}
              </span>
              <span className="ml-1 text-[9px] text-accent-blue">
                {t('chrome.recommended')}
              </span>
              <p className="text-[9px] text-text-muted mt-0.5">
                {t('outpaint.preserveSceneHint')}
              </p>
            </div>
          </label>

          <label className="flex items-start gap-2 cursor-pointer">
            <input aria-label={t('outpaint.preserveAudio')}
              type="checkbox"
              checked={outpaintPreserveSourceAudio}
              onChange={e => setOutpaintPreserveSourceAudio(e.target.checked)}
              className="w-3 h-3 mt-0.5 rounded border-border accent-accent-blue shrink-0"
            />
            <div className="flex-1">
              <span className="text-[10px] text-text-secondary">{t('outpaint.preserveAudio')}</span>
              <p className="text-[9px] text-text-muted mt-0.5">
                {t('outpaint.preserveAudioHint')}
              </p>
            </div>
          </label>

          <label className="flex items-start gap-2 cursor-pointer">
            <input aria-label={t('outpaint.trimSmear')}
              type="checkbox"
              checked={outpaintTrimSmear}
              onChange={e => setOutpaintTrimSmear(e.target.checked)}
              className="w-3 h-3 mt-0.5 rounded border-border accent-accent-blue shrink-0"
            />
            <div className="flex-1">
              <span className="text-[10px] text-text-secondary">{t('outpaint.trimSmear')}</span>
              <p className="text-[9px] text-text-muted mt-0.5">
                {t('outpaint.trimSmearHint')}
              </p>
            </div>
          </label>
        </div>
      )}
    </div>
  )
}
