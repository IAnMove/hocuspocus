import type { CharacterKitStyle } from '../../lib/characterKit'

export {
  applyAgentCharacterKitPreset,
  attachAgentCharacterKitReferences,
  buildAgentCharacterKit,
  createAgentCharacterKit,
  openAgentCharacterKit,
  openAgentCharacterKitRig,
  trackAgentCharacterKitJob,
  updateAgentCharacterKit,
} from '../characters/actions'

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
