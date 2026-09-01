import { fetchCanonicalTasks, fetchCharacterKitLibrary, fetchOutputs, saveCharacterKit } from '../../api/client'
import {
  createCharacterKit,
  type CharacterKit,
  type CharacterKitLibrary,
  type CharacterKitStyle,
} from '../../lib/characterKit'
import { applyFaceRigMouthPreset, FACE_RIG_PRESET_ROOT, type FaceRigMouthPresetPack } from '../../lib/characterKitFaceRig'
import { queueFaceRigHandoff } from '../../lib/characterKitHandoff'
import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import { useStore } from '../../stores/useStore'
import type {
  ApplyCharacterKitPresetCommand,
  AttachCharacterKitReferencesCommand,
  BuildCharacterKitCommand,
  CreateCharacterKitCommand,
  OpenCharacterKitCommand,
  OpenCharacterKitRigCommand,
  TrackCharacterKitJobCommand,
  UpdateCharacterKitCommand,
} from './commands'
import { rememberCharacterKitLibrary } from './session'

const STYLES = new Set<CharacterKitStyle>(['cutout', 'children-illustration', 'anime-2d'])

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function normalizeName(value: string): string {
  return value.normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase()
}

async function loadLibrary(): Promise<CharacterKitLibrary> {
  const library = await fetchCharacterKitLibrary(workspaceName())
  rememberCharacterKitLibrary(library)
  return library
}

function findKit(library: CharacterKitLibrary, kitName: string): CharacterKit {
  if (kitName.trim()) {
    const wanted = normalizeName(kitName)
    const match = Object.values(library.kits).find(kit => normalizeName(kit.name) === wanted || kit.id === kitName)
    if (!match) throw new Error(`No existe el Character Kit “${kitName}”.`)
    return match
  }
  const active = library.kits[library.activeId] || Object.values(library.kits)[0]
  if (!active) throw new Error('No hay un Character Kit abierto.')
  return active
}

async function persist(library: CharacterKitLibrary, kit: CharacterKit): Promise<CharacterKitLibrary> {
  const next = await saveCharacterKit(workspaceName(), library, kit)
  rememberCharacterKitLibrary(next)
  return next
}

function kitResult(kit: CharacterKit, destination: 'character_kit' | 'character_creator' = 'character_kit'): CommandResult {
  const entity = { kind: 'character_kit', id: kit.id, workspaceId: workspaceName() }
  return commandResultFromSlice({
    entity,
    navigationTarget: { destination, entity },
  })
}

export async function createAgentCharacterKit(command: CreateCharacterKitCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const existing = Object.values(library.kits).find(kit => normalizeName(kit.name) === normalizeName(command.name))
  if (existing) {
    rememberCharacterKitLibrary({ ...library, activeId: existing.id })
    const entity = { kind: 'character_kit', id: existing.id, workspaceId: workspaceName() }
    return commandResultFromSlice({
      entity,
      navigationTarget: { destination: 'character_kit', entity, section: 'existing' },
    })
  }
  const kit = createCharacterKit(command.name, STYLES.has(command.style) ? command.style : 'cutout')
  await persist(library, kit)
  return kitResult(kit)
}

export async function openAgentCharacterKit(command: OpenCharacterKitCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const kit = findKit(library, command.kitName)
  rememberCharacterKitLibrary({ ...library, activeId: kit.id })
  return kitResult(kit)
}

export async function updateAgentCharacterKit(command: UpdateCharacterKitCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const current = findKit(library, command.kitName)
  const kit: CharacterKit = {
    ...current,
    name: command.name.trim() || current.name,
    lookNotes: command.lookNotes.trim() || current.lookNotes,
    style: command.style && STYLES.has(command.style) ? command.style : current.style,
    updatedAt: new Date().toISOString(),
  }
  await persist(library, kit)
  return kitResult(kit)
}

export async function attachAgentCharacterKitReferences(command: AttachCharacterKitReferencesCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const current = findKit(library, command.kitName)
  const outputs = await fetchOutputs(80, 0, { workspace: workspaceName(), mediaType: 'image' })
  const wanted = command.outputNames.map(name => name.trim()).filter(Boolean)
  if (wanted.length !== 1) {
    throw new Error('Character Kit admite una única referencia de identidad. Indica un solo output exacto.')
  }
  const identity = outputs.outputs.find(output => output.name === wanted[0])
  if (!identity) throw new Error(`No existe el output de imagen “${wanted[0]}” en este workspace.`)
  const kit: CharacterKit = {
    ...current,
    identityReference: {
      id: `${current.id}-identity`,
      name: identity.name,
      source: identity.url || identity.name,
      kind: 'image',
      alphaStatus: 'opaque',
      reviewState: 'approved',
      workspace: workspaceName(),
    },
    updatedAt: new Date().toISOString(),
  }
  await persist(library, kit)
  return kitResult(kit)
}

export async function buildAgentCharacterKit(command: BuildCharacterKitCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const current = findKit(library, command.kitName)
  const source = current.identityReference || current.base
  if (!source?.source) throw new Error('El kit no tiene una referencia de identidad para construir la pose base.')
  const kit: CharacterKit = {
    ...current,
    base: { ...source, id: `${current.id}-base`, reviewState: 'approved' },
    updatedAt: new Date().toISOString(),
  }
  await persist(library, kit)
  return kitResult(kit)
}

export async function openAgentCharacterKitRig(command: OpenCharacterKitRigCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const kit = findKit(library, command.kitName)
  const source = kit.base?.source || kit.identityReference?.source
  if (source) queueFaceRigHandoff({ name: kit.name, source, workspace: workspaceName() })
  return kitResult(kit)
}

export async function applyAgentCharacterKitPreset(command: ApplyCharacterKitPresetCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const current = findKit(library, command.kitName)
  const response = await fetch(`${FACE_RIG_PRESET_ROOT}/manifest.json`)
  if (!response.ok) throw new Error('No pude cargar los packs de visemas.')
  const data = await response.json() as { packs?: FaceRigMouthPresetPack[] }
  const pack = (data.packs || []).find(item => item.id === command.presetId || item.label === command.presetId)
  if (!pack) throw new Error(`No existe el preset de animación “${command.presetId}”.`)
  const kit = applyFaceRigMouthPreset(current, pack, workspaceName())
  await persist(library, kit)
  return kitResult(kit)
}

export async function trackAgentCharacterKitJob(command: TrackCharacterKitJobCommand): Promise<CommandResult> {
  const library = await loadLibrary()
  const kit = findKit(library, command.kitName)
  const snapshot = await fetchCanonicalTasks(workspaceName(), 'active')
  const taskIds = snapshot.tasks.filter(task => !task.parent_id).map(task => task.id)
  return commandResultFromSlice({
    status: taskIds.length ? 'queued' : 'completed',
    entity: { kind: 'character_kit', id: kit.id, workspaceId: workspaceName() },
    taskIds,
    navigationTarget: { destination: 'character_kit', entity: { kind: 'character_kit', id: kit.id, workspaceId: workspaceName() } },
  })
}
