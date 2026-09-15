import { createRoot } from 'react-dom/client'
import '../../i18n'
import '../../index.css'
import { Scene3DStage, type Scene3DStageHandle } from './Scene3DStage'
import { parseScene3DDocument } from './document'
import { waitForWorld3DAssets } from './exportFlow'
import { startWorld3DExport, finishWorld3DExport, paintWorld3DExportFrame } from './exportLock'
import { scene3dPlaybackSpeed } from './clock'
import { paintSceneFx } from '../sceneFx/paint'
import { paintKineticTexts } from '../../lib/kineticText'
import { paintClipNumber } from './performance'
import type { Scene3DDocument } from './types'

type Size = { width: number; height: number }
type Renderer = { load: (raw: unknown, size: Size) => Promise<void>; frame: (seconds: number) => Promise<string>; dispose: () => void }
declare global { interface Window { __world3dExport: Renderer } }

const root = createRoot(document.getElementById('root')!)
let stage: Scene3DStageHandle | null = null
let snapshot: Scene3DDocument | null = null
const canvas = document.createElement('canvas')

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
    snapshot = startWorld3DExport(stage, scene, size)
    canvas.width = size.width
    canvas.height = size.height
  },
  async frame(seconds) {
    if (!stage || !snapshot) throw new Error('Load a World3D snapshot first')
    const time = seconds * scene3dPlaybackSpeed(snapshot.playbackSpeed)
    await stage.prepareFrame?.(time, snapshot)
    const source = paintWorld3DExportFrame(stage, snapshot, time)
    const context = canvas.getContext('2d')!
    context.drawImage(source, 0, 0, canvas.width, canvas.height)
    paintSceneFx(context, canvas.width, canvas.height, time, snapshot.sfx)
    paintKineticTexts(context, canvas.width, canvas.height, time, snapshot.texts)
    paintClipNumber(context, canvas.width, canvas.height, snapshot.clipNumber)
    return canvas.toDataURL('image/png')
  },
  dispose() {
    if (stage && snapshot) finishWorld3DExport(stage)
    root.unmount()
    snapshot = null
  },
}
