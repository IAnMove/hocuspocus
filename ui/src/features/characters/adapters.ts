import {
  applyAgentCharacterKitPreset,
  attachAgentCharacterKitReferences,
  buildAgentCharacterKit,
  createAgentCharacterKit,
  openAgentCharacterKit,
  openAgentCharacterKitRig,
  trackAgentCharacterKitJob,
  updateAgentCharacterKit,
} from './actions'
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

export async function createKit(command: CreateCharacterKitCommand) {
  return createAgentCharacterKit(command)
}

export async function openKit(command: OpenCharacterKitCommand) {
  return openAgentCharacterKit(command)
}

export async function updateKit(command: UpdateCharacterKitCommand) {
  return updateAgentCharacterKit(command)
}

export async function attachReference(command: AttachCharacterKitReferencesCommand) {
  return attachAgentCharacterKitReferences(command)
}

export async function buildKit(command: BuildCharacterKitCommand) {
  return buildAgentCharacterKit(command)
}

export async function openRig(command: OpenCharacterKitRigCommand) {
  return openAgentCharacterKitRig(command)
}

export async function applyPreset(command: ApplyCharacterKitPresetCommand) {
  return applyAgentCharacterKitPreset(command)
}

export async function trackJob(command: TrackCharacterKitJobCommand) {
  return trackAgentCharacterKitJob(command)
}
