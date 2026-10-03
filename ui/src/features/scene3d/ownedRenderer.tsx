import { createRoot } from 'react-dom/client'
import '../../i18n'
import '../../index.css'
import { Scene3DStage, type Scene3DStageHandle } from './Scene3DStage'
import { parseScene3DDocument } from './document'
import { waitForWorld3DAssets } from './exportFlow'
import { startWorld3DExport, finishWorld3DExport, paintWorld3DExportFrame } from './exportLock'
import { scene3dPlaybackSpeed } from './clock'
import { paintSceneFx } from '../sceneFx/paint'
import { ensureTextFonts, paintKineticTexts, paintSceneLyrics } from '../../lib/kineticText'
import { paintClipNumber } from './performance'
import { mixSceneSpeech } from './speech/audio'
import { sceneAudioWavDataUrl } from '../sceneFx/audioExport'
import { FrameAccumulator, motionBlurOf, renderQualityOf, subframeTimes, type MotionBlur } from './exportQuality'
import type { Scene3DDocument } from './types'

/** The export plan: output size, plus the supersampling and MSAA of the quality level. */
type Size = { width: number; height: number; fps?: number; supersample?: number; samples?: number; subframes?: number; shutter?: number }
type Renderer = { load: (raw: unknown, size: Size) => Promise<void>; frame: (seconds: number) => Promise<string>; audio: () => Promise<string>; dispose: () => void }
declare global { interface Window { __world3dExport: Renderer } }

const root = createRoot(document.getElementById('root')!)
let stage: Scene3DStageHandle | null = null
let snapshot: Scene3DDocument | null = null
let blur: MotionBlur = motionBlurOf(null)
let fps = 30
const canvas = document.createElement('canvas')

/** Paint each subframe at the output size and average them; overlays are painted once, after. */
async function paintBlurred(context: CanvasRenderingContext2D, times: number[]) {
  const accumulator = new FrameAccumulator(canvas.width * canvas.height * 4)
  for (const time of times) {
    await stage!.prepareFrame?.(time, snapshot!)
    context.drawImage(paintWorld3DExportFrame(stage!, snapshot!, time), 0, 0, canvas.width, canvas.height)
    accumulator.add(context.getImageData(0, 0, canvas.width, canvas.height).data)
  }
  const image = context.createImageData(canvas.width, canvas.height)
  image.data.set(accumulator.result())
  context.putImageData(image, 0, 0)
}

window.__world3dExport = {
  async load(raw, size) {
    const scene = parseScene3DDocument(raw)
    if (!scene) throw new Error('Invalid World3D snapshot')
    root.render(<Scene3DStage ref={value => { stage = value }} document={scene} sceneSeconds={0} editing={false} />)
    const deadline = Date.now() + 25000
    while (!stage) {
      if (Date.now() > deadline) throw new Error('World3D stage did not mount')
      await new Promise(resolve => setTimeout(resolve, 20))
    }
    // Load props and resources before locking the stage for deterministic export.
    await waitForWorld3DAssets(stage, scene, 90000)
    await ensureTextFonts(scene.texts)
    snapshot = startWorld3DExport(stage, scene, size, renderQualityOf(size))
    blur = motionBlurOf(size)
    fps = size.fps ?? 30
    canvas.width = size.width
    canvas.height = size.height
    // Blurred frames read back every subframe; a sharp export keeps the default canvas.
    canvas.getContext('2d', { willReadFrequently: blur.subframes > 1 })
  },
  async frame(seconds) {
    if (!stage || !snapshot) throw new Error('Load a World3D snapshot first')
    const speed = scene3dPlaybackSpeed(snapshot.playbackSpeed)
    const time = seconds * speed
    const context = canvas.getContext('2d')!
    // A supersampled stage is larger than the output; scale it down with the high-quality filter.
    context.imageSmoothingQuality = 'high'
    if (blur.subframes > 1) {
      await paintBlurred(context, subframeTimes(time, blur, speed / fps, snapshot.duration))
    } else {
      await stage.prepareFrame?.(time, snapshot)
      context.drawImage(paintWorld3DExportFrame(stage, snapshot, time), 0, 0, canvas.width, canvas.height)
    }
    paintSceneFx(context, canvas.width, canvas.height, time, snapshot.sfx)
    paintKineticTexts(context, canvas.width, canvas.height, time, snapshot.texts)
    paintSceneLyrics(context, canvas.width, canvas.height, time, snapshot.lyrics)
    paintClipNumber(context, canvas.width, canvas.height, snapshot.clipNumber)
    return canvas.toDataURL('image/png')
  },
  /** The same mix as the browser export (voices, soundtrack, sound effects), as a WAV data URL; '' when silent. */
  async audio() {
    if (!snapshot) throw new Error('Load a World3D snapshot first')
    const buffer = await mixSceneSpeech(snapshot)
    return buffer ? sceneAudioWavDataUrl(buffer) : ''
  },
  dispose() {
    if (stage && snapshot) finishWorld3DExport(stage)
    root.unmount()
    snapshot = null
  },
}
