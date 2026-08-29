import { createCharacterKit, type CharacterKit, type CharacterKitLibrary } from './characterKit'

export const FACE_RIG_HANDOFF_EVENT = 'hocuspocus:face-rig-handoff'
const FACE_RIG_HANDOFF_KEY = 'hocuspocus:character-kit-face-rig-handoff'

export type FaceRigHandoff = {
  name: string
  source: string
  workspace: string
}

export function isPersistentCharacterSource(source: string): boolean {
  return Boolean(source.trim()) && !source.startsWith('blob:') && !source.startsWith('data:')
}

export function queueFaceRigHandoff(handoff: FaceRigHandoff, storage: Pick<Storage, 'setItem'> = sessionStorage): FaceRigHandoff {
  if (!isPersistentCharacterSource(handoff.source)) throw new Error('Face Rig needs a saved pose or upload, not a temporary browser image.')
  const next: FaceRigHandoff = {
    name: handoff.name.trim() || 'Character from Creator',
    source: handoff.source.trim(),
    workspace: handoff.workspace.trim() || 'default',
  }
  storage.setItem(FACE_RIG_HANDOFF_KEY, JSON.stringify(next))
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(FACE_RIG_HANDOFF_EVENT))
  return next
}

export function consumeFaceRigHandoff(storage: Pick<Storage, 'getItem' | 'removeItem'> = sessionStorage): FaceRigHandoff | null {
  const raw = storage.getItem(FACE_RIG_HANDOFF_KEY)
  storage.removeItem(FACE_RIG_HANDOFF_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as Partial<FaceRigHandoff>
    if (!parsed || typeof parsed.source !== 'string' || !isPersistentCharacterSource(parsed.source)) return null
    return {
      name: typeof parsed.name === 'string' && parsed.name.trim() ? parsed.name.trim() : 'Character from Creator',
      source: parsed.source.trim(),
      workspace: typeof parsed.workspace === 'string' && parsed.workspace.trim() ? parsed.workspace.trim() : 'default',
    }
  } catch {
    return null
  }
}

/** Open an existing kit with this pose, or draft a Character Kit base. Does not generate Face Rig pieces. */
export function kitFromFaceRigHandoff(handoff: FaceRigHandoff, library: CharacterKitLibrary): CharacterKit {
  if (!isPersistentCharacterSource(handoff.source)) throw new Error('Face Rig needs a persistent pose source.')
  const existing = Object.values(library.kits).find(kit =>
    kit.base?.source === handoff.source || kit.identityReference?.source === handoff.source,
  )
  if (existing) return {
    ...existing,
    poses: { ...existing.poses },
    mouth: { ...existing.mouth },
    eyes: { ...existing.eyes },
    anchors: { ...existing.anchors },
    provenance: [...existing.provenance],
  }
  const kit = createCharacterKit(handoff.name)
  const asset = {
    id: `${kit.id}-base`,
    name: kit.name,
    source: handoff.source,
    kind: 'image' as const,
    alphaStatus: 'opaque' as const,
    reviewState: 'approved' as const,
    workspace: handoff.workspace,
  }
  return {
    ...kit,
    base: asset,
    identityReference: { ...asset, id: `${kit.id}-identity` },
    provenance: [{ method: 'character-creator-handoff', source: handoff.source, workspace: handoff.workspace }],
  }
}
