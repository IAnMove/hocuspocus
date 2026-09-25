import { CanvasTexture, DoubleSide, Mesh, MeshBasicMaterial, SRGBColorSpace, type Object3D } from 'three'
import { mediaScreenRect, type MediaScreen } from '../mediaScreen.ts'
import { SCREEN_PLANE_NAME, attachScreenPlane, detachScreenPlane, screenUsesPlane } from '../screenPlane.ts'
import { EXPRESSIONS, VISEMES, type Scene3DSpeech } from './types'
import { expressionAt, mouthAt } from './track'

export const FACE_PACK_COLS = VISEMES.length
export const FACE_PACK_ROWS = EXPRESSIONS.length

export function facePackCell(viseme: number, expression: number, width: number, height: number) {
  const tileW = width / FACE_PACK_COLS, tileH = height / FACE_PACK_ROWS
  return { sx: viseme * tileW, sy: expression * tileH, sw: tileW, sh: tileH }
}

export function validFacePackSize(width: number, height: number) {
  return width > 0 && height > 0 && width * FACE_PACK_ROWS === height * FACE_PACK_COLS && height / FACE_PACK_ROWS <= 256
}

export const FACE_PACK_SCREEN_ERROR = 'Face pack needs a screen plane on the head.'

export class FacePackRuntime {
  ready = false
  error?: Error
  private revision = 0
  private key = ''
  private last = ''
  private image?: HTMLImageElement
  private canvas?: HTMLCanvasElement
  private context?: CanvasRenderingContext2D
  private texture?: CanvasTexture
  private material?: MeshBasicMaterial
  private plane?: Mesh
  private previous?: Mesh['material']
  private attached = false
  private root?: Object3D
  private readonly redraw: () => void
  constructor(redraw: () => void = () => {}) {
    this.redraw = redraw
  }

  private clear() {
    this.revision++
    this.ready = false
    this.error = undefined
    this.image = undefined
    this.last = ''
    if (this.plane && this.previous) this.plane.material = this.previous
    this.material?.dispose()
    this.texture?.dispose()
    if (this.attached && this.root && this.plane) detachScreenPlane(this.root, this.plane)
    this.material = undefined
    this.texture = undefined
    this.canvas = undefined
    this.context = undefined
    this.plane = undefined
    this.previous = undefined
    this.attached = false
    this.root = undefined
  }

  private attach(root: Object3D, speech: Scene3DSpeech, screen: MediaScreen) {
    const plane = screenUsesPlane(screen, false)
    let mesh: Mesh | undefined
    try {
      mesh = plane ? attachScreenPlane(root, screen) : undefined
    } catch (error) {
      this.error = error instanceof Error && error.message.startsWith('screen-anchor')
        ? new Error(FACE_PACK_SCREEN_ERROR)
        : error instanceof Error ? error : new Error(FACE_PACK_SCREEN_ERROR)
      return
    }
    const targets: Mesh[] = []
    const name = plane ? SCREEN_PLANE_NAME : screen.targetMesh
    root.traverse(child => { if (child instanceof Mesh && child.name === name) targets.push(child) })
    const target = mesh ?? (targets.length === 1 ? targets[0] : undefined)
    if (!target) { this.error = new Error(FACE_PACK_SCREEN_ERROR); return }
    const canvas = document.createElement('canvas')
    canvas.width = 256
    canvas.height = 256
    const context = canvas.getContext('2d')
    if (!context) { this.error = new Error('Face pack canvas is unavailable.'); return }
    const texture = new CanvasTexture(canvas)
    texture.colorSpace = SRGBColorSpace
    texture.flipY = plane ? !screen.flipY : screen.flipY
    texture.generateMipmaps = false
    const material = new MeshBasicMaterial({ map: texture, toneMapped: false, side: DoubleSide })
    this.root = root
    this.plane = target
    this.previous = target.material
    this.attached = Boolean(mesh)
    this.canvas = canvas
    this.context = context
    this.texture = texture
    this.material = material
    target.material = material
    context.fillStyle = '#11161c'
    context.fillRect(0, 0, canvas.width, canvas.height)
    texture.needsUpdate = true
    const revision = this.revision
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      if (revision !== this.revision) return
      if (!validFacePackSize(image.naturalWidth, image.naturalHeight)) {
        this.error = new Error('Face pack must be 9 viseme columns by 6 expression rows (max 256 px tiles).')
        return
      }
      this.image = image
      this.ready = true
      this.redraw()
    }
    image.onerror = () => { if (revision === this.revision) this.error = new Error('Face pack could not be loaded.') }
    image.src = speech.facePack!.url
  }

  private paint(speech: Scene3DSpeech, seconds: number) {
    const image = this.image, context = this.context, canvas = this.canvas
    if (!image || !context || !canvas) return
    const viseme = mouthAt(speech, seconds).b
    const expression = EXPRESSIONS.indexOf(expressionAt(speech, seconds))
    const key = `${viseme}:${expression}`
    if (key === this.last) return
    this.last = key
    const cell = facePackCell(viseme, Math.max(0, expression), image.naturalWidth, image.naturalHeight)
    const rect = mediaScreenRect(canvas.width, canvas.height, cell.sw, cell.sh, 'cover')
    context.fillStyle = '#04060a'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, cell.sx, cell.sy, cell.sw, cell.sh, rect.x, rect.y, rect.width, rect.height)
    if (this.texture) this.texture.needsUpdate = true
    this.redraw()
  }

  sync(root: Object3D, speech: Scene3DSpeech | undefined, screen: MediaScreen | undefined, seconds: number) {
    const url = speech?.enabled && speech.facePack?.url
    const key = !url ? '' : screen
      ? `${url}|${screen.anchor}|${screen.width}|${screen.height}|${screen.flipY}`
      : `${url}|missing-screen`
    if (key !== this.key) {
      this.clear()
      this.key = key
      if (url && screen && speech) this.attach(root, speech, screen)
      else if (url) this.error = new Error(FACE_PACK_SCREEN_ERROR)
    }
    if (this.ready && speech) this.paint(speech, seconds)
  }

  dispose() { this.clear(); this.key = '' }
}
