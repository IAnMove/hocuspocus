import { create } from 'zustand'
import { readSpeechDraft } from '../../lib/characterSpeechDraft'
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
  saved?: boolean
  onSaved: (kit: CharacterKit) => Promise<void>
  onReturn: () => Promise<void>
}

/** Keep the exact subject while moving between studio tabs. Never match by name. */
export const useCharacterEditorHandoff = create<{ request: CharacterEditorRequest | null }>(() => ({ request: null }))

/** A saved session can yield to another subject even when the user navigated with studio tabs. */
export function characterEditorHasUnsavedChanges(request: CharacterEditorRequest) {
  if (!request.saved) return true
  const draft = request.draft
  if (draft && (draft.name !== request.kit.name || draft.model || JSON.stringify(draft.voice) !== JSON.stringify(request.kit.voice))) return true
  return Boolean(readSpeechDraft(request.workspace, request.kit.id))
}
