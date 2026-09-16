import { saveSceneRecording } from '../../api/video3d.ts'
import type { Scene } from '../../types'
import { encodeWorld3DFrames, world3dExportSize } from '../scene3d/exportMp4.ts'
import { videoJsDuration } from './document.ts'
import type { VideoJsSandbox } from './sandbox.ts'
import type { VideoJsDocument, VideoJsSceneError } from './types.ts'

export class VideoJsExportError extends Error {
  readonly sceneError: VideoJsSceneError

  constructor(sceneError: VideoJsSceneError) {
    super(sceneError.message)
    this.name = 'VideoJsExportError'
    this.sceneError = sceneError
  }
}

/** Renders every frame through the same sandbox used by preview. A scene
 *  error aborts the export instead of publishing an error card in the MP4. */
export async function renderVideoJsMp4(sandbox: VideoJsSandbox, document: VideoJsDocument, options: {
  onProgress?: (current: number, total: number) => void
  signal?: AbortSignal
} = {}): Promise<Blob> {
  const canvas = globalThis.document.createElement('canvas')
  canvas.width = document.width
  canvas.height = document.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('Canvas 2D is unavailable')
  return encodeWorld3DFrames({
    width: document.width,
    height: document.height,
    fps: document.fps,
    duration: videoJsDuration(document),
    signal: options.signal,
    onProgress: options.onProgress,
    paint: async seconds => {
      const { bitmap, errors } = await sandbox.frame(seconds)
      try {
        if (errors.length) throw new VideoJsExportError(errors[0])
        context.clearRect(0, 0, canvas.width, canvas.height)
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
      } finally {
        bitmap.close()
      }
      return canvas
    },
  })
}

export function videoJsRecordingName(document: VideoJsDocument): string {
  const slug = document.title.normalize('NFKD').replace(/[^\w-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48).toLowerCase()
  return `videojs-${slug || 'video'}`
}

export function publishVideoJsRecording(blob: Blob, document: VideoJsDocument, workspace?: string) {
  const size = world3dExportSize(document.width, document.height)
  const scene = {
    version: 1,
    name: videoJsRecordingName(document),
    width: size.width,
    height: size.height,
    fps: document.fps,
    duration: videoJsDuration(document),
    layers: [],
  } as unknown as Scene
  return saveSceneRecording(blob, {
    scene,
    embeddedAudio: false,
    prompt: document.prompt,
    // The full document makes the MP4 explainable and reproducible from its sidecar.
    recipe: { engine: 'videojs', schema: document.schema, document },
    workspace,
  })
}
