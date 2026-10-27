import { controlLabel } from '../../i18n/controlLabel'
import { useCallback, useEffect, useState } from 'react'
import { X, Sparkles } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { VideoTimelineSelector } from '../shared/VideoTimelineSelector'
import type { ApiOutput } from '../../api/outputs'
import { StudioSourceField } from '../../lib/StudioSourceField.tsx'
import { applyChosenStudioMedia, useWorkspaceOutputs } from '../../lib/studioAssetPick.ts'

/**
 * Edit Anything sub-mode — prompt-driven video edit via the
 * Alissonerdx/LTX-LoRAs "Edit Anything" LoRA. No SAM mask required;
 * the LoRA interprets Add / Remove / Replace / Style patterns directly.
 */
export function EditAnythingControls() {
  const { t } = useUiTranslation('studio')
  const editVideoFile = useStore(s => s.editVideoFile)
  const editVideoUrl = useStore(s => s.editVideoUrl)
  const editVideoDuration = useStore(s => s.editVideoDuration)
  const editStartTime = useStore(s => s.editStartTime)
  const editEndTime = useStore(s => s.editEndTime)
  const loraStrength = useStore(s => s.editAnythingLoraStrength)
  const retakeStrength = useStore(s => s.editRetakeStrength)
  const setEditVideo = useStore(s => s.setEditVideo)
  const clearEditVideo = useStore(s => s.clearEditVideo)
  const ensureEditAnythingLora = useStore(s => s.ensureEditAnythingLora)

  const [showAdvanced, setShowAdvanced] = useState(false)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  const videoItems = useWorkspaceOutputs(activeWorkspace, 'video')

  // On mount, make sure the Edit Anything LoRA is downloaded. Idempotent.
  useEffect(() => {
    void ensureEditAnythingLora()
  }, [ensureEditAnythingLora])

  const handleChoose = useCallback((item: ApiOutput) => {
    applyChosenStudioMedia(item, next => {
      setEditVideo(next.file, next.path, next.url, next.duration, `${next.width}x${next.height}`)
    })
  }, [setEditVideo])

  return (
    <div className="space-y-3">
      {/* Header hint */}
      <div className="flex items-start gap-2 bg-accent-blue/10 border border-accent-blue/20 rounded-lg px-2.5 py-2">
        <Sparkles size={12} className="text-accent-blue mt-0.5 shrink-0" />
        <p className="text-[10px] text-text-secondary leading-snug">
          {t('editAnything.hintLead')}
          <br />
          <span className="text-text-muted">• </span><span className="text-text-primary">{t('editAnything.add')}</span>{t('editAnything.addRest')}
          <br />
          <span className="text-text-muted">• </span><span className="text-text-primary">{t('editAnything.remove')}</span>{t('editAnything.removeRest')}
          <br />
          <span className="text-text-muted">• </span><span className="text-text-primary">{t('editAnything.replace')}</span>{t('editAnything.replaceRest')}
          <br />
          <span className="text-text-muted">• </span><span className="text-text-primary">{t('editAnything.convert')}</span>{t('editAnything.convertRest')}
        </p>
      </div>

      {/* Video upload or timeline */}
      {!editVideoFile ? (
        <StudioSourceField
          label={t('chrome.dropVideo')}
          items={videoItems}
          accept="video/*"
          kinds={['video']}
          workspaceId={activeWorkspace}
          onChoose={handleChoose}
        />
      ) : (
        <div className="relative">
          <button onClick={clearEditVideo}
            className="absolute top-1.5 right-1.5 z-20 p-1 rounded-full bg-black/60 text-white/80 hover:text-white hover:bg-black/80 transition-colors" title={controlLabel('a11y.clearVideo')} aria-label={controlLabel('a11y.clearVideo')}>
            <X size={14} />
          </button>
          <VideoTimelineSelector
            videoUrl={editVideoUrl}
            duration={editVideoDuration}
            startTime={editStartTime}
            endTime={editEndTime}
            onStartChange={t => useStore.setState({ editStartTime: t })}
            onEndChange={t => useStore.setState({ editEndTime: t })}
          />
          <p className="text-[9px] text-text-muted mt-1 truncate">{editVideoFile.name}</p>
        </div>
      )}

      {/* Advanced knobs */}
      <button onClick={() => setShowAdvanced(!showAdvanced)}
        className="text-[10px] text-text-muted hover:text-text-primary transition-colors">
        {showAdvanced ? '▾' : '▸'} {t('chrome.advanced')}
      </button>
      {showAdvanced && (
        <div className="space-y-3 pl-2 border-l border-border/50">
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[10px] text-text-muted uppercase tracking-wider">{t('editAnything.loraStrength')}</label>
              <span className="text-[10px] text-text-secondary">{loraStrength.toFixed(2)}</span>
            </div>
            <input
              type="range" min={0.5} max={1.5} step={0.05}
              value={loraStrength}
              onChange={e => useStore.setState({ editAnythingLoraStrength: parseFloat(e.target.value) })}
              className="w-full"
            />
            <p className="text-[9px] text-text-muted mt-0.5">
              {t('editAnything.loraHint')}
            </p>
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[10px] text-text-muted uppercase tracking-wider">{t('editAnything.preserve')}</label>
              <span className="text-[10px] text-text-secondary">{retakeStrength.toFixed(2)}</span>
            </div>
            <input
              type="range" min={0.3} max={1.0} step={0.05}
              value={retakeStrength}
              onChange={e => useStore.setState({ editRetakeStrength: parseFloat(e.target.value) })}
              className="w-full"
            />
            <p className="text-[9px] text-text-muted mt-0.5">
              {t('editAnything.preserveHint')}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
