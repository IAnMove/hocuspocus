import { DepthTexture, type WebGLRenderTarget } from 'three'
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js'
import type { Pass } from 'three/addons/postprocessing/Pass.js'
import type { AtmosHandle } from './clearing.ts'

type Probed = Pass & { atmosProbed?: boolean }

const PASS_KEYS = ['shafts', 'dof', 'grade'] as const

export function ensureComposerDepth(composer: EffectComposer) {
  for (const target of [composer.renderTarget1, composer.renderTarget2]) fitDepth(target)
}

function fitDepth(target: WebGLRenderTarget) {
  const image = target.depthTexture?.image as { width?: number; height?: number } | undefined
  if (image && image.width === target.width && image.height === target.height) return
  target.depthTexture?.dispose()
  target.depthTexture = new DepthTexture(target.width, target.height)
}

/** Insert the set's passes after Render. The handle owns dispose. */
export function bindAtmosPasses(composer: EffectComposer, current: Pass[], handle: AtmosHandle | undefined): Pass[] {
  if (!handle) {
    for (const pass of current) composer.removePass(pass)
    return []
  }
  const wanted = handle.passes()
  if (current[0] === wanted[0]) return current
  for (const pass of current) composer.removePass(pass)
  wanted.forEach((pass, index) => {
    composer.insertPass(pass, 1 + index)
    arm(pass, PASS_KEYS[index], handle)
  })
  return wanted.slice()
}

function arm(pass: Pass | undefined, key: (typeof PASS_KEYS)[number] | undefined, handle: AtmosHandle) {
  if (!pass || !key) return
  const tagged = pass as Probed
  if (tagged.atmosProbed) return
  const run = pass.render.bind(pass)
  tagged.render = (renderer, writeBuffer, readBuffer, deltaTime, maskActive) => {
    const t0 = performance.now()
    run(renderer, writeBuffer, readBuffer, deltaTime, maskActive)
    handle.ms[key] = performance.now() - t0
  }
  tagged.atmosProbed = true
}

export function publishAtmosStats(
  stats: { calls: number; triangles: number; geometries: number; textures: number },
  ms: AtmosHandle['ms'],
) {
  const bucket = globalThis as { __atmosLast?: unknown; __atmosProbe?: (value: AtmosHandle['ms']) => void }
  bucket.__atmosLast = { ...stats, ms: { ...ms } }
  bucket.__atmosProbe?.(ms)
}
