import { parseSceneFile } from '../../src/lib/sceneFile.ts'

export const MAX_OUTPUTS = 128
export const MAX_OUTPUT_BYTES = 256 * 1024 * 1024
const PROCEDURAL_EFFECT_KINDS = new Set([
  'rain', 'snow', 'dust', 'embers', 'fog', 'smoke', 'ash',
  'fireflies', 'confetti', 'bokeh', 'sparkles', 'bubbles', 'speedlines', 'leaves',
])
const PROCEDURAL_EFFECT_SOURCE = /^maestro-effect:([a-z]+)$/
export const REVIEW_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
  'x-frame-options': 'DENY',
  'content-security-policy': [
    "default-src 'none'", "base-uri 'none'", "form-action 'none'", "frame-ancestors 'none'",
    "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'", "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:", "media-src 'self' data: blob:", "font-src 'self' data:",
    "connect-src 'self' data: blob:", "worker-src 'self' blob:",
  ].join('; '),
}

export function createWriteBudget({ maxOutputs = MAX_OUTPUTS, maxBytes = MAX_OUTPUT_BYTES } = {}) {
  if (!Number.isSafeInteger(maxOutputs) || maxOutputs < 1 || maxOutputs > MAX_OUTPUTS
    || !Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > MAX_OUTPUT_BYTES) throw new Error('Invalid review storage budget.')
  let outputs = 0
  let bytes = 0
  return {
    // Reservations are conservative: an I/O failure never refunds disk capacity
    // that might already contain a partial file. Restart into a fresh sandbox.
    reserve(size) {
      if (!Number.isSafeInteger(size) || size < 0 || outputs + 1 > maxOutputs || bytes + size > maxBytes) throw new Error('Review storage quota exceeded; start a fresh sandbox.')
      outputs += 1
      bytes += size
    },
    snapshot: () => ({ outputs, bytes, maxOutputs, maxBytes }),
  }
}

function validateSource(source, isIndexedSource) {
  if (typeof source !== 'string' || source.length > 2_000_000) throw new Error('Invalid review asset reference.')
  if (/^data:(?:image\/|model\/gltf-binary;)/i.test(source)) return
  const indexedShape = /^\/(?:api\/v1\/file\/|scene-template-previews\/)/i
  if (indexedShape.test(source) && isIndexedSource(source)) return
  throw new Error('Review assets must be inline or indexed in this sandbox; external, blob and disk sources are blocked.')
}

function isValidatedProceduralEffect(layer) {
  if (layer.type !== 'effect' || typeof layer.source !== 'string') return false
  const match = PROCEDURAL_EFFECT_SOURCE.exec(layer.source)
  return Boolean(match && PROCEDURAL_EFFECT_KINDS.has(match[1]) && layer.atmosphere?.kind === match[1])
}

/** Validate, but do not normalize/change the exact recording snapshot. */
export function validateReviewSnapshot(scene, isIndexedSource = () => false) {
  parseSceneFile(JSON.stringify(scene))
  if (scene.generationPolicy !== 'provided_only') throw new Error('Review scenes require provided_only.')
  if (!Number.isFinite(scene.width) || scene.width <= 0 || scene.width > 1920
    || !Number.isFinite(scene.height) || scene.height <= 0 || scene.height > 1080
    || !Number.isFinite(scene.duration) || scene.duration <= 0 || scene.duration > 30
    || ![24, 30, 60].includes(scene.fps) || scene.layers.length > 24) throw new Error('Review scene exceeds its geometry/time/layer budget.')
  if (!/^[a-z0-9][a-z0-9-]*$/.test(scene.narrative?.templateId || '')) throw new Error('Review scene needs a safe template ID.')
  if (scene.audioTracks?.length) throw new Error('This reference sandbox accepts silent scenes only.')
  for (const layer of scene.layers) {
    if (!(['camera', 'effect', 'overlay'].includes(layer.type) && layer.source === '') && !isValidatedProceduralEffect(layer)) validateSource(layer.source, isIndexedSource)
    if (layer.thumbnail) validateSource(layer.thumbnail, isIndexedSource)
  }
  for (const asset of scene.narrative?.assets || []) validateSource(asset.source, isIndexedSource)
  return scene
}
