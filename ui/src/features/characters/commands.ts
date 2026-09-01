import type { CharacterKitStyle } from '../../lib/characterKit'

export interface CreateCharacterKitCommand {
  name: string
  style: CharacterKitStyle
}

export interface OpenCharacterKitCommand {
  kitName: string
}

export interface UpdateCharacterKitCommand {
  kitName: string
  name: string
  lookNotes: string
  style: CharacterKitStyle | ''
}

export interface AttachCharacterKitReferencesCommand {
  kitName: string
  outputNames: string[]
}

export interface BuildCharacterKitCommand {
  kitName: string
}

export interface OpenCharacterKitRigCommand {
  kitName: string
}

export interface ApplyCharacterKitPresetCommand {
  kitName: string
  presetId: string
}

export interface TrackCharacterKitJobCommand {
  kitName: string
}
