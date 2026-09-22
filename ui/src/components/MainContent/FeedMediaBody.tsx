import React, { useCallback, type ReactNode, type RefObject, type SyntheticEvent } from 'react'
import { BookOpen, Box, Film, Play } from 'lucide-react'
import { getFileUrl } from '../../api/client'
import type { OutputFile } from '../../types'
import { ImagePreview } from '../common/ImagePreview'

const MEDIA_FIT = 'mx-auto block h-auto w-auto max-w-full object-contain'

type FeedMediaBodyProps = {
  file: OutputFile
  workspace?: string
  isActive: boolean
  maxMediaHeight?: number
  videoReady: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  onPlay: () => void
  onIntrinsicSize: (width: number, height: number) => void
  onImageLoad: (event: SyntheticEvent<HTMLImageElement>) => void
  isScene: boolean
  isComic: boolean
  isModel3d: boolean
  canPreviewModel3d: boolean
  isRigged: boolean
  riggedClips: string[]
  activeClip: string | null
  setActiveClip: (clip: string) => void
  retryImage: (url: string) => ReactNode
}

function FeedVideoPreview({
  file, isActive, maxHeight, videoReady, videoRef, onPlay, onIntrinsicSize, onImageLoad,
}: {
  file: OutputFile
  isActive: boolean
  maxHeight?: { maxHeight: number }
  videoReady: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  onPlay: () => void
  onIntrinsicSize: (width: number, height: number) => void
  onImageLoad: (event: SyntheticEvent<HTMLImageElement>) => void
}) {
  const play = useCallback((event: SyntheticEvent<HTMLButtonElement>) => {
    event.stopPropagation()
    onPlay()
  }, [onPlay])
  if (videoReady) {
    return (
      <video
        ref={videoRef}
        key={file.url}
        src={file.url}
        controls
        loop
        autoPlay
        preload="metadata"
        poster={file.thumbnail_url || undefined}
        className={MEDIA_FIT}
        style={maxHeight}
        muted={!isActive}
        onLoadedMetadata={event => {
          const video = event.currentTarget
          onIntrinsicSize(video.videoWidth, video.videoHeight)
        }}
      />
    )
  }
  return (
    <div className="relative mx-auto inline-block max-w-full">
      {file.thumbnail_url ? (
        <img
          src={file.thumbnail_url}
          alt={file.name}
          className={MEDIA_FIT}
          style={maxHeight}
          loading="lazy"
          decoding="async"
          onLoad={onImageLoad}
        />
      ) : (
        <div className="flex h-48 w-full items-center justify-center text-text-muted"><Film size={32} /></div>
      )}
      <button
        type="button"
        onClick={play}
        className="absolute left-1/2 top-1/2 z-10 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-black/70 text-white shadow-xl transition-transform hover:scale-105 hover:bg-black/85"
        aria-label={`Play ${file.name}`}
        title="Load and play video"
      >
        <Play size={24} className="ml-1" />
      </button>
    </div>
  )
}

function FeedModel3dPreview({
  file, isActive, canPreviewModel3d, isRigged, riggedClips, activeClip, setActiveClip,
}: {
  file: OutputFile
  isActive: boolean
  canPreviewModel3d: boolean
  isRigged: boolean
  riggedClips: string[]
  activeClip: string | null
  setActiveClip: (clip: string) => void
}) {
  let preview: ReactNode
  if (canPreviewModel3d && isActive) {
    preview = (
      <model-viewer
        key={file.url}
        src={getFileUrl(file.name)}
        alt={file.name}
        camera-controls
        auto-rotate={isRigged ? undefined : true}
        autoplay={isRigged ? true : undefined}
        animation-name={isRigged && activeClip ? activeClip : undefined}
        shadow-intensity="1"
        exposure="1"
        loading="lazy"
        className="h-full w-full"
      />
    )
  } else if (canPreviewModel3d && file.thumbnail_url) {
    preview = <img src={file.thumbnail_url} alt={file.name} className="h-full w-full object-contain" loading="lazy" />
  } else {
    preview = (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 px-4 text-center">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-bg-active"><Box size={26} className="text-accent-blue" /></div>
        <div>
          <p className="text-sm text-text-secondary">3D model asset</p>
          <p className="mt-1 text-[11px] text-text-muted">{canPreviewModel3d ? 'Select this card to open the interactive GLB preview.' : 'Interactive preview is available for GLB exports.'}</p>
        </div>
      </div>
    )
  }
  return (
    <div className="relative h-full w-full">
      {preview}
      <a href={getFileUrl(file.name)} download={file.name} className="absolute right-2 top-2 rounded-lg border border-white/20 bg-black/60 px-2.5 py-1.5 text-[10px] text-white transition-colors hover:bg-black/80">Download</a>
      {isRigged && riggedClips.length > 0 && (
        <select value={activeClip ?? riggedClips[0]} onChange={event => setActiveClip(event.target.value)} className="absolute bottom-2 left-2 rounded-lg border border-white/20 bg-black/60 px-2 py-1 text-[10px] text-white" title="Animation clip">
          {riggedClips.map(clip => <option key={clip} value={clip}>{clip}</option>)}
        </select>
      )}
    </div>
  )
}

export function FeedMediaBody(props: FeedMediaBodyProps) {
  return <React.Fragment>{renderFeedMedia(props)}</React.Fragment>
}

function renderFeedMedia({
  file, isActive, maxMediaHeight, videoReady, videoRef, onPlay, onIntrinsicSize, onImageLoad,
  isScene, isComic, isModel3d, canPreviewModel3d, isRigged, riggedClips, activeClip, setActiveClip,
  retryImage, workspace,
}: FeedMediaBodyProps) {
  const maxHeight = maxMediaHeight == null ? undefined : { maxHeight: maxMediaHeight }
  if (file.type === 'video') {
    return (
      <FeedVideoPreview
        file={file}
        isActive={isActive}
        maxHeight={maxHeight}
        videoReady={videoReady}
        videoRef={videoRef}
        onPlay={onPlay}
        onIntrinsicSize={onIntrinsicSize}
        onImageLoad={onImageLoad}
      />
    )
  }
  if (file.type === 'audio') {
    return (
      <div className="flex flex-col items-center gap-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-bg-active">
          <Play size={24} className="text-text-muted" />
        </div>
        <p className="mb-2 text-xs text-text-muted">{file.name}</p>
        <audio key={file.url} src={file.url} controls className="w-64" />
      </div>
    )
  }
  if (isScene) {
    return file.thumbnail_url
      ? <img src={file.thumbnail_url} alt={file.name} className={MEDIA_FIT} style={maxHeight} onLoad={onImageLoad} />
      : <div className="flex flex-col items-center gap-2 text-text-muted"><Film size={28} /><span className="text-xs">Saved scene</span></div>
  }
  if (isComic) {
    return file.thumbnail_url
      ? <img src={file.thumbnail_url} alt={file.name} className={MEDIA_FIT} style={maxHeight} onLoad={onImageLoad} />
      : <div className="flex flex-col items-center gap-2 text-text-muted"><BookOpen size={28} /><span className="text-xs">Saved comic</span></div>
  }
  if (isModel3d) {
    return (
      <FeedModel3dPreview
        file={file}
        isActive={isActive}
        canPreviewModel3d={canPreviewModel3d}
        isRigged={isRigged}
        riggedClips={riggedClips}
        activeClip={activeClip}
        setActiveClip={setActiveClip}
      />
    )
  }
  return <ImagePreview image={{ ...file, workspace_id: workspace }} className="block max-w-full cursor-zoom-in">
    {retryImage(isActive ? file.url : (file.thumbnail_url || file.url))}
  </ImagePreview>
}
