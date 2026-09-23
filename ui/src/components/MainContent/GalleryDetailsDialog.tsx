import { useEffect, useMemo, useState } from 'react'
import { BookOpen, Box, ExternalLink, Film, Music } from 'lucide-react'
import ImagePreviewDialog from '../common/ImagePreviewDialog'
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
      media={visual ? undefined : <OtherMedia file={file} onOpened={onClose} />}
      actions={
        <OutputActionBar
          file={file}
          index={index}
          variant="dialog"
          getVideoTime={videoTime}
          // Deleting or moving the item steps to its neighbour instead of
          // leaving an empty dialog.
          onBeforeRemove={() => {
            if (next != null) onNavigate(next)
            else if (previous != null) onNavigate(previous)
            else onClose()
          }}
        />
      }
      navigation={{
        position: index + 1,
        total: hasMore ? `${outputs.length}+` : outputs.length,
        onPrevious: previous == null ? undefined : () => onNavigate(previous),
        onNext: next == null ? undefined : () => onNavigate(next),
      }}
    />
  )
}
