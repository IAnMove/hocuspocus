import type { Scene3DSpeech } from './types'
import { defaultSpeech } from './types'
import { parseSpeech, safeMediaUrl } from './track'

export type FaceSettings = Pick<Scene3DSpeech, 'face' | 'atlas' | 'strength' | 'clean' | 'style' | 'lip' | 'expression' | 'blink' | 'eyes'>
export function faceSettings(speech: Scene3DSpeech): FaceSettings {
  const { face, atlas, strength, clean, style, lip, expression, blink, eyes } = speech
  return { face, atlas, strength, clean, style, lip, expression, blink, eyes }
}

export const MAX_MODEL_BYTES = 64 * 1024 * 1024
const SHA256_HEX = /^[a-f0-9]{64}$/
const hashes = new Map<string, Promise<string>>()

export function clearModelDigestCache() { hashes.clear() }

const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])
const rr = (x: number, n: number) => (x >>> n) | (x << (32 - n))
/** SHA-256 of bytes; used when crypto.subtle is missing (LAN HTTP). */
export function sha256Hex(bytes: Uint8Array): string {
  const bitLen = bytes.length * 8
  const paddedLen = ((bytes.length + 9 + 63) & ~63)
  const buf = new Uint8Array(paddedLen)
  buf.set(bytes)
  buf[bytes.length] = 0x80
  const view = new DataView(buf.buffer)
  view.setUint32(paddedLen - 4, bitLen >>> 0)
  let h0 = 0x6a09e667, h1 = 0xbb67ae85, h2 = 0x3c6ef372, h3 = 0xa54ff53a
  let h4 = 0x510e527f, h5 = 0x9b05688c, h6 = 0x1f83d9ab, h7 = 0x5be0cd19
  const w = new Uint32Array(64)
  for (let i = 0; i < paddedLen; i += 64) {
    for (let t = 0; t < 16; t++) w[t] = view.getUint32(i + t * 4)
    for (let t = 16; t < 64; t++) {
      const s0 = rr(w[t - 15], 7) ^ rr(w[t - 15], 18) ^ (w[t - 15] >>> 3)
      const s1 = rr(w[t - 2], 17) ^ rr(w[t - 2], 19) ^ (w[t - 2] >>> 10)
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) >>> 0
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4, f = h5, g = h6, h = h7
    for (let t = 0; t < 64; t++) {
      const temp1 = (h + (rr(e, 6) ^ rr(e, 11) ^ rr(e, 25)) + ((e & f) ^ (~e & g)) + K[t] + w[t]) >>> 0
      const temp2 = ((rr(a, 2) ^ rr(a, 13) ^ rr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0
      h = g; g = f; f = e; e = (d + temp1) >>> 0; d = c; c = b; b = a; a = (temp1 + temp2) >>> 0
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0
    h4 = (h4 + e) >>> 0; h5 = (h5 + f) >>> 0; h6 = (h6 + g) >>> 0; h7 = (h7 + h) >>> 0
  }
  return [h0, h1, h2, h3, h4, h5, h6, h7].map(n => n.toString(16).padStart(8, '0')).join('')
}
export async function hashSha256(data: ArrayBuffer): Promise<string> {
  try {
    if (globalThis.crypto?.subtle) {
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256', data))].map(b => b.toString(16).padStart(2, '0')).join('')
    }
  } catch { /* insecure HTTP: subtle is absent or rejects */ }
  return sha256Hex(new Uint8Array(data))
}

function fileNameFromApiPath(pathname: string) {
  const marker = '/api/v1/file/'
  const at = pathname.indexOf(marker)
  if (at < 0) return undefined
  let filename = pathname.slice(at + marker.length)
  try { filename = decodeURIComponent(filename) } catch { return undefined }
  if (!filename || filename.includes('/') || filename.includes('\\')) return undefined
  if (!filename.toLowerCase().endsWith('.glb')) return undefined
  return filename
}

function workspaceScope(parsed: URL, workspace?: string) {
  const scope = parsed.searchParams.get('workspace') || workspace || ''
  if (!scope || scope === '.' || scope === '..' || /[\\/]/.test(scope) || scope.length > 120) return undefined
  return scope
}

export function storedGlbTarget(url: string, workspace?: string) {
  if (!safeMediaUrl(url)) return undefined
  let parsed: URL
  try { parsed = new URL(url, 'https://hocus.invalid') } catch { return undefined }
  const filename = fileNameFromApiPath(parsed.pathname)
  const scope = workspaceScope(parsed, workspace)
  if (!filename || !scope) return undefined
  return { workspace: scope, filename }
}

async function serverDigest(target: { workspace: string; filename: string }, signal: AbortSignal): Promise<string | undefined> {
  const query = 'workspace=' + encodeURIComponent(target.workspace) + '&filename=' + encodeURIComponent(target.filename)
  const response = await fetch('/api/v1/character-kits/speech/digest?' + query, { signal, cache: 'force-cache' })
  if (response.status === 413) throw new Error('Model exceeds 64 MB.')
  if (!response.ok) return undefined
  const data = await response.json().catch(() => undefined) as { digest?: unknown } | undefined
  return typeof data?.digest === 'string' && SHA256_HEX.test(data.digest) ? data.digest : undefined
}

async function fetchModelBytes(url: string, signal: AbortSignal) {
  const response = await fetch(url, { signal, cache: 'force-cache' })
  if (!response.ok || Number(response.headers.get('content-length')) > MAX_MODEL_BYTES) throw new Error('Could not identify the model (maximum 64 MB).')
  const bytes = await response.arrayBuffer()
  if (bytes.byteLength > MAX_MODEL_BYTES) throw new Error('Model exceeds 64 MB.')
  return bytes
}

export function modelDigest(url: string, workspace?: string, signal?: AbortSignal): Promise<string> {
  if (!safeMediaUrl(url)) return Promise.reject(new Error('Save/upload the GLB before saving calibration.'))
  const key = (workspace ?? '') + '\0' + url
  if (hashes.has(key)) return hashes.get(key)!
  const pending = (async () => {
    const abort = signal ?? AbortSignal.timeout(30000)
    const stored = storedGlbTarget(url, workspace)
    if (stored) {
      const canonical = await serverDigest(stored, abort)
      if (canonical) return canonical
    }
    const bytes = await fetchModelBytes(url, abort)
    const local = await hashSha256(bytes)
    if (!globalThis.crypto?.subtle && stored) {
      const canonical = await serverDigest(stored, abort)
      if (canonical && canonical !== local) throw new Error('Model identity mismatch.')
      if (canonical) return canonical
    }
    return local
  })()
  if (hashes.size >= 32) hashes.delete(hashes.keys().next().value!)
  hashes.set(key, pending)
  void pending.catch(() => { if (hashes.get(key) === pending) hashes.delete(key) })
  return pending
}
export async function loadFaceProfile(url: string, workspace: string, signal?: AbortSignal) {
  const digest = await modelDigest(url, workspace, signal)
  const response = await fetch('/api/v1/character-kits/speech/profiles/' + digest + '?workspace=' + encodeURIComponent(workspace), { signal })
  if (response.status === 404) return { digest, revision: 0, settings: undefined }
  if (!response.ok) throw new Error('Could not load saved face calibration.')
  const data = await response.json()
  if (data.digest !== digest || !Number.isInteger(data.revision) || data.revision < 1) throw new Error('Invalid face calibration.')
  const speech = parseSpeech({ ...defaultSpeech(), ...data.settings })!
  if (!speech.face) throw new Error('Saved calibration has no face.')
  return { digest, revision: data.revision as number, settings: faceSettings(speech) }
}
export async function saveFaceProfile(digest: string, workspace: string, revision: number, speech: Scene3DSpeech) {
  if (!speech.face) throw new Error('Place the mouth first.')
  if (!SHA256_HEX.test(digest)) throw new Error('Invalid face calibration.')
  const response = await fetch('/api/v1/character-kits/speech/profiles/' + digest, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, revision, settings: faceSettings(speech) }),
  })
  if (!response.ok) throw new Error(response.status === 409 ? 'Calibration changed elsewhere; reload it before saving.' : 'Could not save face calibration.')
  return response.json() as Promise<{ revision: number; digest: string }>
}
