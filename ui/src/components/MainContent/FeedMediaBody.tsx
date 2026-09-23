import React, { useState, type ReactNode, type RefObject } from 'react'
import { BookOpen, Box, Film, Play } from 'lucide-react'
import { getFileUrl } from '../../api/client'
import type { OutputFile } from '../../types'
import { ImagePreview } from '../common/ImagePreview'

// The card's media box has a fixed height; every preview is contained in it.
const MEDIA_FIT = 'block h-full w-full object-contain'

type FeedMediaBodyProps = {
  file: OutputFile
  workspace?: string
  isActive: boolean
  /** Aspect-preserving preview for images and videos; saved scenes, comics
   *  and 3D models pass their own preview image. */
  previewUrl: string | null
  videoReady: boolean
  videoRef: RefObject<HTMLVideoElement | null>
  videoTime?: number
  onVideoTimeChange?: (seconds: number) => void
  onPlay: () => void
  /** Open the gallery's details dialog for this item. */
  onOpenDetails: () => void
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

function FeedVideoPreview({ file, workspace, previewUrl, videoTime, onVideoTimeChange, onOpenDetails }: {
  file: OutputFile; workspace?: string; previewUrl: string | null; videoTime?: number; onVideoTimeChange?: (seconds: number) => void; onOpenDetails: () => void
}) {
  return (
    <ImagePreview image={{ ...file, type: 'video', workspace_id: workspace }} videoTime={videoTime} onVideoTimeChange={onVideoTimeChange} onOpenDialog={onOpenDetails} className="relative block h-full w-full cursor-zoom-in">
      {previewUrl ? (
        <PlaceholderImage src={previewUrl} alt={file.name} color={file.color} />
      ) : (
        <span className="flex h-full w-full items-center justify-center text-text-muted"><Film size={32} /></span>
      )}
      <span aria-hidden="true" className="pointer-events-none absolute left-1/2 top-1/2 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/30 bg-black/70 text-white shadow-xl">
        <Play size={24} className="ml-1" />
      </span>
    </ImagePreview>
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

/** Paints the output's average colour until its preview has decoded. */
function PlaceholderImage({ src, alt, color }: { src: string; alt: string; color?: string }) {
  const [loaded, setLoaded] = useState<string | null>(null)
  return <img src={src} alt={alt} className="h-full w-full object-contain" loading="lazy" decoding="async"
    style={loaded === src || !color ? undefined : { backgroundColor: color }} onLoad={() => setLoaded(src)} />
}

export function FeedMediaBody(props: FeedMediaBodyProps) {
  return <React.Fragment>{renderFeedMedia(props)}</React.Fragment>
}

function renderFeedMedia({
  file, isActive, previewUrl,
  isScene, isComic, isModel3d, canPreviewModel3d, isRigged, riggedClips, activeClip, setActiveClip,
  retryImage, workspace, videoTime, onVideoTimeChange, onOpenDetails,
}: FeedMediaBodyProps) {
  if (file.type === 'video') {
    return <FeedVideoPreview file={file} workspace={workspace} previewUrl={previewUrl} videoTime={videoTime} onVideoTimeChange={onVideoTimeChange} onOpenDetails={onOpenDetails} />
  }
  if (file.type === 'audio') {
    return (
      <div className="flex w-full min-w-0 flex-col items-center gap-4 px-4">
        <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-bg-active">
          <Play size={24} className="text-text-muted" />
        </div>
        <p className="mb-2 max-w-full truncate text-xs text-text-muted" title={file.name}>{file.name}</p>
        <audio key={file.url} src={file.url} controls className="w-64 max-w-full" />
      </div>
    )
  }
  if (isScene) {
    return file.thumbnail_url
      ? <img src={file.thumbnail_url} alt={file.name} className={MEDIA_FIT} loading="lazy" decoding="async" />
      : <div className="flex flex-col items-center gap-2 text-text-muted"><Film size={28} /><span className="text-xs">Saved scene</span></div>
  }
  if (isComic) {
    return file.thumbnail_url
      ? <img src={file.thumbnail_url} alt={file.name} className={MEDIA_FIT} loading="lazy" decoding="async" />
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
  return <ImagePreview image={{ ...file, type: 'image', workspace_id: workspace }} onOpenDialog={onOpenDetails} className="block h-full w-full cursor-zoom-in">
    {retryImage(previewUrl || file.url)}
  </ImagePreview>
}
