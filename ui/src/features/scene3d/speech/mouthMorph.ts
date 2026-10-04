import { CanvasTexture, LinearFilter, SRGBColorSpace, type Texture } from 'three'
import { mouthContourMesh, renderMouthMorph, type MouthMorphFrame } from '../../../lib/lipsMorph'
import { VISEMES } from './types'

function surface(size: number, columns = 1) {
  const canvas = document.createElement('canvas')
  canvas.width = size * columns; canvas.height = size
  return canvas
}

function atlasFrames(image: CanvasImageSource, size: number): MouthMorphFrame[] {
  return VISEMES.map((_, index) => {
    const canvas = surface(size), context = canvas.getContext('2d', { willReadFrequently: true })!
    context.drawImage(image, index * size, 0, size, size, 0, 0, size, size)
    return { image: canvas, mesh: mouthContourMesh(context.getImageData(0, 0, size, size).data, size, size) }
  })
}

/** The Lips Creator contour warp, sampled from the scene clock instead of wall time. */
export class MouthAtlasMorph {
  readonly texture: CanvasTexture
  private readonly frames: MouthMorphFrame[]
  private readonly context: CanvasRenderingContext2D
  private readonly layers: readonly [HTMLCanvasElement, HTMLCanvasElement]
  private lastPose = ''

  constructor(atlas: Texture) {
    const image = atlas.image as CanvasImageSource & { height: number }
    const size = image.height, canvas = surface(size, VISEMES.length)
    this.frames = atlasFrames(image, size)
    this.context = canvas.getContext('2d')!
    this.layers = [surface(size), surface(size)]
    // Keep the native nine-column shader contract; the moving drawing uses tile zero.
    this.texture = new CanvasTexture(canvas)
    this.texture.colorSpace = SRGBColorSpace
    this.texture.minFilter = LinearFilter; this.texture.magFilter = atlas.magFilter
    this.texture.generateMipmaps = false
  }

  sample(pose: { a: number; b: number; mix: number }) {
    const key = `${pose.a}:${pose.b}:${pose.mix}`
    if (key === this.lastPose) return
    renderMouthMorph(this.context, this.frames[pose.a], this.frames[pose.b], pose.mix, this.layers)
    this.texture.needsUpdate = true; this.lastPose = key
  }

  dispose() { this.texture.dispose() }
}
