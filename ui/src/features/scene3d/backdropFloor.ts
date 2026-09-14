import { Color, Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry, ShaderChunk, Vector2, Vector3, type Material, type MeshStandardMaterial, type Texture } from 'three'
import { cameraEyeAtTime } from './camera'
import { framingPose } from './framing'
import { framingAnchor } from './framingAnchor'
import { applyPsxImageMaterial } from './imageLook'
import type { GpuWorld } from './gpu'
import type { Scene3DDocument } from './types'

/** Project the plate onto a real floor from a fixed reference viewpoint.
 * The contact plane gains parallax without a flat-colored seam in the artwork. */
export class BackdropFloor {
  private material?: MeshBasicMaterial
  private original: Material | Material[]
  private texture?: Texture
  private psx?: number
  private uniforms = { hpGroundEye: { value: new Vector3() }, hpGroundOrigin: { value: new Vector3() },
    hpGroundNormal: { value: new Vector3() }, hpGroundInverse: { value: new Matrix4() }, hpGroundSize: { value: new Vector2() }, hpGroundFallback: { value: new Color() }, hpGroundSourceHeight: { value: 1 } }
  private world: GpuWorld
  constructor(world: GpuWorld) { this.world = world; this.original = world.floor.material }

  private restore(doc: Scene3DDocument) {
    this.world.floor.material = this.original
    ;(this.original as MeshStandardMaterial).color.set(doc.environment?.floorColor ?? '#1c222c')
    this.world.floor.visible = !doc.environment?.reflectiveFloor && doc.environment?.floorStyle !== 'none'
  }

  sync(doc: Scene3DDocument) {
    this.restore(doc)
    const slot = doc.slots.find(s => s.slot === 'background' && s.media === 'image' && (!s.surface || s.surface === 'cutout'))
    const root = slot && this.world.slots.get(slot.id)?.root
    const texture = root instanceof Mesh && (root.material as MeshBasicMaterial).map
    if (doc.environment?.floorStyle !== 'backdrop' || !slot || !(root instanceof Mesh) || !(root.geometry instanceof PlaneGeometry) || !texture) return
    if (this.texture !== texture || this.psx !== slot.imageLook?.psx) this.create(texture, slot.imageLook?.psx)
    root.updateMatrixWorld(true)
    const frame = doc.camera.framing, target = doc.slots.find(s => s.id === frame?.targetSlot)
    const actor = target && this.world.slots.get(target.id)?.root
    const eye = frame && target && actor ? framingPose(frame, framingAnchor(actor, frame.anchor), target, doc.duration / 2, doc.duration).eye
      : cameraEyeAtTime(doc.camera, doc.duration / 2, doc.duration, doc.slots)
    const u = this.uniforms
    u.hpGroundFallback.value.set(doc.environment.floorColor ?? '#1c222c')
    u.hpGroundSourceHeight.value = doc.environment.floorSourceHeight ?? 1
    u.hpGroundEye.value.set(...eye)
    root.getWorldPosition(u.hpGroundOrigin.value)
    u.hpGroundNormal.value.set(0, 0, 1).transformDirection(root.matrixWorld)
    u.hpGroundInverse.value.copy(root.matrixWorld).invert()
    u.hpGroundSize.value.set(root.geometry.parameters.width, root.geometry.parameters.height)
    this.world.floor.material = this.material!
  }

  private create(texture: Texture, psx?: number) {
    this.material?.dispose(); this.texture = texture; this.psx = psx
    const material = new MeshBasicMaterial({ map: texture })
    if (psx) applyPsxImageMaterial(material, texture, psx)
    const imageShader = material.onBeforeCompile
    material.customProgramCacheKey = () => `hocuspocus-backdrop-floor-${Boolean(psx)}`
    material.onBeforeCompile = (shader, renderer) => {
      imageShader(shader, renderer)
      Object.assign(shader.uniforms, this.uniforms)
      shader.vertexShader = 'varying vec3 hpGroundWorld;\n' + shader.vertexShader.replace('#include <project_vertex>', '#include <project_vertex>\nhpGroundWorld=(modelMatrix*vec4(transformed,1.)).xyz;')
      shader.fragmentShader = `varying vec3 hpGroundWorld; uniform vec3 hpGroundEye; uniform vec3 hpGroundOrigin; uniform vec3 hpGroundNormal;
        uniform mat4 hpGroundInverse; uniform vec2 hpGroundSize; uniform vec3 hpGroundFallback; uniform float hpGroundSourceHeight;\n` + shader.fragmentShader
      shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', ShaderChunk.map_fragment)
        .replaceAll('vMapUv', 'hpGroundUv').replace('void main() {', `void main() {
          vec3 ray=hpGroundWorld-hpGroundEye; float denominator=dot(hpGroundNormal,ray);
          if(abs(denominator)<.00001) discard;
          float distance=dot(hpGroundNormal,hpGroundOrigin-hpGroundEye)/denominator;
          vec3 hit=(hpGroundInverse*vec4(hpGroundEye+ray*distance,1.)).xyz;
          vec2 rawUv=hit.xy/hpGroundSize+.5;
          // Preserve the plate at the distant edge; introduce its floor texture gradually toward the camera.
          rawUv.y*=mix(hpGroundSourceHeight,1.,smoothstep(4.,10.,length(hpGroundWorld.xz)));
          float hpGroundOutside=max(max(-rawUv.x,rawUv.x-1.),max(-rawUv.y,rawUv.y-1.));
          vec2 hpGroundUv=clamp(rawUv,vec2(.0001),vec2(.9999));`)
        .replace('#include <color_fragment>', '#include <color_fragment>\ndiffuseColor.rgb=mix(diffuseColor.rgb,hpGroundFallback,smoothstep(0.,.08,hpGroundOutside));')
    }
    this.material = material
  }
  dispose() { this.world.floor.material = this.original; this.material?.dispose() }
}
