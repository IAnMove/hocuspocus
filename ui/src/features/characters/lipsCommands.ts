import type { CharacterMouthState } from '../../lib/characterMouthStates'

export const LIPS_OPERATIONS = ['list', 'create', 'update', 'generation.plan', 'capture', 'accept', 'apply', 'delete'] as const
export interface LipsCollectionCommand { operation: typeof LIPS_OPERATIONS[number]; input: Record<string, unknown> }
export interface GenerateLipsCommand { packId: string; states?: CharacterMouthState[]; model: string }
