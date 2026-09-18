import { Mesh, MeshStandardMaterial, SRGBColorSpace, TextureLoader, type BufferGeometry, type Object3D, type Texture } from 'three'
import { EXPRESSIONS, blinkAt } from './eyes'
import { createAtlas, faceMaterial } from './mouths'
import { faceMeshes } from './calibration'
import { expressionAt, mouthAt } from './track'
import type { Scene3DSpeech } from './types'

export class SpeechFaceRuntime {
  private key = ''
  private binding?: ReturnType<typeof faceMaterial>
  private mesh?: Mesh<BufferGeometry, MeshStandardMaterial>
  private original?: MeshStandardMaterial
  private atlas?: Texture
  private revision = 0
  ready = true
  error?: Error
  private readonly redraw: () => void
  constructor(redraw: () => void = () => {}) { this.redraw = redraw }

  private clear() {
    this.revision++
    if (this.mesh && this.original) this.mesh.material = this.original
    this.binding?.material.dispose()
    this.atlas?.dispose()
    this.binding = undefined; this.mesh = undefined; this.original = undefined; this.atlas = undefined
    this.ready = true; this.error = undefined
  }
  sync(root: Object3D, speech: Scene3DSpeech | undefined, seconds: number) {
    const active = speech?.enabled && speech.face
    const key = active ? JSON.stringify([speech.face?.meshIndex, speech.style, speech.lip, speech.atlas?.url]) : ''
    if (key !== this.key) {
      this.clear(); this.key = key
      if (active) {
        const mesh = faceMeshes(root)[speech.face!.meshIndex]
        if (!mesh || Array.isArray(mesh.material) || !(mesh.material instanceof MeshStandardMaterial)) {
          this.error = new Error('Face placement needs a supported mesh/material.'); return
        }
        this.mesh = mesh as Mesh<BufferGeometry, MeshStandardMaterial>; this.original = this.mesh.material
        this.atlas = createAtlas(speech.style, speech.lip)
        this.binding = faceMaterial(this.mesh, this.atlas, true)
        if (speech.atlas) {
          this.ready = false
          const revision = this.revision
          new TextureLoader().load(speech.atlas.url, texture => {
            if (revision !== this.revision) { texture.dispose(); return }
            const img = texture.image as { width: number; height: number }
            if (!img || img.width !== img.height * 9 || img.height > 512) {
              texture.dispose(); this.error = new Error('Mouth atlas must contain 9 square tiles (maximum 512 px each).'); return
            }
            texture.colorSpace = SRGBColorSpace; texture.generateMipmaps = false
            this.atlas?.dispose(); this.atlas = texture; this.binding!.uniforms.mouthAtlas.value = texture; this.ready = true; this.redraw()
          }, undefined, () => { if (revision === this.revision) this.error = new Error('Mouth atlas could not be loaded.') })
        }
      }
    }
    if (!this.binding || !speech?.face) return
    const u = this.binding.uniforms, f = speech.face, m = mouthAt(speech, seconds), e = EXPRESSIONS[expressionAt(speech, seconds)]
    u.faceCenter.value.fromArray(f.center); u.faceSize.value.fromArray(f.size); u.skinColor.value.fromArray(f.skin)
    u.cleanSkin.value = speech.clean ? 1 : 0; u.mouthStrength.value = speech.strength
    u.mouthA.value = m.a; u.mouthB.value = m.b; u.mouthMix.value = m.mix
    u.eyeLeft.value.fromArray(f.eyes.left); u.eyeRight.value.fromArray(f.eyes.right); u.eyeSize.value.fromArray(f.eyes.size)
    u.eyeSkinLeft.value.fromArray(f.eyes.skinLeft); u.eyeSkinRight.value.fromArray(f.eyes.skinRight)
    u.eyesEnabled.value = speech.eyes ? 1 : 0; u.eyeExpression.value.fromArray(e.values); u.eyeBrows.value = e.brows
    u.eyeBlink.value = speech.blink ? blinkAt(seconds) : 0
  }
  dispose() { this.clear(); this.key = '' }
}
