import { useRef, useCallback, useState } from 'react'
import { Upload, X, UserRoundPen, Loader2, Eye, Plus } from 'lucide-react'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { RecastCharacterMapping } from '../../types'
import { VideoTimelineSelector } from '../shared/VideoTimelineSelector'
import { InfoTooltip } from './InfoTooltip'
import { ScailResolutionSelector } from './ScailResolutionSelector'
import * as api from '../../api/client'

const MAPPING_COLORS = ['#0000ff', '#ff0000', '#00c853', '#ff00ff', '#00cfd1']
const MAPPING_LABELS = ['A', 'B', 'C', 'D', 'E']

type ReferencePreview = NonNullable<
  Awaited<ReturnType<typeof api.recastPreview>>['reference_previews']
>[number]
type MappingPreviewResult = NonNullable<
  Awaited<ReturnType<typeof api.recastPreview>>['mapping_results']
>[number]

function formatTimelineTime(seconds?: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return ''
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds - minutes * 60
  return `${minutes}:${remainder.toFixed(1).padStart(4, '0')}`
}

function emptyMapping(index: number): RecastCharacterMapping {
  return {
    id: `recast-${Date.now()}-${index}`,
    target: '',
    refFile: null,
    refPath: '',
    refUrl: '',
    additionalRefs: [],
    referenceAlignedToSource: false,
  }
}

/**
 * Recast sub-mode — deterministic SCAIL-2 source-person → reference mapping.
 * Every card owns one stable semantic color; additional images on that card
 * reuse the same color and therefore describe another view of the same person.
 */
export function RecastControls() {
  const { t } = useUiTranslation('studio')
  const editVideoFile = useStore(s => s.editVideoFile)
  const editVideoPath = useStore(s => s.editVideoPath)
  const editVideoUrl = useStore(s => s.editVideoUrl)
  const editVideoDuration = useStore(s => s.editVideoDuration)
  const editStartTime = useStore(s => s.editStartTime)
  const editEndTime = useStore(s => s.editEndTime)
  const setEditVideo = useStore(s => s.setEditVideo)
  const clearEditVideo = useStore(s => s.clearEditVideo)
  const mappings = useStore(s => s.editRecastMappings)
  const setMappings = useStore(s => s.setEditRecastMappings)
  const useRelighting = useStore(s => s.editRecastUseRelighting)
  const resolutionProfile = useStore(s => s.editRecastResolutionProfile)

  const [previewImg, setPreviewImg] = useState<string | null>(null)
  const [previewState, setPreviewState] = useState<'idle' | 'loading' | 'found' | 'notfound' | 'error'>('idle')
  const [previewMatch, setPreviewMatch] = useState<{ matched: number; requested: number } | null>(null)
  const [mappingResults, setMappingResults] = useState<MappingPreviewResult[]>([])
  const [referencePreviews, setReferencePreviews] = useState<ReferencePreview[]>([])
  const [previewError, setPreviewError] = useState('')
  const videoFileRef = useRef<HTMLInputElement>(null)

  const resetPreview = useCallback(() => {
    setPreviewImg(null)
    setPreviewState('idle')
    setPreviewMatch(null)
    setMappingResults([])
    setReferencePreviews([])
    setPreviewError('')
  }, [])

  const updateMapping = useCallback((index: number, patch: Partial<RecastCharacterMapping>) => {
    const next = useStore.getState().editRecastMappings.map((mapping, mappingIndex) => (
      mappingIndex === index ? { ...mapping, ...patch } : mapping
    ))
    setMappings(next)
    resetPreview()
  }, [resetPreview, setMappings])

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
      }
      resetPreview()
    } catch {
      console.error('Failed to upload video')
    }
  }, [resetPreview, setEditVideo])

  const handlePrimaryUpload = useCallback(async (mappingIndex: number, file: File) => {
    try {
      const result = await api.uploadImage(file)
      updateMapping(mappingIndex, {
        refFile: file,
        refPath: result.path,
        refUrl: URL.createObjectURL(file),
        referenceAlignedToSource: false,
      })
    } catch {
      console.error('Failed to upload reference image')
    }
  }, [updateMapping])

  const handleAdditionalUploads = useCallback(async (mappingIndex: number, files: File[]) => {
    try {
      const available = Math.max(
        0,
        4 - (useStore.getState().editRecastMappings[mappingIndex]?.additionalRefs.length || 0),
      )
      const selected = files.slice(0, available)
      const uploaded = await Promise.all(selected.map(async file => {
        const result = await api.uploadImage(file)
        return { file, path: result.path, url: URL.createObjectURL(file) }
      }))
      const current = useStore.getState().editRecastMappings[mappingIndex]
      if (!current) return
      updateMapping(mappingIndex, {
        additionalRefs: [...current.additionalRefs, ...uploaded],
      })
    } catch {
      console.error('Failed to upload additional reference view')
    }
  }, [updateMapping])

  const handlePreview = useCallback(async () => {
    if (!editVideoPath || mappings.length === 0) return
    setPreviewState('loading')
    setPreviewError('')
    try {
      const res = await api.recastPreview({
        video_path: editVideoPath,
        character_mappings: mappings.map(mapping => ({
          id: mapping.id,
          target: mapping.target.trim() || 'person',
          ...(mapping.refPath ? { ref_image_path: mapping.refPath } : {}),
          additional_ref_image_paths: mapping.additionalRefs
            .map(reference => reference.path)
            .filter(Boolean),
          reference_aligned_to_source: mapping.referenceAlignedToSource,
        })),
        // Recast's identity preparation is intentionally automatic now.
        isolate_reference: true,
        auto_face_detail: true,
        resolution_profile: resolutionProfile,
        time: editStartTime,
        end_time: editEndTime,
      })
      setPreviewImg(res.preview)
      setPreviewMatch({ matched: res.matched_people, requested: res.requested_people })
      setMappingResults(res.mapping_results || [])
      setReferencePreviews(res.reference_previews || [])
      setPreviewState(res.found ? 'found' : 'notfound')
    } catch (error) {
      console.error('Recast preview failed:', error)
      setPreviewError(error instanceof Error ? error.message : t('recast.previewFailed'))
      setPreviewState('error')
    }
  }, [editVideoPath, mappings, editStartTime, editEndTime, resolutionProfile, t])

  const addMapping = useCallback(() => {
    if (mappings.length >= 5) return
    setMappings([...mappings, emptyMapping(mappings.length)])
    resetPreview()
  }, [mappings, resetPreview, setMappings])

  const removeMapping = useCallback((index: number) => {
    if (mappings.length <= 1) return
    setMappings(mappings.filter((_, mappingIndex) => mappingIndex !== index))
    resetPreview()
  }, [mappings, resetPreview, setMappings])

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5">
        <UserRoundPen size={13} className="shrink-0 text-accent-blue" />
        <span className="text-[10px] font-medium text-text-primary">
          {t('recast.title')}
        </span>
        <InfoTooltip
          placement="bottom"
          label={t('recast.about')}
          text={t('recast.aboutText')}
        />
      </div>

      <ScailResolutionSelector
        value={resolutionProfile}
        workflow="Recast"
        onChange={profile => {
          useStore.setState({ editRecastResolutionProfile: profile })
          resetPreview()
        }}
      />

      {!editVideoFile ? (
        <div
          onDragOver={event => event.preventDefault()}
          onDrop={event => {
            event.preventDefault()
            const file = event.dataTransfer.files[0]
            if (file && file.type.startsWith('video/')) void handleVideoUpload(file)
          }}
          onClick={() => videoFileRef.current?.click()}
          className="border-2 border-dashed border-border rounded-lg p-6 text-center cursor-pointer hover:border-accent-blue/50 hover:bg-bg-hover/30 transition-all"
        >
          <Upload size={24} className="mx-auto mb-2 text-text-muted" />
          <p className="text-xs text-text-secondary">{t('chrome.dropVideo')}</p>
          <input
            ref={videoFileRef}
            type="file"
            accept="video/*"
            className="hidden"
            onChange={event => {
              if (event.target.files?.[0]) void handleVideoUpload(event.target.files[0])
            }}
          />
        </div>
      ) : (
        <div className="relative">
          <button
            onClick={() => {
              clearEditVideo()
              resetPreview()
            }}
            className="absolute top-1.5 right-1.5 z-20 p-1 rounded-full bg-black/60 text-white/80 hover:text-white hover:bg-black/80 transition-colors"
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
              resetPreview()
            }}
            onEndChange={time => {
              useStore.setState({ editEndTime: time })
              resetPreview()
            }}
          />
          <p className="text-[9px] text-text-muted mt-1 truncate">{editVideoFile.name}</p>
        </div>
      )}

      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <label className="text-[10px] text-text-muted uppercase tracking-wider">
              {t('recast.characters', { count: mappings.length })}
            </label>
            <InfoTooltip
              label={t('recast.aboutMappings')}
              text={t('recast.aboutMappingsText')}
            />
          </div>
          <button
            onClick={handlePreview}
            disabled={!editVideoPath || previewState === 'loading' || mappings.some(mapping => !mapping.target.trim())}
            className="flex items-center gap-1 px-2 py-1 rounded bg-bg-tertiary border border-border text-[9px] text-text-secondary hover:text-text-primary hover:border-accent-blue/50 transition-colors disabled:opacity-40"
            title={t('recast.previewTitle')}
          >
            {previewState === 'loading'
              ? <Loader2 size={11} className="animate-spin" />
              : <Eye size={11} />}
            {t('recast.preview')}
          </button>
        </div>

        {mappings.map((mapping, mappingIndex) => {
          const mappingResult = mappingResults.find(result => result.mapping_index === mappingIndex)
          const previews = referencePreviews.filter(preview => preview.mapping_index === mappingIndex)
          return (
            <div key={mapping.id} className="rounded-lg border border-border bg-bg-secondary/40 p-2 space-y-2">
              <div className="flex items-center gap-1.5">
                <span
                  className="w-3 h-3 rounded-full border border-white/30 shrink-0"
                  style={{ backgroundColor: MAPPING_COLORS[mappingIndex] }}
                />
                <span className="text-[10px] font-medium text-text-primary">
                  {t('recast.character', { label: MAPPING_LABELS[mappingIndex] })}
                </span>
                {mappings.length > 1 && (
                  <button
                    onClick={() => removeMapping(mappingIndex)}
                    className="ml-auto p-0.5 text-text-muted hover:text-status-error"
                    title={t('recast.removeMapping')}
                  >
                    <X size={12} />
                  </button>
                )}
              </div>

              <div>
                <label className="text-[9px] text-text-muted block mb-0.5">{t('recast.who')}</label>
                <input
                  type="text"
                  value={mapping.target}
                  onChange={event => updateMapping(mappingIndex, { target: event.target.value })}
                  placeholder={mappingIndex === 0 ? t('recast.whoPh0') : t('recast.whoPh1')}
                  className="w-full bg-bg-tertiary border border-border rounded px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent-blue"
                />
                {mappingResult && (
                  <p className={`text-[9px] mt-0.5 ${mappingResult.found ? 'text-accent-green' : 'text-status-warning'}`}>
                    {mappingResult.found
                      ? t('recast.foundAt', { time: formatTimelineTime(mappingResult.anchor_time_seconds) })
                      : t('recast.notFound')}
                    {mappingResult.overlap_fraction > 0.02 && t('recast.overlap', { percent: (mappingResult.overlap_fraction * 100).toFixed(0) })}
                  </p>
                )}
              </div>

              <div>
                <label className="text-[9px] text-text-muted block mb-0.5">{t('recast.replacement')}</label>
                {!mapping.refPath ? (
                  <label className="block border border-dashed border-border rounded p-3 text-center cursor-pointer hover:border-accent-blue/50 hover:bg-bg-hover/30">
                    <Upload size={15} className="mx-auto mb-1 text-text-muted" />
                    <span className="text-[9px] text-text-secondary">{t('recast.uploadCharacter')}</span>
                    <input
                      type="file"
                      accept="image/*"
                      className="hidden"
                      onChange={event => {
                        if (event.target.files?.[0]) void handlePrimaryUpload(mappingIndex, event.target.files[0])
                        event.currentTarget.value = ''
                      }}
                    />
                  </label>
                ) : (
                  <div className="relative inline-block">
                    <img src={mapping.refUrl} alt={t('recast.refAlt', { label: MAPPING_LABELS[mappingIndex] })} className="h-24 rounded border border-border" />
                    <button
                      onClick={() => updateMapping(mappingIndex, {
                        refFile: null,
                        refPath: '',
                        refUrl: '',
                        additionalRefs: [],
                        referenceAlignedToSource: false,
                      })}
                      className="absolute top-1 right-1 p-0.5 rounded-full bg-black/60 text-white/80 hover:text-white hover:bg-black/80"
                    >
                      <X size={12} />
                    </button>
                  </div>
                )}
              </div>

              {mapping.refPath && !mapping.referenceAlignedToSource && (
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-1">
                      <span className="text-[9px] text-text-muted">{t('recast.moreViews')}</span>
                      <InfoTooltip
                        label={t('recast.aboutViews')}
                        text={t('recast.aboutViewsText')}
                      />
                    </div>
                    <span className="text-[8px] text-text-muted">
                      {mapping.additionalRefs.length}/4
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {mapping.additionalRefs.map((reference, referenceIndex) => (
                      <div key={`${reference.path}-${referenceIndex}`} className="relative">
                        <img src={reference.url} alt={t('recast.viewAlt')} className="h-14 w-14 object-cover rounded border border-border" />
                        <button
                          onClick={() => updateMapping(mappingIndex, {
                            additionalRefs: mapping.additionalRefs.filter((_, index) => index !== referenceIndex),
                          })}
                          className="absolute -top-1 -right-1 p-0.5 rounded-full bg-black/70 text-white"
                        >
                          <X size={9} />
                        </button>
                      </div>
                    ))}
                    {mapping.additionalRefs.length < 4 && (
                      <label className="h-14 w-14 flex flex-col items-center justify-center rounded border border-dashed border-border cursor-pointer hover:border-accent-blue/50 text-text-muted">
                        <Plus size={13} />
                        <span className="text-[7px]">{t('recast.view')}</span>
                        <input
                          type="file"
                          accept="image/*"
                          multiple
                          className="hidden"
                          onChange={event => {
                            if (event.target.files?.length) {
                              void handleAdditionalUploads(mappingIndex, Array.from(event.target.files))
                            }
                            event.currentTarget.value = ''
                          }}
                        />
                      </label>
                    )}
                  </div>
                </div>
              )}

              {previews.length > 0 && (
                <div className="space-y-1.5 border-t border-border pt-1.5">
                  <div className="flex items-center gap-1">
                    <p className="text-[9px] text-accent-green">{t('recast.prepared')}</p>
                    <InfoTooltip
                      label={t('recast.aboutPrepared')}
                      text={t('recast.aboutPreparedText')}
                    />
                  </div>
                  {previews.map(preview => (
                    <div
                      key={`${preview.view_index}-${preview.kind}`}
                      title={`Mask: ${preview.mask_source}${preview.detail_source ? ` · ${preview.detail_source}` : ''}`}
                    >
                      <p className="text-[8px] text-text-muted mb-0.5">
                        {preview.kind === 'primary'
                          ? t('recast.primary')
                          : preview.kind === 'auto_face_detail'
                            ? t('recast.faceDetail')
                            : t('recast.viewN', { n: preview.view_index })} · {preview.prepared_size.join('×')}
                      </p>
                      <div className={`grid gap-1 ${preview.clip_identity_image ? 'grid-cols-3' : 'grid-cols-2'}`}>
                        {preview.clip_identity_image && (
                          <div>
                            <img src={preview.clip_identity_image} alt={t('recast.identityAlt')} className="w-full rounded border border-border" />
                            <span className="text-[7px] text-text-muted">{t('recast.identity')}</span>
                          </div>
                        )}
                        <div>
                          <img src={preview.prepared_image} alt={t('recast.preparedAlt')} className="w-full rounded border border-border" />
                          <span className="text-[7px] text-text-muted">{t('recast.reference')}</span>
                        </div>
                        <div>
                          <img src={preview.semantic_mask} alt={t('recast.maskAlt')} className="w-full rounded border border-border" />
                          <span className="text-[7px] text-text-muted">{t('recast.mask')}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}

        {mappings.length < 5 && (
          <button
            onClick={addMapping}
            className="w-full flex items-center justify-center gap-1 py-1.5 rounded border border-dashed border-border text-[9px] text-text-secondary hover:text-accent-blue hover:border-accent-blue/50"
          >
            <Plus size={11} />
            {t('recast.addCharacter')}
          </button>
        )}
      </div>

      {previewImg && (
        <div>
          <div className="mb-1 flex items-center gap-1">
            <p className="text-[9px] text-text-muted">{t('recast.sourceSelection')}</p>
            <InfoTooltip
              label={t('recast.aboutSource')}
              text={t('recast.aboutSourceText')}
            />
          </div>
          <img src={previewImg} alt={t('recast.mappingAlt')} className="w-full rounded border border-border" />
          {previewState === 'found' && previewMatch && (
            <p className="text-[9px] text-accent-green mt-0.5">
              {t('recast.foundAll', { count: previewMatch.matched })}
            </p>
          )}
          {previewState === 'notfound' && (
            <p className="text-[9px] text-status-warning mt-0.5">
              {t('recast.foundSome', { matched: previewMatch?.matched ?? 0, requested: previewMatch?.requested ?? mappings.length })}
            </p>
          )}
        </div>
      )}
      {previewState === 'error' && (
        <p className="text-[9px] text-status-error">
          {previewError ? t('recast.previewFailedDetail', { message: previewError }) : t('recast.previewFailedLog')}
        </p>
      )}

      <div className="flex items-center gap-1">
        <label className="flex cursor-pointer items-center gap-1.5 text-[9px] text-text-secondary">
          <input
            type="checkbox"
            checked={useRelighting}
            onChange={event => useStore.setState({ editRecastUseRelighting: event.target.checked })}
            className="accent-accent-blue"
          />
          <span>{t('recast.matchLighting')}</span>
        </label>
        <InfoTooltip
          placement="top"
          label={t('recast.aboutLighting')}
          text={t('recast.aboutLightingText')}
        />
      </div>
    </div>
  )
}
