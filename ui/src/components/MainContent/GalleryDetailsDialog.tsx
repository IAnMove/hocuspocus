import { useEffect, useMemo, useState } from 'react'
import ImagePreviewDialog from '../common/ImagePreviewDialog'
import type { OutputFile } from '../../types'

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

const previewable = (file: OutputFile | undefined) => file?.type === 'image' || file?.type === 'video'

/** The gallery's one details dialog. It steps through every image and video
 *  in the current list — including ones scrolled far out of the virtualized
 *  window — and warms the neighbours so the next step shows at once. */
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
  const order = useMemo(() => outputs.flatMap((file, index) => (previewable(file) ? [index] : [])), [outputs])
  const index = useMemo(() => outputs.findIndex(file => file.name === detail.name), [outputs, detail.name])
  const at = order.indexOf(index)
  const file = outputs[index]
  const previous = at > 0 ? order[at - 1] : undefined
  const next = at >= 0 && at < order.length - 1 ? order[at + 1] : undefined
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
    if (hasMore && at >= 0 && at >= order.length - 3) onNearEnd()
  }, [at, order.length, hasMore, onNearEnd])

  if (!file || !previewable(file)) return null
  const ownVideo = file.name === detail.origin ? detail.video : undefined
  return (
    <ImagePreviewDialog
      key={file.name}
      image={{ ...file, type: file.type as 'image' | 'video', workspace_id: workspace }}
      onClose={onClose}
      videoTime={ownVideo ? ownVideo.time : videoTimes.get(file.name)}
      onVideoTimeChange={seconds => {
        if (ownVideo) ownVideo.onChange(seconds)
        else videoTimes.set(file.name, seconds)
      }}
      navigation={{
        position: at + 1,
        total: hasMore ? `${order.length}+` : order.length,
        onPrevious: previous == null ? undefined : () => onNavigate(previous),
        onNext: next == null ? undefined : () => onNavigate(next),
      }}
    />
  )
}
