import { useEffect, useMemo, useState } from 'react'
import { ArrowLeftRight, BookOpen, Box, Columns2, ExternalLink, Film, Music, X } from 'lucide-react'
import ImagePreviewDialog from '../common/ImagePreviewDialog'
import { ZoomableImage } from '../common/ZoomableImage'
import { useUiTranslation } from '../../i18n'
import type { OutputFile } from '../../types'
import { OutputActionBar } from './OutputActionBar'
import { openOutputInEditor } from './openOutputEditor'

/** A card that opens details hands over its own seek position, so a frame
 *  picked in the dialog is still the one its "send frame" action captures. */
export interface DetailVideoTime {
  time: number
  onChange: (seconds: number) => void
}

export interface GalleryDetail {
  /** Output shown. Tracked by name so new outputs arriving above it while
   *  the dialog is open do not swap the picture under the reader. */
  name: string
  /** Output the dialog was opened from, and that card's seek state. */
  origin: string
  video?: DetailVideoTime
  /** Open side by side with this image (from a two-image selection). */
  compare?: string
}

const KIND_ICON = { audio: Music, model3d: Box, scene: Film, comic: BookOpen } as const

/** Preview for outputs that are not a picture or a clip: a player for audio,
 *  the saved preview for scenes, comics and 3D, and a way into their editor. */
function OtherMedia({ file, onOpened }: { file: OutputFile; onOpened: () => void }) {
  const { t } = useUiTranslation('common')
  const [error, setError] = useState('')
  const Icon = KIND_ICON[file.type as keyof typeof KIND_ICON] ?? Film
  const editable = file.type === 'scene' || file.type === 'comic'
  return (
    <div className="flex w-full flex-col items-center gap-3 p-4 text-center">
      {file.type === 'audio' ? (
        <>
          <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-bg-active"><Icon size={26} className="text-text-muted" /></span>
          <audio key={file.url} src={file.url} controls className="w-full max-w-md" />
        </>
      ) : file.thumbnail_url ? (
        <img src={file.thumbnail_url} alt={file.name} className="block max-h-[50dvh] max-w-full object-contain" />
      ) : (
        <span className="flex flex-col items-center gap-2 text-sm text-text-muted"><Icon size={32} />{t('imagePreview.noPreview')}</span>
      )}
      {editable && (
        <button type="button" className="flex min-h-11 items-center gap-2 rounded-lg border border-border px-3 text-sm hover:bg-bg-hover"
          onClick={() => {
            setError('')
            openOutputInEditor(file).then(onOpened).catch(reason => setError(reason instanceof Error ? reason.message : String(reason)))
          }}>
          <ExternalLink size={15} />{t('imagePreview.openInEditor')}
        </button>
      )}
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
    </div>
  )
}

/** Two images side by side (stacked on a phone), each zoomable on its own.
 *  A stays put; B is the one that stepping and swiping change. */
function CompareMedia({ a, b, onSwipe }: { a: OutputFile; b: OutputFile; onSwipe: (direction: 'previous' | 'next') => void }) {
  return (
    <div data-testid="compare-view" className="grid w-full grid-rows-2 gap-2 md:grid-cols-2 md:grid-rows-1">
      {[a, b].map((file, side) => (
        <figure key={`${side}:${file.name}`} className="flex min-h-0 min-w-0 flex-col items-center justify-center gap-1">
          <ZoomableImage src={file.url} alt={file.name} onSwipe={side === 1 ? onSwipe : undefined}
            className="block max-h-[27dvh] max-w-full object-contain md:max-h-[min(70dvh,calc(100dvh-13rem))]" />
          <figcaption className="max-w-full truncate text-[11px] text-text-muted" title={file.name}>
            <span className="mr-1 font-semibold text-text-secondary">{side === 0 ? 'A' : 'B'}</span>{file.name}
          </figcaption>
        </figure>
      ))}
    </div>
  )
}

/** Side-by-side state: which image is B, and where stepping would move it. */
function useCompare(outputs: OutputFile[], index: number, initial: string | undefined) {
  const [compareName, setCompareName] = useState<string | null>(initial ?? null)
  const images = useMemo(() => outputs.flatMap((item, at) => (item.type === 'image' ? [at] : [])), [outputs])
  const compareIndex = compareName ? outputs.findIndex(item => item.name === compareName) : -1
  const comparing = compareIndex >= 0 && compareIndex !== index && outputs[index]?.type === 'image'
  /** The image B lands on when stepping, never the one pinned as A. */
  const step = (direction: -1 | 1): number | undefined => {
    if (!comparing) return undefined
    let at = images.indexOf(compareIndex) + direction
    if (images[at] === index) at += direction
    return images[at]
  }
  const start = outputs[index]?.type === 'image'
    ? images.find(at => at > index) ?? [...images].reverse().find(at => at < index)
    : undefined
  const show = (at: number | undefined) => { if (at != null) setCompareName(outputs[at].name) }
  return { images, compareIndex, comparing, previous: step(-1), next: step(1), start, show, stop: () => setCompareName(null), setCompareName }
}

function CompareControls({ compare, current, onSwap }: {
  compare: ReturnType<typeof useCompare>
  current: OutputFile
  onSwap: () => void
}) {
  const { t } = useUiTranslation('common')
  const button = 'flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary'
  if (compare.comparing) {
    return <>
      <button type="button" className={button} onClick={() => { compare.setCompareName(current.name); onSwap() }}>
        <ArrowLeftRight size={15} />{t('imagePreview.swap')}
      </button>
      <button type="button" className={button} onClick={compare.stop}><X size={15} />{t('imagePreview.stopCompare')}</button>
      <span className="text-[11px] text-text-muted">{t('imagePreview.compareHint')}</span>
    </>
  }
  if (compare.start == null) return null
  return <button type="button" className={button} onClick={() => compare.show(compare.start)}>
    <Columns2 size={15} />{t('imagePreview.compare')}
  </button>
}

/** The gallery's one details dialog, the same in all three views. It steps
 *  through every output in the current list — including ones scrolled far out
 *  of the virtualized window — offers the full action set of a one-up card,
 *  and warms the neighbouring images so the next step shows at once. */
export default function GalleryDetailsDialog({ outputs, hasMore, detail, workspace, onNavigate, onNearEnd, onClose }: {
  outputs: OutputFile[]
  /** More pages exist on the server beyond `outputs`. */
  hasMore: boolean
  detail: GalleryDetail
  workspace: string
  onNavigate: (index: number) => void
  onNearEnd: () => void
  onClose: () => void
}) {
  const { t } = useUiTranslation('common')
  const index = useMemo(() => outputs.findIndex(file => file.name === detail.name), [outputs, detail.name])
  const file = outputs[index]
  const previous = index > 0 ? index - 1 : undefined
  const next = index >= 0 && index < outputs.length - 1 ? index + 1 : undefined
  const compare = useCompare(outputs, index, detail.compare)
  // Seek positions for videos reached by stepping rather than from their card.
  // Read only when a video mounts, so updating it needs no re-render.
  const [videoTimes] = useState(() => new Map<string, number>())

  useEffect(() => {
    for (const neighbour of [previous, next]) {
      const candidate = neighbour == null ? undefined : outputs[neighbour]
      if (candidate?.type === 'image') new Image().src = candidate.url
    }
  }, [outputs, previous, next])

  useEffect(() => {
    if (hasMore && index >= 0 && index >= outputs.length - 3) onNearEnd()
  }, [index, outputs.length, hasMore, onNearEnd])

  if (!file) return null
  const visual = file.type === 'image' || file.type === 'video'
  const ownVideo = file.name === detail.origin ? detail.video : undefined
  const videoTime = () => (ownVideo ? ownVideo.time : videoTimes.get(file.name) ?? 0)
  return (
    <ImagePreviewDialog
      key={file.name}
      image={{ ...file, type: file.type === 'video' ? 'video' : 'image', workspace_id: workspace }}
      title={visual ? undefined : t('imagePreview.outputTitle')}
      onClose={onClose}
      videoTime={ownVideo ? ownVideo.time : videoTimes.get(file.name)}
      onVideoTimeChange={seconds => {
        if (ownVideo) ownVideo.onChange(seconds)
        videoTimes.set(file.name, seconds)
      }}
      media={compare.comparing
        ? <CompareMedia a={file} b={outputs[compare.compareIndex]} onSwipe={direction => compare.show(direction === 'next' ? compare.next : compare.previous)} />
        : visual ? undefined : <OtherMedia file={file} onOpened={onClose} />}
      actions={<div className="flex flex-wrap items-center gap-1">
        <CompareControls compare={compare} current={file} onSwap={() => onNavigate(compare.compareIndex)} />
        <OutputActionBar
          file={file}
          index={index}
          variant="dialog"
          getVideoTime={videoTime}
          // Deleting or moving the item steps to its neighbour instead of
          // leaving an empty dialog.
          onBeforeRemove={() => {
            compare.stop()
            if (next != null) onNavigate(next)
            else if (previous != null) onNavigate(previous)
            else onClose()
          }}
        />
      </div>}
      navigation={compare.comparing ? {
        // While comparing, stepping moves B through the images only.
        position: compare.images.indexOf(compare.compareIndex) + 1,
        total: compare.images.length,
        onPrevious: compare.previous == null ? undefined : () => compare.show(compare.previous),
        onNext: compare.next == null ? undefined : () => compare.show(compare.next),
      } : {
        position: index + 1,
        total: hasMore ? `${outputs.length}+` : outputs.length,
        onPrevious: previous == null ? undefined : () => onNavigate(previous),
        onNext: next == null ? undefined : () => onNavigate(next),
      }}
    />
  )
}
