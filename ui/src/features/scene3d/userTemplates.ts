import { cloneScene3DDocument, parseScene3DDocument } from './document.ts'
import { adaptAuthoredCameraToFrame, fromPortraitCamera, scene3dFrameFormat } from './frameFormat.ts'
import type { MediaScreen } from './mediaScreen.ts'
import { applyKeptSlotAssets, takeKeptSlot } from './templates.ts'
import type { Scene3DDocument, Scene3DSlot } from './types.ts'

export const WORLD3D_TEMPLATE_KIND = 'hocuspocus.world3d.template'
export const USER_TEMPLATE_STORAGE_KEY = 'hocuspocus-world3d-user-templates'
const MAX_TEMPLATES = 24
const MAX_FILE_BYTES = 1.5 * 1024 * 1024

export type World3DUserTemplate = {
  kind: typeof WORLD3D_TEMPLATE_KIND
  version: 1
  id: string
  title: string
  description: string
  includeAssets: boolean
  createdAt: string
  document: Scene3DDocument
}

function hasDurableUrl(url: string | undefined) {
  return typeof url === 'string' && url.length > 0 && !url.startsWith('blob:')
}

function slotHasDurableAsset(slot: Scene3DSlot) {
  return hasDurableUrl(slot.sourceUrl) || hasDurableUrl(slot.screen?.sourceUrl)
}

function stripScreen(screen: MediaScreen | undefined, includeAssets: boolean): MediaScreen | undefined {
  if (!screen) return undefined
  if (includeAssets && hasDurableUrl(screen.sourceUrl)) return screen
  return { ...screen, sourceUrl: '', sourceRef: undefined }
}

function stripSlot(slot: Scene3DSlot, includeAssets: boolean): Scene3DSlot {
  const keep = includeAssets && hasDurableUrl(slot.sourceUrl)
  return {
    ...slot,
    sourceUrl: keep ? slot.sourceUrl : '',
    sourceRef: keep ? slot.sourceRef : undefined,
    clip: keep ? slot.clip : null,
    clipPlayback: keep ? slot.clipPlayback : undefined,
    speech: keep ? slot.speech : undefined,
    character: keep ? slot.character : undefined,
    screen: stripScreen(slot.screen, includeAssets),
  }
}

export function scenarioDocumentFromShot(document: Scene3DDocument, includeAssets: boolean): Scene3DDocument {
  const next = cloneScene3DDocument(document)
  delete next.clipNumber
  delete next.production
  next.slots = next.slots.map(slot => stripSlot(slot, includeAssets))
  if (!includeAssets) delete next.soundtrack
  else if (next.soundtrack) {
    next.soundtrack = next.soundtrack.filter(track => hasDurableUrl(track.audio?.url))
    if (!next.soundtrack.length) delete next.soundtrack
  }
  return next
}

export function createUserTemplate(input: {
  document: Scene3DDocument
  title: string
  description?: string
  includeAssets?: boolean
  id?: string
}): World3DUserTemplate | undefined {
  const title = input.title.trim().slice(0, 80)
  if (!title) return undefined
  const document = parseScene3DDocument(scenarioDocumentFromShot(input.document, Boolean(input.includeAssets)))
  if (!document) return undefined
  return {
    kind: WORLD3D_TEMPLATE_KIND,
    version: 1,
    id: input.id || newTemplateId(),
    title,
    description: (input.description || '').trim().slice(0, 240),
    includeAssets: Boolean(input.includeAssets),
    createdAt: new Date().toISOString(),
    document,
  }
}

export function parseUserTemplate(raw: unknown): World3DUserTemplate | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  if (value.kind === WORLD3D_TEMPLATE_KIND) {
    if (value.version !== 1 || typeof value.id !== 'string' || typeof value.title !== 'string') return undefined
    const parsed = parseScene3DDocument(value.document)
    if (!parsed) return undefined
    const includeAssets = value.includeAssets === true
    const document = parseScene3DDocument(scenarioDocumentFromShot(parsed, includeAssets))
    if (!document) return undefined
    const title = value.title.trim().slice(0, 80)
    if (!title) return undefined
    return {
      kind: WORLD3D_TEMPLATE_KIND,
      version: 1,
      id: value.id.slice(0, 80) || newTemplateId(),
      title,
      description: typeof value.description === 'string' ? value.description.trim().slice(0, 240) : '',
      includeAssets,
      createdAt: typeof value.createdAt === 'string' ? value.createdAt : new Date().toISOString(),
      document,
    }
  }
  const document = parseScene3DDocument(raw)
  if (!document) return undefined
  return createUserTemplate({
    document,
    title: document.production?.title || document.templateId,
    includeAssets: document.slots.some(slotHasDurableAsset)
      || Boolean(document.soundtrack?.some(track => hasDurableUrl(track.audio?.url))),
  })
}

function newTemplateId() {
  return `user-${globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`}`
}

function mergeKeptSlots(next: Scene3DSlot[], previous: Scene3DDocument): Scene3DSlot[] {
  const used = new Set<string>()
  return next.map(slot => applyKeptSlotAssets(slot, takeKeptSlot(slot, previous.slots, used)))
}

export function remountUserTemplate(pack: World3DUserTemplate, previous: Scene3DDocument, keepAssets: boolean): Scene3DDocument {
  const next = cloneScene3DDocument(pack.document)
  next.playbackSpeed = previous.playbackSpeed
  next.clipNumber = previous.clipNumber
  next.width = previous.width
  next.height = previous.height
  next.fps = previous.fps
  const packFormat = scene3dFrameFormat(pack.document.width, pack.document.height)
  const nextFormat = scene3dFrameFormat(next.width, next.height)
  if (packFormat !== nextFormat) {
    const authored = packFormat === 'portrait' ? fromPortraitCamera(pack.document.camera) : pack.document.camera
    next.camera = adaptAuthoredCameraToFrame(authored, next.width, next.height)
  }
  next.production = previous.production ? structuredClone(previous.production) : undefined
  if (previous.production) next.duration = previous.duration
  if (keepAssets && previous.soundtrack && !next.soundtrack) next.soundtrack = structuredClone(previous.soundtrack)
  if (!keepAssets) return next
  next.slots = mergeKeptSlots(next.slots, previous)
  return next
}

export function isWorld3DTemplateRaw(raw: unknown): boolean {
  return Boolean(raw && typeof raw === 'object' && (raw as { kind?: unknown }).kind === WORLD3D_TEMPLATE_KIND)
}

export function readStoredUserTemplates(): World3DUserTemplate[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(USER_TEMPLATE_STORAGE_KEY) || '[]')
    if (!Array.isArray(raw)) return []
    return raw.map(parseUserTemplate).filter((item): item is World3DUserTemplate => Boolean(item)).slice(0, MAX_TEMPLATES)
  } catch {
    return []
  }
}

export function writeStoredUserTemplates(templates: World3DUserTemplate[]) {
  try {
    window.localStorage.setItem(USER_TEMPLATE_STORAGE_KEY, JSON.stringify(templates.slice(0, MAX_TEMPLATES)))
  } catch {
    throw new Error('quota')
  }
}

export function saveUserTemplate(pack: World3DUserTemplate): World3DUserTemplate[] {
  const existing = readStoredUserTemplates().filter(item => item.id !== pack.id)
  const next = [pack, ...existing].slice(0, MAX_TEMPLATES)
  writeStoredUserTemplates(next)
  return next
}

export function removeUserTemplate(id: string): World3DUserTemplate[] {
  const next = readStoredUserTemplates().filter(item => item.id !== id)
  writeStoredUserTemplates(next)
  return next
}

export function templateFileTooLarge(size: number) {
  return size > MAX_FILE_BYTES
}

export function downloadUserTemplate(pack: World3DUserTemplate) {
  const slug = pack.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'scenario'
  const blob = new Blob([JSON.stringify(pack, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = window.document.createElement('a')
  link.href = url
  link.download = `${slug}.world3d.template.json`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
