import { create } from 'zustand'
import type { CharacterKit } from '../../lib/characterKit'
import type { CharacterVoice } from '../../lib/characterVoice'
import type { ApiOutput } from '../../api/client'

export type CharacterDefinitionDraft = { name: string; voice?: CharacterVoice; model?: ApiOutput }

export interface CharacterEditorRequest {
  workspace: string
  kit: CharacterKit
  sourceLabel: string
  sourceId: string
  draft?: CharacterDefinitionDraft
  onSaved: (kit: CharacterKit) => Promise<void>
  onReturn: () => Promise<void>
}

/** Keep the exact subject while moving between studio tabs. Never match by name. */
export const useCharacterEditorHandoff = create<{ request: CharacterEditorRequest | null }>(() => ({ request: null }))
