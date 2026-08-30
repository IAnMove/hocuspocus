import { fetchCharacterKitLibrary, fetchOutputs, saveCharacterKit } from '../../api/client'
import {
  createCharacterKit,
  type CharacterKit,
  type CharacterKitLibrary,
  type CharacterKitStyle,
} from '../../lib/characterKit'
import { applyFaceRigMouthPreset, FACE_RIG_PRESET_ROOT, type FaceRigMouthPresetPack } from '../../lib/characterKitFaceRig'
import { queueFaceRigHandoff } from '../../lib/characterKitHandoff'
import { useStore } from '../../stores/useStore'
import { rememberCharacterKitLibrary } from './wizardLabSession'
import { executionReport, type AgentExecutionReport } from './agentContract'

export interface AgentCreateCharacterKitAction {
  type: 'create_character_kit'
  name: string
  style: CharacterKitStyle
}

export interface AgentOpenCharacterKitAction {
  type: 'open_character_kit'
  kitName: string
}

export interface AgentUpdateCharacterKitAction {
  type: 'update_character_kit'
  kitName: string
  name: string
  lookNotes: string
  style: CharacterKitStyle | ''
}

export interface AgentAttachCharacterKitReferencesAction {
  type: 'attach_character_kit_references'
  kitName: string
  outputNames: string[]
}

export interface AgentBuildCharacterKitAction {
  type: 'build_character_kit'
  kitName: string
}

export interface AgentOpenCharacterKitRigAction {
  type: 'open_character_kit_rig'
  kitName: string
}

export interface AgentApplyCharacterKitPresetAction {
  type: 'apply_character_kit_preset'
  kitName: string
  presetId: string
}

export interface AgentTrackCharacterKitJobAction {
  type: 'track_character_kit_job'
  kitName: string
}

const STYLES = new Set<CharacterKitStyle>(['cutout', 'children-illustration', 'anime-2d'])

function workspaceName(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function showCharacterKit(): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setMediaFilter('characters')
  state.setSidebarOpen(false)
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

function kitReport(kit: CharacterKit, message: string, state: AgentExecutionReport['state'] = 'completed'): AgentExecutionReport {
  return executionReport({
    state,
    message,
    recoverable: false,
    target: { kind: 'character_kit', id: kit.id, title: kit.name },
  })
}

export async function createAgentCharacterKit(action: AgentCreateCharacterKitAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const existing = Object.values(library.kits).find(kit => normalizeName(kit.name) === normalizeName(action.name))
  if (existing) {
    rememberCharacterKitLibrary({ ...library, activeId: existing.id })
    showCharacterKit()
    const message = `He abierto el Character Kit existente “${existing.name}”.`
    return { message, report: kitReport(existing, message) }
  }
  const kit = createCharacterKit(action.name, STYLES.has(action.style) ? action.style : 'cutout')
  await persist(library, kit)
  showCharacterKit()
  const message = `He creado el Character Kit “${kit.name}”. Todavía no he generado poses.`
  return { message, report: kitReport(kit, message) }
}

export async function openAgentCharacterKit(action: AgentOpenCharacterKitAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const kit = findKit(library, action.kitName)
  rememberCharacterKitLibrary({ ...library, activeId: kit.id })
  showCharacterKit()
  const message = `He abierto Character Kit “${kit.name}”.`
  return { message, report: kitReport(kit, message) }
}

export async function updateAgentCharacterKit(action: AgentUpdateCharacterKitAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const current = findKit(library, action.kitName)
  const kit: CharacterKit = {
    ...current,
    name: action.name.trim() || current.name,
    lookNotes: action.lookNotes.trim() || current.lookNotes,
    style: action.style && STYLES.has(action.style) ? action.style : current.style,
    updatedAt: new Date().toISOString(),
  }
  await persist(library, kit)
  const message = `He actualizado la identidad de “${kit.name}”.`
  return { message, report: kitReport(kit, message) }
}

export async function attachAgentCharacterKitReferences(action: AgentAttachCharacterKitReferencesAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const current = findKit(library, action.kitName)
  const outputs = await fetchOutputs(80, 0, { workspace: workspaceName(), mediaType: 'image' })
  const wanted = action.outputNames.map(name => name.trim()).filter(Boolean)
  const matches = outputs.outputs.filter(output => wanted.includes(output.name))
  if (!matches.length) throw new Error('Ninguna referencia coincide con un output de imagen del workspace.')
  const identity = matches[0]
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
  const message = `He adjuntado ${matches.length} referencias a “${kit.name}”.`
  return { message, report: kitReport(kit, message) }
}

export async function buildAgentCharacterKit(action: AgentBuildCharacterKitAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const current = findKit(library, action.kitName)
  const source = current.identityReference || current.base
  if (!source?.source) throw new Error('El kit no tiene una referencia de identidad para construir la pose base.')
  const kit: CharacterKit = {
    ...current,
    base: { ...source, id: `${current.id}-base`, reviewState: 'approved' },
    updatedAt: new Date().toISOString(),
  }
  await persist(library, kit)
  const message = `He montado el kit “${kit.name}” con la pose base. No he lanzado generación.`
  return { message, report: kitReport(kit, message) }
}

export async function openAgentCharacterKitRig(action: AgentOpenCharacterKitRigAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const kit = findKit(library, action.kitName)
  const source = kit.base?.source || kit.identityReference?.source
  if (source) queueFaceRigHandoff({ name: kit.name, source, workspace: workspaceName() })
  showCharacterKit()
  const message = `He abierto el Face Rig de “${kit.name}”.`
  return { message, report: kitReport(kit, message) }
}

export async function applyAgentCharacterKitPreset(action: AgentApplyCharacterKitPresetAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const library = await loadLibrary()
  const current = findKit(library, action.kitName)
  const response = await fetch(`${FACE_RIG_PRESET_ROOT}/manifest.json`)
  if (!response.ok) throw new Error('No pude cargar los packs de visemas.')
  const data = await response.json() as { packs?: FaceRigMouthPresetPack[] }
  const pack = (data.packs || []).find(item => item.id === action.presetId || item.label === action.presetId)
  if (!pack) throw new Error(`No existe el preset de animación “${action.presetId}”.`)
  const kit = applyFaceRigMouthPreset(current, pack, workspaceName())
  await persist(library, kit)
  const message = `He aplicado el preset “${pack.label}” al Face Rig de “${kit.name}”.`
  return { message, report: kitReport(kit, message) }
}

export async function trackAgentCharacterKitJob(action: AgentTrackCharacterKitJobAction): Promise<{ message: string; report: AgentExecutionReport }> {
  const { inspectCanonicalQueue } = await import('./queueActions')
  const library = await loadLibrary()
  const kit = findKit(library, action.kitName)
  const message = await inspectCanonicalQueue('active')
  return {
    message: `Sigo el trabajo de “${kit.name}”. ${message}`,
    report: kitReport(kit, message, 'running'),
  }
}
