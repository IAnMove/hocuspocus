import { NearestFilter, Vector2, type MeshBasicMaterial, type MeshStandardMaterial, type Texture } from 'three'
import { parseImageWindows, type ImageWindow } from './imageWindows'

export type ImageLook = { tint?: string; unlit?: boolean; psx?: number; grounded?: boolean; shadow?: number; windows?: ImageWindow[] }

const positiveNumber = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v > 0

export function parseImageLook(raw: unknown): ImageLook | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as ImageLook
  const look: ImageLook = {}
  const windows = parseImageWindows(value.windows)
  if (windows) look.windows = windows
  if (typeof value.tint === 'string' && /^#[\da-f]{6}$/i.test(value.tint)) look.tint = value.tint
  if (value.unlit === true) look.unlit = true
  if (value.grounded === true) look.grounded = true
  if (positiveNumber(value.shadow)) look.shadow = Math.min(1, value.shadow)
  if (positiveNumber(value.psx)) look.psx = Math.max(.5, Math.min(2, value.psx))
  return Object.keys(look).length ? look : undefined
}

/** Texture-local PSX treatment: the alpha silhouette and backdrop remain separate.
 * Quantized UVs, ordered dither and 5-bit channels run in the native renderer. */
export function applyPsxImageMaterial(material: MeshBasicMaterial | MeshStandardMaterial, texture: Texture, amount: number) {
  const image = texture.image as { width: number; height: number }
  const rows = Math.max(32, Math.round(160 / amount))
  const grid = new Vector2(Math.max(16, Math.round(rows * image.width / image.height)), rows)
  texture.magFilter = NearestFilter
  texture.minFilter = NearestFilter
  texture.generateMipmaps = false
  texture.needsUpdate = true
  material.customProgramCacheKey = () => 'hocuspocus-image-psx-v1'
  material.onBeforeCompile = shader => {
    shader.uniforms.hpPsxGrid = { value: grid }
    shader.fragmentShader = 'uniform vec2 hpPsxGrid;\n' + shader.fragmentShader
    shader.fragmentShader = shader.fragmentShader.replace('#include <map_fragment>', `
      #ifdef USE_MAP
        vec2 cell = clamp(floor(vMapUv * hpPsxGrid), vec2(0.), hpPsxGrid - 1.);
        vec2 uv = (cell + .5) / hpPsxGrid;
        vec4 sampledDiffuseColor = texture2D(map, uv);
        float bayer = mod(cell.x, 2.) * 2. + mod(cell.y, 2.);
        float dither = (bayer / 4. - .375) * .6 / 31.;
        // Quantize perceptual colors, then restore linear light for the material.
        // Quantizing linear RGB directly erases almost all dark costume detail.
        vec3 perceptual = pow(max(sampledDiffuseColor.rgb, vec3(0.)), vec3(1. / 2.2));
        perceptual = floor(clamp(perceptual + dither, 0., 1.) * 31. + .5) / 31.;
        sampledDiffuseColor.rgb = pow(perceptual, vec3(2.2));
        diffuseColor *= sampledDiffuseColor;
      #endif
    `)
  }
}
