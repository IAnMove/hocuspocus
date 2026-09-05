import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Eye,
  Loader2,
  Paintbrush,
  Pencil,
  Plus,
  Upload,
  X,
} from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { RepaintRegionMapping } from '../../types'
import { VideoTimelineSelector } from '../shared/VideoTimelineSelector'
import { InfoTooltip } from './InfoTooltip'
import { ScailResolutionSelector } from './ScailResolutionSelector'
import * as api from '../../api/client'

const REGION_COLORS = ['#0000ff', '#ff0000', '#00c853', '#ff00ff', '#00cfd1']

function newRegion(index: number): RepaintRegionMapping {
  return {
    id: `repaint-${Date.now()}-${index}`,
    source: '',
    target: '',
  }
}

type PreviewResult = Awaited<ReturnType<typeof api.repaintPreview>>

/**
 * The internal sub-mode id remains `restyle` for saved-output compatibility,
 * but the product-facing workflow is Repaint: edit the selected first frame,
 * then animate it with the source video's exact SCAIL-2 motion path.
 */
export function RestyleControls() {
  const { t } = useUiTranslation('studio')
  const editVideoFile = useStore(s => s.editVideoFile)
  const editVideoPath = useStore(s => s.editVideoPath)
  const editVideoUrl = useStore(s => s.editVideoUrl)
  const editVideoDuration = useStore(s => s.editVideoDuration)
  const editStartTime = useStore(s => s.editStartTime)
  const editEndTime = useStore(s => s.editEndTime)
  const setEditVideo = useStore(s => s.setEditVideo)
  const clearEditVideo = useStore(s => s.clearEditVideo)
  const targetFramePath = useStore(s => s.editRepaintFramePath)
  const targetFrameUrl = useStore(s => s.editRepaintFrameUrl)
  const setTargetFrame = useStore(s => s.setEditRepaintFrame)
  const mappings = useStore(s => s.editRepaintMappings)
  const setMappings = useStore(s => s.setEditRepaintMappings)
  const resolutionProfile = useStore(s => s.editRepaintResolutionProfile)
  const sendFrameToImageMode = useStore(s => s.sendFrameToImageMode)

  const videoInputRef = useRef<HTMLInputElement>(null)
  const [showRegions, setShowRegions] = useState(mappings.length > 0)
  const [previewState, setPreviewState] = useState<'idle' | 'loading' | 'found' | 'error'>('idle')
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewError, setPreviewError] = useState('')

  useEffect(() => {
    if (mappings.length > 0) {
      const open = window.setTimeout(() => setShowRegions(true), 0)
      return () => window.clearTimeout(open)
    }
    return undefined
  }, [mappings.length])

  const resetPreview = useCallback(() => {
    setPreviewState('idle')
    setPreview(null)
    setPreviewError('')
  }, [])

  const handleVideoUpload = useCallback(async (file: File) => {
    try {
      const result = await api.uploadImage(file)
      const url = URL.createObjectURL(file)
      const video = document.createElement('video')
      video.src = url
      video.onloadedmetadata = () => {
        const duration = video.duration && isFinite(video.duration) ? video.duration : 0
        const resolution = `${video.videoWidth}x${video.videoHeight}`
        setEditVideo(file, result.path, url, duration, resolution)
        // An edited frame is composition-specific. A new source must not
        // silently reuse a target made for the previous video.
        setTargetFrame(null, '', '')
      }
      resetPreview()
    } catch (error) {
      console.error('Repaint source upload failed:', error)
    }
  }, [resetPreview, setEditVideo, setTargetFrame])

  const handleTargetUpload = useCallback(async (file: File) => {
    try {
      const result = await api.uploadImage(file)
      setTargetFrame(file, result.path, URL.createObjectURL(file))
      resetPreview()
    } catch (error) {
      console.error('Repaint target-frame upload failed:', error)
    }
  }, [resetPreview, setTargetFrame])

  const updateMapping = useCallback((index: number, patch: Partial<RepaintRegionMapping>) => {
    const next = useStore.getState().editRepaintMappings.map((mapping, mappingIndex) => (
      mappingIndex === index ? { ...mapping, ...patch } : mapping
    ))
    setMappings(next)
    resetPreview()
  }, [resetPreview, setMappings])

  const addMapping = useCallback(() => {
    if (mappings.length >= 5) return
    setMappings([...mappings, newRegion(mappings.length)])
    resetPreview()
  }, [mappings, resetPreview, setMappings])

  const removeMapping = useCallback((index: number) => {
    setMappings(mappings.filter((_, mappingIndex) => mappingIndex !== index))
    resetPreview()
  }, [mappings, resetPreview, setMappings])

  const handlePreview = useCallback(async () => {
    if (
      !editVideoPath
      || !targetFramePath
      || mappings.length === 0
      || mappings.some(mapping => !mapping.source.trim() || !mapping.target.trim())
    ) return
    setPreviewState('loading')
    setPreviewError('')
    try {
      const result = await api.repaintPreview({
        video_path: editVideoPath,
        target_frame_path: targetFramePath,
        region_mappings: mappings.map(mapping => ({
          id: mapping.id,
          source: mapping.source.trim(),
          target: mapping.target.trim(),
        })),
        time: editStartTime,
      })
      setPreview(result)
      setPreviewState(result.found ? 'found' : 'error')
      if (!result.found) {
        setPreviewError(t('repaint.mismatch'))
      }
    } catch (error) {
      setPreviewState('error')
      setPreviewError(error instanceof Error ? error.message : t('repaint.previewFailed'))
    }
  }, [editStartTime, editVideoPath, mappings, targetFramePath, t])

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <Paintbrush size={13} className="shrink-0 text-accent-blue" />
        <span className="text-[10px] font-medium text-text-primary">
          {t('repaint.title')}
        </span>
        <InfoTooltip
          placement="bottom"
          label={t('repaint.about')}
          text={t('repaint.aboutText')}
        />
      </div>

      <ScailResolutionSelector
        value={resolutionProfile}
        workflow="Repaint"
        onChange={profile => {
          useStore.setState({ editRepaintResolutionProfile: profile })
          resetPreview()
        }}
      />

      {!editVideoFile ? (
        <div
          onDragOver={event => event.preventDefault()}
          onDrop={event => {
            event.preventDefault()
            const file = event.dataTransfer.files[0]
            if (file?.type.startsWith('video/')) void handleVideoUpload(file)
          }}
          onClick={() => videoInputRef.current?.click()}
          className="border-2 border-dashed border-border rounded-lg p-6 text-center cursor-pointer hover:border-accent-blue/50 hover:bg-bg-hover/30 transition-all"
        >
          <Upload size={24} className="mx-auto mb-2 text-text-muted" />
          <p className="text-xs text-text-secondary">{t('repaint.drop')}</p>
          <input
            ref={videoInputRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={event => {
              if (event.target.files?.[0]) void handleVideoUpload(event.target.files[0])
              event.currentTarget.value = ''
            }}
          />
        </div>
      ) : (
        <div className="relative">
          <button
            onClick={() => {
              clearEditVideo()
              setTargetFrame(null, '', '')
              resetPreview()
            }}
            className="absolute top-1.5 right-1.5 z-20 p-1 rounded-full bg-black/60 text-white/80 hover:text-white hover:bg-black/80 transition-colors"
            title={t('repaint.removeSource')}
          >
            <X size={14} />
          </button>
          <VideoTimelineSelector
            videoUrl={editVideoUrl}
            duration={editVideoDuration}
            startTime={editStartTime}
            endTime={editEndTime}
            onStartChange={time => {
              useStore.setState({ editStartTime: time })
              // The target frame must correspond to the selected first frame.
              setTargetFrame(null, '', '')
              resetPreview()
            }}
            onEndChange={time => useStore.setState({ editEndTime: time })}
          />
          <p className="text-[9px] text-text-muted mt-1 truncate">{editVideoFile.name}</p>
        </div>
      )}

      <div className="space-y-2 rounded-lg border border-border bg-bg-secondary/40 p-2.5">
        <div className="flex items-center gap-1">
          <p className="text-[10px] font-medium text-text-primary">{t('repaint.editedFrame')}</p>
          <InfoTooltip
            label={t('repaint.aboutFrame')}
            text={t('repaint.aboutFrameText')}
          />
        </div>

        {targetFramePath && (
          <div className="relative">
            <img
              src={targetFrameUrl}
              alt={t('repaint.editedFrame')}
              className="w-full max-h-48 object-contain rounded border border-border bg-black/20"
            />
            <button
              onClick={() => {
                setTargetFrame(null, '', '')
                resetPreview()
              }}
              className="absolute top-1.5 right-1.5 p-1 rounded-full bg-black/65 text-white/80 hover:text-white"
              title={t('repaint.removeFrame')}
            >
              <X size={12} />
            </button>
          </div>
        )}

        <button
          onClick={() => void sendFrameToImageMode('repaint')}
          disabled={!editVideoPath}
          className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded border border-accent-blue/40 bg-accent-blue/10 text-[10px] text-accent-blue hover:bg-accent-blue/20 disabled:opacity-40"
        >
          <Pencil size={11} />
          {targetFramePath ? t('repaint.editAgain') : t('repaint.editFrame')}
        </button>

        <label className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 rounded border border-dashed border-border text-[10px] text-text-secondary hover:text-text-primary hover:border-accent-blue/50 cursor-pointer">
          <Upload size={11} />
          {targetFramePath ? t('repaint.replaceFrame') : t('repaint.uploadFrame')}
          <input
            type="file"
            accept="image/*"
            className="hidden"
            onChange={event => {
              if (event.target.files?.[0]) void handleTargetUpload(event.target.files[0])
              event.currentTarget.value = ''
            }}
          />
        </label>
      </div>

      <div className="rounded-lg border border-border overflow-hidden">
        <div className="flex items-center">
          <button
            onClick={() => setShowRegions(value => !value)}
            className="flex flex-1 items-center gap-1.5 px-2.5 py-2 text-left hover:bg-bg-hover/40"
          >
            {showRegions ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            <span className="text-[10px] text-text-primary">{t('repaint.trackRegions')}</span>
            <span className="ml-auto text-[9px] text-text-muted">{t('chrome.optional')}</span>
          </button>
          <div className="pr-2">
            <InfoTooltip
              label={t('repaint.aboutRegions')}
              text={t('repaint.aboutRegionsText')}
            />
          </div>
        </div>

        {showRegions && (
          <div className="space-y-2 border-t border-border p-2.5">
            {mappings.map((mapping, index) => {
              const result = preview?.mapping_results.find(item => item.mapping_index === index)
              return (
                <div key={mapping.id} className="rounded border border-border bg-bg-secondary/50 p-2 space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <span
                      className="h-3 w-3 rounded-full border border-white/30"
                      style={{ backgroundColor: REGION_COLORS[index] }}
                    />
                    <span className="text-[9px] text-text-secondary">{t('repaint.region', { n: index + 1 })}</span>
                    <button
                      onClick={() => removeMapping(index)}
                      className="ml-auto p-0.5 text-text-muted hover:text-status-error"
                      title={t('repaint.removeRegion')}
                    >
                      <X size={11} />
                    </button>
                  </div>
                  <input
                    type="text"
                    value={mapping.source}
                    onChange={event => updateMapping(index, { source: event.target.value })}
                    placeholder={t('repaint.sourcePlaceholder')}
                    className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-[10px] text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                  />
                  <input
                    type="text"
                    value={mapping.target}
                    onChange={event => updateMapping(index, { target: event.target.value })}
                    placeholder={t('repaint.targetPlaceholder')}
                    className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-[10px] text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                  />
                  {result && (
                    <p className={`text-[8px] ${result.source_found && result.target_found ? 'text-accent-green' : 'text-status-warning'}`}>
                      {t('repaint.matchLine', {
                        source: result.source_found ? t('repaint.found') : t('repaint.notFound'),
                        target: result.target_found ? t('repaint.found') : t('repaint.notFound'),
                      })}
                    </p>
                  )}
                </div>
              )
            })}

            <div className="flex gap-1.5">
              {mappings.length < 5 && (
                <button
                  onClick={addMapping}
                  className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded border border-dashed border-border text-[9px] text-text-secondary hover:text-accent-blue hover:border-accent-blue/50"
                >
                  <Plus size={11} />
                  {t('repaint.addRegion')}
                </button>
              )}
              {mappings.length > 0 && (
                <button
                  onClick={() => void handlePreview()}
                  disabled={
                    previewState === 'loading'
                    || !editVideoPath
                    || !targetFramePath
                    || mappings.some(mapping => !mapping.source.trim() || !mapping.target.trim())
                  }
                  className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded border border-border bg-bg-tertiary text-[9px] text-text-secondary hover:text-text-primary disabled:opacity-40"
                >
                  {previewState === 'loading'
                    ? <Loader2 size={11} className="animate-spin" />
                    : <Eye size={11} />}
                  {t('repaint.previewRegions')}
                </button>
              )}
            </div>

            {preview && (
              <div className="grid grid-cols-2 gap-1.5">
                <div>
                  <img src={preview.source_preview} alt={t('repaint.sourceAlt')} className="w-full rounded border border-border" />
                  <p className="text-[8px] text-text-muted mt-0.5">{t('repaint.sourceCaption')}</p>
                </div>
                <div>
                  <img src={preview.target_preview} alt={t('repaint.editedAlt')} className="w-full rounded border border-border" />
                  <p className="text-[8px] text-text-muted mt-0.5">{t('repaint.editedCaption')}</p>
                </div>
              </div>
            )}
            {previewState === 'error' && previewError && (
              <p className="text-[9px] text-status-error">{previewError}</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
