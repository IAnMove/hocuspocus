import { ACESFilmicToneMapping, AgXToneMapping, NeutralToneMapping, NoToneMapping, PMREMGenerator, type Scene, type Texture, type ToneMapping, type WebGLRenderer } from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { exposureFactor, type ToneMappingName } from './look'
import type { Scene3DDocument } from './types'

const TONE_MAPPING: Record<ToneMappingName, ToneMapping> = {
  aces: ACESFilmicToneMapping, agx: AgXToneMapping, neutral: NeutralToneMapping,
}

/** The scene's environment light: reflections and soft fill for the models' PBR materials. Pixel worlds keep
 * their flat look, and scenes without a model (placeholders, sets or effects only) skip the bake. */
export class EnvironmentLighting {
  private room?: Texture
  private applied = false

  sync(renderer: WebGLRenderer, scene: Scene, document: Scene3DDocument) {
    const lit = !document.pixelWorld && document.slots.some(slot => slot.media === 'model3d' && Boolean(slot.sourceUrl))
    const environment = lit ? document.lighting?.environment : undefined
    if (!environment || environment.source === 'none' || environment.intensity <= 0) {
      if (this.applied) { scene.environment = null; this.applied = false }
      return
    }
    // Generated once per renderer, without downloads. Until 2.F2 loads files, `hdri` lights with it too.
    // Test doubles without render targets cannot bake it; they keep today's lighting.
    if (typeof renderer.getRenderTarget !== 'function') return
    if (!this.room) {
      const generator = new PMREMGenerator(renderer)
      this.room = generator.fromScene(new RoomEnvironment(), 0.04).texture
      generator.dispose()
    }
    scene.environment = this.room
    scene.environmentIntensity = environment.intensity
    scene.environmentRotation.set(0, (environment.rotation * Math.PI) / 180, 0)
    this.applied = true
  }

  dispose() {
    this.room?.dispose()
    this.room = undefined
  }
}

/** The document's tone mapping and exposure. Always written so a previous scene cannot leak its grade.
 *  `cinematic` is the old default: ACES when the composer path is active, otherwise none. */
export function applyLook(renderer: WebGLRenderer, document: Scene3DDocument, cinematic = false) {
  if (document.pixelWorld) {
    renderer.toneMapping = NoToneMapping
    renderer.toneMappingExposure = 1
    return
  }
  if (document.look) {
    renderer.toneMapping = TONE_MAPPING[document.look.toneMapping]
    renderer.toneMappingExposure = exposureFactor(document.look)
    return
  }
  renderer.toneMapping = cinematic ? ACESFilmicToneMapping : NoToneMapping
  renderer.toneMappingExposure = 1
}
