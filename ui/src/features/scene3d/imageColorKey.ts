import { Vector3, type MeshBasicMaterial, type MeshStandardMaterial } from 'three'

export type ImageColorKey = { color: string; tolerance: number; softness: number }

export function parseImageColorKey(raw: unknown): ImageColorKey | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Partial<ImageColorKey>
  if (typeof value.color !== 'string' || !/^#[\da-f]{6}$/i.test(value.color)) return undefined
  const unit = (n: unknown, fallback: number) => typeof n === 'number' && Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : fallback
  return { color: value.color, tolerance: unit(value.tolerance, .06), softness: Math.max(.001, unit(value.softness, .04)) }
}

/** Refine existing alpha, including enclosed gaps. Runs on the original texture
 * colors before tint/lighting, and composes with the optional PSX material. */
export function applyImageColorKey(material: MeshBasicMaterial | MeshStandardMaterial, key: ImageColorKey) {
  const color = new Vector3(...[1, 3, 5].map(start => parseInt(key.color.slice(start, start + 2), 16) / 255) as [number, number, number])
  const previousCompile = material.onBeforeCompile.bind(material)
  const previousCacheKey = material.customProgramCacheKey.bind(material)
  // Capture before replacing the callback: the default cache key reads it.
  const cacheKey = previousCacheKey()
  material.customProgramCacheKey = () => `${cacheKey}-hocuspocus-color-key-v1`
  material.onBeforeCompile = (shader, renderer) => {
    previousCompile(shader, renderer)
    shader.uniforms.hpKeyColor = { value: color }
    shader.uniforms.hpKeyTolerance = { value: key.tolerance }
    shader.uniforms.hpKeySoftness = { value: key.softness }
    shader.fragmentShader = `
      uniform vec3 hpKeyColor;
      uniform float hpKeyTolerance;
      uniform float hpKeySoftness;
      vec3 hpKeySRGB(vec3 linearColor) {
        return mix(linearColor * 12.92,
          1.055 * pow(max(linearColor, vec3(0.)), vec3(1. / 2.4)) - .055,
          step(vec3(.0031308), linearColor));
      }
    ` + shader.fragmentShader
    shader.fragmentShader = shader.fragmentShader.replace('#include <alphatest_fragment>', `
      #ifdef USE_MAP
        vec3 hpOriginalColor = hpKeySRGB(texture2D(map, vMapUv).rgb);
        float hpDistance = distance(hpOriginalColor, hpKeyColor) / sqrt(3.);
        diffuseColor.a *= smoothstep(hpKeyTolerance, hpKeyTolerance + hpKeySoftness, hpDistance);
      #endif
      #include <alphatest_fragment>
    `)
  }
  material.transparent = true
  material.alphaTest = .05
  material.needsUpdate = true
}
