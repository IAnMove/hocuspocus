/** What an export needs from a video element: whether it is still seeking and whether it holds a current frame. */
export type SettlingVideo = Pick<HTMLVideoElement, 'seeking' | 'readyState' | 'addEventListener' | 'removeEventListener'>

/**
 * Resolves once every video shows the frame it was sought to, or after ``timeoutMs``. An export sets each video's
 * time and then paints; the painter skips a video with no current frame (``readyState`` under 2), so painting before
 * the seek lands drops the video layer from that frame — a video background vanished from editor MP4s.
 */
export function videosSettled(videos: readonly SettlingVideo[], timeoutMs = 5000): Promise<void> {
  return Promise.all(videos.map(video => new Promise<void>(resolve => {
    if (!video.seeking && video.readyState >= 2) { resolve(); return }
    const done = () => {
      video.removeEventListener('seeked', done)
      video.removeEventListener('loadeddata', done)
      clearTimeout(timer)
      resolve()
    }
    video.addEventListener('seeked', done)
    video.addEventListener('loadeddata', done)
    const timer = setTimeout(done, timeoutMs)
  }))).then(() => undefined)
}
