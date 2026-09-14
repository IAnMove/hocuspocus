import { saveCharacterKit } from '../../api/characters'
import type { CharacterKit, CharacterKitLibrary } from '../../lib/characterKit'
import { clearSpeechDraft, readSpeechDraft } from '../../lib/characterSpeechDraft'
import type { SaveSpeechWorkshop } from './useCharacterSpeechLibrary'

/** One write merges the definition with the mounted workshop or its scoped recovery draft. */
export async function saveCharacterDefinition(input: {
  workspace: string; library: CharacterKitLibrary; id: string; kit?: CharacterKit
  workshop: SaveSpeechWorkshop | null; update: (kit?: CharacterKit) => Promise<CharacterKit>; isCurrent: () => boolean
}) {
  const { workspace, library, id, kit, workshop, update, isCurrent } = input
  const check = () => { if (!isCurrent()) throw new Error('The character editor changed before saving finished.') }
  check()
  if (workshop) {
    const saved = await workshop(update)
    check()
    return { saved, kit: saved.kits[id], linked: true }
  }
  const recovery = readSpeechDraft(workspace, id)
  const next = await update(recovery?.kit ?? kit)
  check()
  const saved = await saveCharacterKit(workspace, { ...library, revision: recovery?.baseRevision ?? library.revision }, next)
  check()
  clearSpeechDraft(workspace, id)
  return { saved, kit: saved.kits[next.id], linked: false }
}
