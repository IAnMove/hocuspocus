import React, { memo, useState, useRef, useEffect, useCallback, useMemo, type CSSProperties, type MouseEvent as ReactMouseEvent, type SyntheticEvent } from 'react'
import { Copy, Check, Clock3 } from 'lucide-react'
import { FeedMediaBody } from './FeedMediaBody'
import { OutputActionBar } from './OutputActionBar'
import { openOutputInEditor } from './openOutputEditor'
import { useUiTranslation } from '../../i18n'
import { useStore } from '../../stores/useStore'
import { getStoredAssetUrl, fetchOutputMetadata } from '../../api/client'
import type { OutputFile, OutputMetadata } from '../../types'
import { modelDisplayName } from '../../lib/modelDisplay'
import { getOutputReference } from '../../lib/outputReference'
import { formatGenerationBreakdown, formatGenerationDuration } from '../../lib/generationTiming'
import { formatAppAction, formatAppTimestamp } from '../../lib/locale'
import { galleryThumbnailUrl } from './galleryThumbnail'
import type { DetailVideoTime } from './GalleryDetailsDialog'

interface Props {
  file: OutputFile
  index: number
  isActive: boolean
  onVisible: (index: number) => void
  onOpenDetails: (index: number, video?: DetailVideoTime) => void
  /** Row geometry from the gallery layout. The card is exactly this tall, so
   *  the virtualizer's positions are the rendered positions. */
  top: number
  height: number
  mediaHeight: number
}

/** Image component that retries loading if the file isn't fully written yet.
 *
 * Backstops the backend's atomic image-write guarantee in two ways:
 *   1. onError — fires when the request fails outright (404 during the
 *      tiny window between job-complete signal and file existence).
 *   2. onLoad with naturalWidth === 0 — fires when the backend returned
 *      bytes the browser couldn't decode (truncated/corrupt body that
 *      still produced a 200 OK with matching Content-Length). The
 *      browser silently shows an empty box in this case; without the
 *      check the user sees a half-image and feels they need to refresh
 *      the page (which loses Studio prompts/settings/reference images).
 */
function RetryImage({ url, alt, color }: {
  url: string
  alt: string
  /** Average colour shown until the preview decodes. */
  color?: string
}) {
  const [request, setRequest] = useState({ url, tries: 0, bust: 0 })
  const [loadedUrl, setLoadedUrl] = useState<string | null>(null)
  const maxRetries = 5

  if (request.url !== url) {
    setRequest({ url, tries: 0, bust: 0 })
  }

  const src = request.bust
    ? `${url}${url.includes('?') ? '&' : '?'}t=${request.bust}`
    : url

  const scheduleRetry = useCallback(() => {
    setRequest(current => {
      if (current.url !== url || current.tries >= maxRetries) return current
      const tries = current.tries + 1
      setTimeout(() => {
        setRequest(latest => latest.url !== url ? latest : { ...latest, bust: Date.now() })
      }, 800 * tries)
      return { ...current, tries }
    })
  }, [url])

  const handleError = useCallback(() => {
    scheduleRetry()
  }, [scheduleRetry])

  const handleLoad = useCallback((e: SyntheticEvent<HTMLImageElement>) => {
    // Truncated body that decoded to nothing — browser fired onLoad
    // (Content-Length matched) but produced a 0×0 image. Treat as
    // failure and retry with a cache-busted URL.
    const img = e.currentTarget
    if (img.naturalWidth === 0 || img.naturalHeight === 0) {
      scheduleRetry()
      return
    }
    setLoadedUrl(img.getAttribute('src'))
  }, [scheduleRetry])

  return (
    <img
      src={src}
      alt={alt}
      className="mx-auto block h-full w-full object-contain"
      style={loadedUrl === src || !color ? undefined : { backgroundColor: color }}
      decoding="async"
      onError={handleError}
      onLoad={handleLoad}
    />
  )
}

export const MediaFeedItem = memo(function MediaFeedItem({ file, index, isActive, onVisible, onOpenDetails, top, height, mediaHeight }: Props) {
  const { t } = useUiTranslation('activity')
  const setSelectedOutput = useStore(s => s.setSelectedOutput)
  const activeWorkspace = useStore(s => s.activeWorkspace)
  // Virtual Uploads view: browse-only. Move/favorite/delete resolve
  // against the active OUTPUT workspace server-side, so they can't act
  // on upload files — hide them. Download + send-to-input still work
  // (serve_file falls back to the uploads folder).
  const browsingUploads = useStore(s => s.browsingUploads)
  const outputWorkspace = browsingUploads ? '__uploads__' : activeWorkspace
  // Used to translate the raw model_type slug (e.g.
  // "ltx2_22B_distilled_1_1") in the per-clip metadata bar into the
  // human-readable display name (e.g. "LTX-2.3 Distilled 1.1 22B")
  // via modelDisplayName().
  const models = useStore(s => s.models)


  const [meta, setMeta] = useState<OutputMetadata | null>(null)
  const [metaLoaded, setMetaLoaded] = useState(false)
  const [videoReady, setVideoReady] = useState(false)
  const [videoTime, setVideoTime] = useState(0)
  const [referenceCopied, setReferenceCopied] = useState(false)
  const [comicOpenError, setComicOpenError] = useState('')
  const itemRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const metadataRequestRef = useRef(0)

  const releaseVideo = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    video.pause()
    video.removeAttribute('src')
    video.load()
  }, [])

  // IntersectionObserver to detect visibility (for active tracking)
  useEffect(() => {
    const el = itemRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          onVisible(index)
        }
      },
      { threshold: 0.5 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [index, onVisible])

  useEffect(() => {
    metadataRequestRef.current += 1
    setMeta(null)
    setMetaLoaded(false)
  }, [file.name, outputWorkspace])

  // Lazy load metadata when first visible
  useEffect(() => {
    if (metaLoaded) return
    const el = itemRef.current
    if (!el) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          setMetaLoaded(true)
          const request = ++metadataRequestRef.current
          fetchOutputMetadata(file.name, outputWorkspace)
            .then(value => {
              if (metadataRequestRef.current === request) setMeta(value)
            })
            .catch(() => {})
        }
      },
      { threshold: 0.1 }
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [file.name, metaLoaded, outputWorkspace])

  // Pause video when scrolled out of view (but don't auto-play when scrolled in)
  useEffect(() => {
    if (!isActive) {
      releaseVideo()
    }
  }, [isActive, releaseVideo])

  // A scrolled-away clip releases its MP4 source. Returning to it shows the
  // cheap server thumbnail again until the user explicitly presses Play.
  useEffect(() => {
    if (!isActive) setVideoReady(false)
  }, [isActive])

  useEffect(() => {
    setVideoReady(false)
    setVideoTime(0)
    return releaseVideo
  }, [file.url, releaseVideo])

  const params = meta?.params as Record<string, unknown> | null
  const uploadFilenames = meta?.upload_filenames as Record<string, string> | undefined

  const prompt = (params?._tts_original_prompt as string) || (params?.prompt as string) || ''
  const modelType = (params?.model_type as string) || ''
  const modelLabel = modelDisplayName(modelType, models)
  const isAudio = file.type === 'audio'
  const isModel3d = file.type === 'model3d'
  const isScene = file.type === 'scene'
  const isComic = file.type === 'comic'
  const cardStyle = useMemo<CSSProperties>(() => ({ position: 'absolute', top, left: 0, right: 0, height }), [top, height])
  const previewUrl = galleryThumbnailUrl(file, outputWorkspace, 'md')
  const canPreviewModel3d = isModel3d && /\.(glb|gltf)$/i.test(file.name)
  // Rigged outputs carry their baked glTF clip names in the sidecar; the
  // viewer autoplays one and offers a selector to switch.
  const isRigged = !!params?.rigged
  const riggedClips = useMemo(() => (Array.isArray(params?.animations) ? (params.animations as string[]) : []), [params])
  const [activeClip, setActiveClip] = useState<string | null>(null)

  // Keep the model-viewer runtime out of Maestro's main Image/Video/Audio
  // bundle, and only mount WebGL for the active card. The virtualizer can
  // keep ~10 3D items in the window; each model-viewer is a full GPU
  // context, which freezes the desktop when Hunyuan is also running.
  useEffect(() => {
    if (canPreviewModel3d && isActive) void import('@google/model-viewer')
  }, [canPreviewModel3d, isActive])

  const resolution = isAudio ? '' : ((params?.resolution as string) || '')
  const seed = params?.seed as number | undefined
  const generationTime = meta?.generation_timings?.total_time_sec ?? meta?.generation_time
  const generationBreakdown = formatGenerationBreakdown(meta?.generation_timings)
  const outputReference = getOutputReference(file)
  const metadataCompletedAt = meta?.completed_at ?? meta?.finished_at ?? meta?.created_at
  const completionTime = formatAppTimestamp(metadataCompletedAt ?? file.completed_at ?? file.created_at)
  const completionLabel = formatAppAction(browsingUploads ? 'added' : 'finished')
  const completionTimeIsExact = metadataCompletedAt != null || file.completion_time_source === 'metadata'

  const multiClipInfo = params?.multi_clip_info as { group_id: string; index: number; total: number } | undefined
  const clipIndex = multiClipInfo?.index
  const clipTotal = multiClipInfo?.total

  const rawStart = uploadFilenames?.image_start
  const rawEnd = uploadFilenames?.image_end
  const imageStartFile = Array.isArray(rawStart) ? (rawStart.find((f: string) => f) || null) : rawStart
  const imageEndFile = Array.isArray(rawEnd) ? (rawEnd.find((f: string) => f) || null) : rawEnd

  const handleSelect = useCallback(() => {
    if (isScene || isComic) {
      setComicOpenError('')
      void openOutputInEditor(file).catch(error => {
        console.error(`Failed to open ${file.type}:`, error)
        if (isComic) setComicOpenError(error instanceof Error ? error.message : String(error))
      })
      return
    }
    setSelectedOutput(index)
  }, [file, index, isComic, isScene, setSelectedOutput])

  const handleCopyReference = (event: ReactMouseEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    const markCopied = () => {
      setReferenceCopied(true)
      setTimeout(() => setReferenceCopied(false), 1500)
    }
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(outputReference).then(markCopied).catch(() => {
        const ta = document.createElement('textarea')
        ta.value = outputReference
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
        markCopied()
      })
      return
    }
    const ta = document.createElement('textarea')
    ta.value = outputReference
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    markCopied()
  }

  return (
    <React.Fragment>
    <div
      ref={itemRef}
      data-feed-index={index}
      style={cardStyle}
      className={`flex flex-col rounded-xl border-2 overflow-hidden transition-colors ${
        // Active frame: theme-aware bezel via frame-active-gradient.
        //
        // Default theme: linear gradient with both stops set to
        // accent-blue → reads as a flat 2px blue ring (preserves
        // prior visual exactly).
        //
        // HocusPocus Blue: a conic-gradient override (see index.css)
        // sweeps spotlight stops around the perimeter — electric blue
        // and cyan at three asymmetric angles, with deep blue in between
        // so those sections of the border
        // blend into the surrounding panel. The effect reads as
        // "cool stage lights catching the edge of the asset at random
        // points" rather than a uniform halo or solid line.
        //
        // shadow-active-ring is now minimal (just a 6px / 15% wash)
        // because the visual character lives ON the bezel itself,
        // not as an outward glow.
        isActive
          ? 'border-transparent frame-active-gradient shadow-active-ring'
          : 'border-border bg-bg-tertiary'
      }`}
      onClick={handleSelect}
    >
      {/* Media player */}
      <div
        data-testid="media-feed-viewport"
        className={`relative flex w-full shrink-0 items-center justify-center overflow-hidden bg-media-canvas ${isAudio ? 'py-4' : ''}`}
        style={{ height: mediaHeight }}
      >
        <button
          type="button"
          onClick={handleCopyReference}
          className="absolute top-2 left-2 z-10 flex items-center gap-1.5 rounded-md border border-white/20 bg-black/70 px-2 py-1 font-mono text-[10px] text-white shadow-sm transition-colors hover:bg-black/90"
          title={`Copy output ID ${outputReference}`}
          aria-label={`Copy output ID ${outputReference}`}
        >
          {referenceCopied ? <Check size={11} className="text-accent-green" /> : <Copy size={11} />}
          {outputReference}
        </button>
        <FeedMediaBody
          file={file}
          workspace={outputWorkspace}
          isActive={isActive}
          previewUrl={previewUrl}
          videoReady={videoReady}
          videoRef={videoRef}
          videoTime={videoTime}
          onVideoTimeChange={setVideoTime}
          onPlay={() => { setSelectedOutput(index); setVideoReady(true) }}
          onOpenDetails={() => onOpenDetails(index, { time: videoTime, onChange: setVideoTime })}
          isScene={isScene}
          isComic={isComic}
          isModel3d={isModel3d}
          canPreviewModel3d={canPreviewModel3d}
          isRigged={isRigged}
          riggedClips={riggedClips}
          activeClip={activeClip}
          setActiveClip={setActiveClip}
          retryImage={url => <RetryImage url={url} alt={file.name} color={file.color} />}
        />
        {comicOpenError && (
          <div role="alert" className="absolute inset-x-0 bottom-0 z-10 border-t border-red-500/30 bg-red-950/90 px-3 py-2 text-xs text-red-200">
            {t('comicOpenFailed', { error: comicOpenError })}
          </div>
        )}
      </div>

      {/* Inline info bar */}
      {/* Fixed-height info bar: three single-line rows of text and one row of
          actions. Every line truncates, so no line is ever half visible. */}
      <div className="flex h-[100px] shrink-0 flex-col gap-1 overflow-hidden px-3 py-1">
        <div className="flex h-12 min-w-0 items-center gap-2">
        {imageStartFile && file.type !== 'image' && file.type !== 'video' && (
          <img
            src={getStoredAssetUrl(imageStartFile)}
            alt="Start"
            className="w-7 h-7 rounded border border-border object-cover shrink-0"
            title="Start image"
          />
        )}
        {imageEndFile && file.type !== 'image' && file.type !== 'video' && (
          <img
            src={getStoredAssetUrl(imageEndFile)}
            alt="End"
            className="w-7 h-7 rounded border border-border object-cover shrink-0"
            title="End image"
          />
        )}

        <div className="min-w-0 flex-1 leading-4">
          {completionTime && (
            <div
              className="flex h-4 items-center gap-1 text-[10px] text-text-muted"
              title={`${completionLabel}: ${completionTime}${!browsingUploads && !completionTimeIsExact ? ' (file timestamp, approximate)' : ''}`}
            >
              <Clock3 size={10} className="shrink-0" aria-hidden="true" />
              <span className="truncate">
                {completionLabel} · {completionTime}
                {!browsingUploads && !completionTimeIsExact ? ' · aprox.' : ''}
              </span>
            </div>
          )}
          {params ? (
            <>
              <div className="h-4 truncate text-xs text-text-secondary" title={generationBreakdown || undefined}>
                {modelLabel && <span className="font-medium" title={modelType}>{modelLabel}</span>}
                {resolution && <span className="text-text-muted"> &middot; {resolution}</span>}
                {seed != null && seed >= 0 && <span className="text-text-muted"> &middot; seed {seed}</span>}
                {generationTime != null && (
                  <span className="text-text-muted"> &middot; total {formatGenerationDuration(generationTime)}</span>
                )}
                {clipIndex != null && clipTotal != null && (
                  <span className="text-accent-blue"> &middot; clip {clipIndex + 1}/{clipTotal}</span>
                )}
              </div>
              <div className="h-4 truncate text-[11px] text-text-muted" title={prompt || generationBreakdown || undefined}>
                {prompt || generationBreakdown}
              </div>
            </>
          ) : metaLoaded ? (
            <div className="h-4 truncate text-[11px] text-text-muted">{file.name}</div>
          ) : (
            <div className="h-4 text-[11px] text-text-muted animate-pulse">Loading...</div>
          )}
        </div>
        </div>

        <OutputActionBar
          file={file}
          index={index}
          params={params ?? null}
          getVideoElement={() => videoRef.current}
          getVideoTime={() => videoTime}
        />
      </div>
    </div>
    </React.Fragment>
  )
})
