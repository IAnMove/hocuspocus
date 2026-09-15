export const PACKAGE_KIND = 'hocuspocus.scene-package'
export const PACKAGE_VERSION = 1
export const TEMPLATE_KIND = 'hocuspocus.world3d.template'
export const MEDIA_DIR = 'media'
export const DOCUMENTS_DIR = 'documents'
export const MANIFEST_NAME = 'package.json'
export const HASH_PREFIX = 'sha256:'
export const MAX_ZIP_BYTES = 256 * 1024 * 1024
export const MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
export const MAX_MEMBER_BYTES = 128 * 1024 * 1024
export const MAX_DOCUMENT_BYTES = 2 * 1024 * 1024

const SAFE_SEGMENT = /^[A-Za-z0-9._-]+$/
const SHA256 = /^[0-9a-f]{64}$/
const CINEMA_MEMBERS = new Set([
  'cinema.js', 'cinema.ts', 'cinema.mjs', 'tools/cinema.js', 'tools/cinema.ts',
  'tools/cinema.mjs', 'cinema/runtime.js', 'cinema/runtime.ts',
])
const CINEMA_FIELDS = ['cinema', 'cinemaExtension', 'cinemaRuntime'] as const
const KNOWN_DOCUMENT_KEYS = new Set([
  'version', 'units', 'up', 'width', 'height', 'fps', 'duration', 'templateId',
  'camera', 'light', 'slots', 'soundtrack', 'production', 'clipNumber', 'sfx',
  'worldSfx', 'texts', 'playbackSpeed', 'environment', 'dressing', 'workshopScreen',
])
const KNOWN_WRAPPER_KEYS = new Set([
  'kind', 'version', 'id', 'title', 'description', 'includeAssets', 'createdAt', 'document',
])
const KNOWN_SLOT_KEYS = new Set([
  'id', 'slot', 'position', 'rotationY', 'scale', 'sourceUrl', 'sourceRef', 'speech',
  'media', 'screen', 'surface', 'appearance', 'textureRepeat', 'performance', 'grounded',
  'clip', 'clipPlayback', 'motion', 'loop', 'character',
])

export type UrlClass = 'empty' | 'transient' | 'external' | 'gallery' | 'uploads' | 'relative' | 'unsafe'

export type AssetUse = {
  docId: string
  role: string
  kind: string
  workspaceId: string
  filename: string
  url: string
  assetId?: string
}

export type PackageIssue = {
  code: string
  message: string
  repair?: boolean
  path?: string
}

export function isTemplateWrapper(value: unknown): value is { kind: typeof TEMPLATE_KIND; document: unknown } {
  return Boolean(value && typeof value === 'object' && (value as { kind?: unknown }).kind === TEMPLATE_KIND)
}

export function unwrapDocument(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object') throw new Error('Each packed item must be a scene document')
  if (isTemplateWrapper(value)) {
    const nested = value.document
    if (!nested || typeof nested !== 'object') throw new Error('Scenario template is missing its scene document')
    return nested as Record<string, unknown>
  }
  return value as Record<string, unknown>
}

export function cinemaExtensionOf(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const kind = String(record.kind || '')
  if (kind.startsWith('hocuspocus.cinema')) return String(record.extension || record.id || kind)
  for (const key of CINEMA_FIELDS) {
    const field = record[key]
    if (typeof field === 'string' && field.trim()) return field.trim()
    if (field && typeof field === 'object') {
      const nested = field as Record<string, unknown>
      const ext = nested.extension || nested.id || nested.kind
      if (ext) return String(ext)
    }
  }
  return undefined
}

const TRANSIENT_PREFIXES = ['blob:', 'file:', 'filesystem:', 'javascript:', 'data:']
const EXTERNAL_PREFIXES = ['http://', 'https://', '//']

function startsWithAny(text: string, prefixes: readonly string[]): boolean {
  return prefixes.some(prefix => text.startsWith(prefix))
}

function hasControlChars(text: string): boolean {
  return [...text].some(char => char.charCodeAt(0) <= 32 || char === '\\')
}

function classifyPath(path: string, text: string): UrlClass {
  if (path.startsWith('/api/v1/file/')) return 'gallery'
  if (path.startsWith('/api/v1/uploads/')) return 'uploads'
  const dotted = path.split('/').includes('..')
  if (path.startsWith(`${MEDIA_DIR}/`)) return dotted ? 'unsafe' : 'relative'
  if (path.startsWith('/') || text.includes('://')) return 'external'
  return dotted ? 'unsafe' : 'relative'
}

export function classifyUrl(url: string): UrlClass {
  const text = String(url || '').trim()
  if (!text) return 'empty'
  if (hasControlChars(text)) return 'unsafe'
  const lowered = text.toLowerCase()
  if (startsWithAny(lowered, TRANSIENT_PREFIXES)) return 'transient'
  if (startsWithAny(lowered, EXTERNAL_PREFIXES)) return 'external'
  return classifyPath(text.split('?')[0], text)
}

export function collectUnknownFields(raw: unknown, prefix = ''): string[] {
  if (!raw || typeof raw !== 'object') return []
  const record = raw as Record<string, unknown>
  if (isTemplateWrapper(record)) {
    const found = Object.keys(record).filter(key => !KNOWN_WRAPPER_KEYS.has(key)).map(key => prefix + key)
    return found.concat(collectUnknownFields(record.document, prefix ? `${prefix}document.` : 'document.'))
  }
  const found = Object.keys(record).filter(key => !KNOWN_DOCUMENT_KEYS.has(key)).map(key => prefix + key)
  const slots = record.slots
  if (Array.isArray(slots)) {
    slots.forEach((slot, index) => {
      if (!slot || typeof slot !== 'object') return
      for (const key of Object.keys(slot as object)) {
        if (!KNOWN_SLOT_KEYS.has(key)) found.push(`${prefix}slots[${index}].${key}`)
      }
    })
  }
  return found
}

function basename(value: string): string {
  return value.replace(/\\/g, '/').split('/').pop() || ''
}

function pickString(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string' && value) return value
  }
  return ''
}

function emptyUse(url: string): AssetUse {
  return { docId: '', role: '', kind: '', workspaceId: '', filename: basename(url.split('?')[0]), url }
}

function refFromRecord(record: Record<string, unknown>, url: string): AssetUse | undefined {
  const filename = basename(pickString(record, ['filename']))
  const refUrl = pickString(record, ['url', 'sourceUrl']) || url
  if (!filename && !refUrl) return undefined
  return {
    docId: '',
    role: '',
    kind: '',
    workspaceId: pickString(record, ['workspaceId', 'workspace_id']),
    filename: filename || basename(refUrl.split('?')[0]),
    url: refUrl,
    assetId: pickString(record, ['assetId', 'asset_id']),
  }
}

function refFrom(value: unknown, url = ''): AssetUse | undefined {
  if (typeof value === 'string' && value) return emptyUse(value)
  if (value && typeof value === 'object') return refFromRecord(value as Record<string, unknown>, url)
  return url ? emptyUse(url) : undefined
}

function pushUse(uses: AssetUse[], raw: unknown, docId: string, role: string, kind: string, url = '') {
  const ref = refFrom(raw, url)
  if (!ref || (!ref.url && !ref.filename)) return
  uses.push({ ...ref, docId, role, kind })
}

function collectWorldSfxUses(body: Record<string, unknown>, docId: string, uses: AssetUse[]) {
  const cues = Array.isArray(body.worldSfx) ? body.worldSfx : []
  cues.forEach((cue, index) => {
    if (!cue || typeof cue !== 'object') return
    const record = cue as Record<string, unknown>
    const url = String(record.sourceUrl || '')
    const kind = classifyUrl(url)
    if (kind !== 'gallery' && kind !== 'uploads') return
    const media = /\.(mp4|webm|mov)$/i.test(url.split('?')[0]) ? 'video' : 'image'
    pushUse(uses, record.sourceRef, docId, `worldSfx[${index}]`, media, url)
  })
}

function collectSlotUses(slot: unknown, index: number, docId: string, uses: AssetUse[]) {
  if (!slot || typeof slot !== 'object') return
  const record = slot as Record<string, unknown>
  const media = String(record.media || 'model3d')
  const kind = media === 'image' || media === 'screen' ? 'image' : 'model3d'
  pushUse(uses, record.sourceRef, docId, `slots[${index}]`, kind, String(record.sourceUrl || ''))
  const screen = record.screen
  if (screen && typeof screen === 'object') {
    const screenRecord = screen as Record<string, unknown>
    pushUse(uses, screenRecord.sourceRef, docId, `slots[${index}].screen`, screenRecord.media === 'video' ? 'video' : 'image', String(screenRecord.sourceUrl || ''))
  }
  const speech = record.speech
  if (!speech || typeof speech !== 'object') return
  const speechRecord = speech as Record<string, unknown>
  pushUse(uses, speechRecord.audio, docId, `slots[${index}].speech.audio`, 'audio')
  pushUse(uses, speechRecord.atlas, docId, `slots[${index}].speech.atlas`, 'image')
  const clips = Array.isArray(speechRecord.clips) ? speechRecord.clips : []
  clips.forEach((clip, clipIndex) => {
    if (clip && typeof clip === 'object') {
      pushUse(uses, (clip as Record<string, unknown>).audio, docId, `slots[${index}].speech.clips[${clipIndex}].audio`, 'audio')
    }
  })
}

export function collectAssetUses(document: unknown, docId = 'shot'): AssetUse[] {
  const uses: AssetUse[] = []
  const body = unwrapDocument(document)
  const slots = Array.isArray(body.slots) ? body.slots : []
  slots.forEach((slot, index) => collectSlotUses(slot, index, docId, uses))
  const tracks = Array.isArray(body.soundtrack) ? body.soundtrack : []
  tracks.forEach((track, index) => {
    if (track && typeof track === 'object') {
      pushUse(uses, (track as Record<string, unknown>).audio, docId, `soundtrack[${index}]`, 'audio')
    }
  })
  collectWorldSfxUses(body, docId, uses)
  return uses
}

export function uniqueAssetUses(uses: AssetUse[]): AssetUse[] {
  const seen = new Set<string>()
  const unique: AssetUse[] = []
  for (const use of uses) {
    const key = use.workspaceId && use.filename ? `${use.workspaceId}:${use.filename}` : use.url
    if (!key || seen.has(key)) continue
    seen.add(key)
    unique.push(use)
  }
  return unique
}

export function safeZipMember(name: string): string {
  const raw = String(name || '').replace(/\\/g, '/')
  if (!raw || raw.endsWith('/')) throw new Error('empty')
  if (raw.includes('\0') || raw.startsWith('/') || raw.startsWith('../') || raw === '..') throw new Error('traversal')
  const parts = raw.split('/').filter(part => part && part !== '.')
  if (!parts.length || parts.includes('..') || parts.some(part => !SAFE_SEGMENT.test(part))) throw new Error('traversal')
  return parts.join('/')
}

export function isCinemaMember(name: string): boolean {
  const lowered = name.toLowerCase()
  return CINEMA_MEMBERS.has(lowered) || lowered.endsWith('/cinema.js') || lowered.endsWith('/cinema.ts')
}

export function isContentHashName(name: string): boolean {
  const base = basename(name)
  const [hash] = base.split('.')
  return SHA256.test(hash)
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const subtle = globalThis.crypto?.subtle
  if (!subtle) throw new Error('SHA-256 is unavailable')
  const copy = new ArrayBuffer(data.byteLength)
  new Uint8Array(copy).set(data)
  const hash = await subtle.digest('SHA-256', copy)
  return [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, '0')).join('')
}

export function documentIssues(document: unknown, index: number): PackageIssue[] {
  const issues: PackageIssue[] = []
  const cinema = cinemaExtensionOf(document) || (isTemplateWrapper(document) ? cinemaExtensionOf(document.document) : undefined)
  if (cinema) issues.push({ code: 'cinema_extension', message: cinema, path: `documents[${index}]` })
  for (const use of collectAssetUses(document, `shot-${index}`)) {
    const kind = classifyUrl(use.url)
    if (kind === 'external' || kind === 'unsafe' || kind === 'transient') {
      issues.push({ code: 'external_link', message: use.url, path: use.role })
    }
  }
  return issues
}
