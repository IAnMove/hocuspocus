import { fetchCharacterKitLibrary, saveCharacterKit } from '../../api/characters'
import {
  createCharacterKit,
  type CharacterKit,
  type CharacterKitAsset,
} from '../../lib/characterKit'
import type { CharacterVoice } from '../../lib/characterVoice'
import { rememberCharacterKitLibrary } from '../characters/session'
import { CUT_PAPER_CAST, CUT_PAPER_PUBLIC_ROOT, CUT_PAPER_VISEMES } from './bible.ts'
import { CUT_PAPER_MOUTH_ANCHOR } from './puppet.ts'

export const TIJERAL_CHARACTER_PREFIX = 'tijeral-'

/** Distinct Qwen3 CustomVoice presets; not cloned actors. */
export const CUT_PAPER_TTS: Record<string, CharacterVoice> = {
  nilo: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'dylan', instructions: 'Slow, formal, slightly too precise. Speak the written language (Spanish or English).' },
  berta: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'serena', instructions: 'Fast, hungry, always tasting things. Nasal kid. Speak the written language (Spanish or English).' },
  kito: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'sohee', instructions: 'Short lines, high, always arriving. Excited kid. Speak the written language (Spanish or English).' },
  rami: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'ryan', instructions: 'Few words, dry, a drum hit is a sentence. Speak the written language (Spanish or English).' },
  paca: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'vivian', instructions: 'Dry adult alto. School caretaker. Speak the written language (Spanish or English).' },
  lino: { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'eric', instructions: 'Warm mid-baritone. Speaks with flour in the air. Speak the written language (Spanish or English).' },
}

const SPEAKING = new Set(['nilo', 'berta', 'kito'])

function imageAsset(id: string, name: string, source: string, kind: CharacterKitAsset['kind'] = 'image'): CharacterKitAsset {
  return {
    id, name, source, kind,
    alphaStatus: source.endsWith('.png') ? 'transparent' : 'opaque',
    reviewState: 'approved',
  }
}

export function tijeralCharacterKitId(characterId: string): string {
  return `${TIJERAL_CHARACTER_PREFIX}${characterId}`
}

export function createTijeralCharacterKits(): CharacterKit[] {
  const now = '2026-09-12T00:00:00.000Z'
  return CUT_PAPER_CAST.map(character => {
    const id = tijeralCharacterKitId(character.id)
    const voice = CUT_PAPER_TTS[character.id]
    const kit: CharacterKit = {
      ...createCharacterKit(character.name, 'cutout', []),
      id,
      name: character.name,
      lookNotes: `${character.silhouette}. ${character.hat}. ${character.notes}`,
      voice,
      provenance: [
        {
          method: 'tijeral-cut-paper',
          characterId: character.id,
          ...(SPEAKING.has(character.id) ? { voiceSample: `${CUT_PAPER_PUBLIC_ROOT}/voices/vo-${character.id}-${character.id}-1.wav` } : {}),
        },
      ],
      createdAt: now,
      updatedAt: now,
    }
    if (!SPEAKING.has(character.id)) return kit
    const anchor = CUT_PAPER_MOUTH_ANCHOR[character.id]
    kit.identityReference = imageAsset(`${id}-identity`, `${character.name} still`, `${CUT_PAPER_PUBLIC_ROOT}/puppets/${character.id}-canonical.jpg`)
    kit.base = imageAsset(`${id}-body`, `${character.name} body`, `${CUT_PAPER_PUBLIC_ROOT}/puppets/${character.id}-body.png`)
    kit.mouth = Object.fromEntries(CUT_PAPER_VISEMES.map(state => [
      state,
      imageAsset(`${id}-mouth-${state}`, `${character.name} ${state}`, `${CUT_PAPER_PUBLIC_ROOT}/mouths/paper-${state}.png`, 'overlay'),
    ]))
    if (anchor) kit.anchors = { base: { mouth: { offsetX: anchor.offsetX, offsetY: anchor.offsetY, scale: anchor.scale, rotation: 0 } } }
    return kit
  })
}

/** Insert bundled Tijeral kits into the workspace library. Never overwrite a kit the user already saved. */
export async function seedTijeralCharacterKits(workspace: string): Promise<number> {
  let library = await fetchCharacterKitLibrary(workspace)
  let inserted = 0
  for (const kit of createTijeralCharacterKits()) {
    if (library.kits[kit.id]) continue
    library = await saveCharacterKit(workspace, library, kit)
    inserted += 1
  }
  rememberCharacterKitLibrary(library)
  return inserted
}
