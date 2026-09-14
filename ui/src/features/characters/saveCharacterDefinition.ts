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
    const savedKit = saved.kits[id]
    if (!savedKit) throw new Error('The character editor changed before saving finished.')
    return { saved, kit: savedKit, linked: true }
  }
  // Only a real kit id may recover a scoped draft. An empty id is "new
  // character" and must not alias the general workshop recovery key.
  const recovery = id ? readSpeechDraft(workspace, id) : null
  const next = await update(recovery?.kit ?? kit)
  check()
  const saved = await saveCharacterKit(workspace, { ...library, revision: recovery?.baseRevision ?? library.revision }, next)
  check()
  if (id) clearSpeechDraft(workspace, id)
  const savedKit = saved.kits[next.id]
  if (!savedKit) throw new Error('The character editor changed before saving finished.')
  return { saved, kit: savedKit, linked: false }
}
