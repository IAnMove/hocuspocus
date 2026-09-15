import { Box3, Color, Mesh, MeshBasicMaterial, MeshStandardMaterial, type Material, type Object3D } from 'three'
import { ENERGY_NOISE } from '../sceneFx/energyShaders'
import type { Scene3DSlot } from './types'

type Patch = { compile: Material['onBeforeCompile']; cache: Material['customProgramCacheKey'] }
/** Composes with the native mouth shader. Source materials and geometry are never replaced. */
export class MaterializationRuntime {
  private patches = new Map<Material, Patch>()
  private uniforms = { arrivalCut: { value: -10000 }, arrivalTime: { value: 0 }, arrivalColor: { value: new Color('#83e8ff') } }
  sync(root: Object3D, appearance: Scene3DSlot['appearance'], seconds: number) {
    root.visible = !appearance || seconds >= appearance.start
    if (!appearance) { this.clear(); return }
    const activeMaterials = new Set<Material>()
    root.traverse(child => {
      if (!(child instanceof Mesh)) return
      for (const material of Array.isArray(child.material) ? child.material : [child.material]) {
        if (!(material instanceof MeshStandardMaterial) && !(material instanceof MeshBasicMaterial)) continue
        activeMaterials.add(material)
        if (this.patches.has(material)) continue
        const compile = material.onBeforeCompile, cache = material.customProgramCacheKey
        const oldKey = cache.call(material)
        this.patches.set(material, { compile, cache })
        material.customProgramCacheKey = () => `${oldKey}/arrival-v1`
        material.onBeforeCompile = (shader, renderer) => {
          compile.call(material, shader, renderer)
          Object.assign(shader.uniforms, this.uniforms)
          shader.vertexShader = shader.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 arrivalWorld;')
            .replace('#include <project_vertex>', '#include <project_vertex>\narrivalWorld=(modelMatrix*vec4(transformed,1.)).xyz;')
          shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `#include <common>\nvarying vec3 arrivalWorld; uniform float arrivalCut,arrivalTime; uniform vec3 arrivalColor; ${ENERGY_NOISE}`)
            .replace('#include <alphatest_fragment>', `#include <alphatest_fragment>\nfloat edge=arrivalCut-arrivalWorld.y+(noise2(arrivalWorld.xz*19.+arrivalTime)-.5)*.08; if(edge<0.) discard;`)
            .replace('#include <opaque_fragment>', 'outgoingLight+=arrivalColor*(1.-smoothstep(0.,.09,edge))*4.;\n#include <opaque_fragment>')
        }
        material.needsUpdate = true
      }
    })
    for (const [material, patch] of this.patches) if (!activeMaterials.has(material)) { this.restore(material, patch); this.patches.delete(material) }
    const bounds = new Box3().setFromObject(root, true)
    const progress = Math.max(0, Math.min(1, (seconds - appearance.start) / appearance.duration))
    this.uniforms.arrivalCut.value = bounds.min.y - .1 + (bounds.max.y - bounds.min.y + .3) * progress
    this.uniforms.arrivalTime.value = Math.max(0, seconds - appearance.start)
    this.uniforms.arrivalColor.value.set(appearance.color)
  }
  private restore(material: Material, patch: Patch) { material.onBeforeCompile = patch.compile; material.customProgramCacheKey = patch.cache; material.needsUpdate = true }
  clear() { for (const [material, patch] of this.patches) this.restore(material, patch); this.patches.clear() }
}
