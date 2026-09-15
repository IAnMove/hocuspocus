import { createStoryProject } from '../stories/model'
import type { StoryProject, StoryVisualAsset } from '../stories/types'
import { CUT_PAPER_CAST, CUT_PAPER_KIT_ID, CUT_PAPER_LOCATIONS, CUT_PAPER_PUBLIC_ROOT, CUT_PAPER_TOWN } from './bible.ts'
import { tijeralCharacterKitId } from './characterKits.ts'

function asset(id: string, name: string, source: string, prompt: string): StoryVisualAsset {
  return {
    id, name, source, prompt,
    provider: 'upload', approval: 'approved', createdAt: '2026-09-11T00:00:00.000Z',
  }
}

/** Bundled Story Lab chapter. Beats open Video 2D scenes; they are not baked MP4s. */
export function createTijeralStoryProject(workspace = 'default'): StoryProject {
  const now = '2026-09-11T00:00:00.000Z'
  const base = createStoryProject('full_story')
  const assets: Record<string, StoryVisualAsset> = {
    'asset-plaza': asset('asset-plaza', 'Plaza de Tijeral', `${CUT_PAPER_PUBLIC_ROOT}/locations/plaza.png`, 'Paper plaza of Tijeral'),
    'asset-nilo': asset('asset-nilo', 'Nilo Carda', `${CUT_PAPER_PUBLIC_ROOT}/puppets/nilo-canonical.jpg`, 'Nilo paper puppet'),
    'asset-berta': asset('asset-berta', 'Berta Miga', `${CUT_PAPER_PUBLIC_ROOT}/puppets/berta-canonical.jpg`, 'Berta paper puppet'),
    'asset-kito': asset('asset-kito', 'Kito Veleta', `${CUT_PAPER_PUBLIC_ROOT}/puppets/kito-canonical.jpg`, 'Kito paper puppet'),
  }
  return {
    ...base,
    id: `story-${CUT_PAPER_KIT_ID}`,
    title: 'Tijeral · la fuente',
    genre: 'Limited-animation comedy',
    tone: 'Dry, paper-cut, village gag',
    audience: 'All ages',
    language: 'Español',
    spokenLanguage: 'Español de España',
    visualStyle: 'Photographed construction-paper collage, torn scissor edges, layered cardstock, square frontal faces, no 3D walkers, no round portrait-in-a-circle.',
    characterVisualStyle: 'Paper puppets: square face card glued on a paper head; mustard/navy/olive/teal-cream palette; never an orange parka or pom-pom beanie.',
    premise: `${CUT_PAPER_TOWN.name}: a highland paper village. Someone glued tracing paper on the fountain and called it ice.`,
    logline: 'In Tijeral, Nilo insists the fountain is not frozen. Berta tastes it anyway. Kito proves it was a sticker.',
    synopsis: 'Winter in Tijeral. The plaza fountain looks iced over. Nilo Carda, glue inventor, knows it is onion-skin paper. Berta Miga licks it and calls it cold glue. Kito Veleta slides in on a paper sled and peels the square off.',
    theme: 'Things that look frozen are often just stuck.',
    ending: 'The tracing-paper square flies off. Kito: it was a sticker.',
    creativeBrief: {
      ...base.creativeBrief,
      generalIdea: 'Original cut-paper series kit. Tutorial chapter, 78 seconds, three Video 2D shots.',
      context: CUT_PAPER_TOWN.summary,
      subjects: CUT_PAPER_CAST.filter(item => item.role === 'kid').map(item => item.name).join(', '),
      setting: 'Plaza nevada de Tijeral',
      action: 'Dialogue then a paper-sled gag',
      durationSeconds: 78,
    },
    world: {
      summary: CUT_PAPER_TOWN.summary,
      period: 'A paper winter that happens every year.',
      geography: `${CUT_PAPER_TOWN.name}, ${CUT_PAPER_TOWN.range}. Scalloped tile roofs, grey-blue cardstock streets, a fountain of stacked paper discs.`,
      society: 'A small village. Kids invent glue, taste things, and arrive too fast. Adults bake and keep the school.',
      technology: 'Glue, scissors, tracing paper. No cars, no TV heads.',
      rules: [
        'Faces are square frontal cards, not round portraits.',
        'Mouths change without changing brows.',
        'No orange parka, no pom-pom beanie, no cloned voices.',
        'Shots are assembled in Video 2D (Scene Animator), not as an external MP4.',
      ],
      visualLanguage: 'Scanner-lit cardstock, torn edges, paper snow, navy/mustard/olive/rust/cream.',
      visualPrompt: 'Construction-paper village plaza, scalloped roofs, stacked-disc fountain, torn-paper snow, front camera',
      negativePrompt: 'photoreal, 3D render, suburban bus stop, orange parka, round portrait in a circle, TV-head, cloned celebrity',
      locations: CUT_PAPER_LOCATIONS.map(location => ({
        id: `loc-${location.id}`,
        name: location.name,
        purpose: location.shot,
        description: location.shot,
        visualPrompt: location.shot,
        negativePrompt: 'bus stop, yellow bus, 3D photoreal',
        referenceAssetIds: location.id === 'plaza' ? ['asset-plaza'] : [],
      })),
      referenceAssetIds: ['asset-plaza'],
    },
    characters: CUT_PAPER_CAST.map(character => ({
      id: `char-${character.id}`,
      name: character.name,
      role: character.role === 'adult' ? 'Adult' : 'Kid',
      age: character.role === 'adult' ? 'adult' : 'kid',
      pronouns: character.id === 'berta' || character.id === 'paca' ? 'she/her' : 'he/him',
      personality: character.notes,
      desire: character.id === 'nilo' ? 'To be correct about glue.' : character.id === 'berta' ? 'To taste everything.' : character.id === 'kito' ? 'To arrive first.' : 'To keep the village going.',
      need: 'To notice the paper.',
      flaw: character.voice.notes,
      conflict: 'The fountain looks frozen.',
      arc: 'The sticker peels.',
      voice: `${character.voice.pitch}: ${character.voice.notes}`,
      characterKitRef: { id: tijeralCharacterKitId(character.id), workspace },
      appearance: `${character.silhouette}. ${character.hat}. Palette ${character.palette.join(', ')}.`,
      wardrobe: character.notes,
      visualPrompt: `${character.silhouette}, construction-paper puppet, square frontal face card, ${character.notes}`,
      negativePrompt: 'orange parka, pom-pom beanie, round portrait, photoreal child, 3D walker',
      referenceAssetIds: assets[`asset-${character.id}`] ? [`asset-${character.id}`] : [],
      primaryReferenceAssetId: assets[`asset-${character.id}`] ? `asset-${character.id}` : undefined,
      approval: 'approved' as const,
    })),
    relationships: [
      { id: 'rel-nilo-berta', fromCharacterId: 'char-nilo', toCharacterId: 'char-berta', label: 'Inventor / taster', dynamic: 'He explains. She licks.', evolution: 'She still thinks cold glue is ice.' },
      { id: 'rel-kito-nilo', fromCharacterId: 'char-kito', toCharacterId: 'char-nilo', label: 'Proof', dynamic: 'Kito arrives sideways and proves Nilo right.', evolution: 'The sticker flies.' },
    ],
    beats: [
      {
        id: 'beat-plaza', stage: 'Establish', title: 'Plaza nevada',
        summary: 'Tijeral in paper winter. Fountain of stacked discs. No bus stop.',
        goal: 'Show the village and the fake ice.',
        conflict: 'The fountain looks frozen.',
        turn: 'We hold on the tracing-paper square.',
        sceneLink: { editor: 'video2d', href: `${CUT_PAPER_PUBLIC_ROOT}/shots/01-plaza.maestro-scene.json`, label: 'Video 2D · plano 1' },
      },
      {
        id: 'beat-talk', stage: 'Dialogue', title: 'Cola fría',
        summary: 'Nilo says it is onion-skin paper. Berta tastes it. Cold glue.',
        goal: 'Play the argument.',
        conflict: 'Science versus tongue.',
        turn: 'Berta will not concede.',
        sceneLink: { editor: 'video2d', href: `${CUT_PAPER_PUBLIC_ROOT}/shots/02-talk.maestro-scene.json`, label: 'Video 2D · plano 2' },
      },
      {
        id: 'beat-sticker', stage: 'Gag', title: 'Era un sticker',
        summary: 'Kito slides in on a paper sled. The square peels off.',
        goal: 'Prove it was stuck, not frozen.',
        conflict: 'The ice is a sticker.',
        turn: 'Kito names it.',
        sceneLink: { editor: 'video2d', href: `${CUT_PAPER_PUBLIC_ROOT}/shots/03-sticker.maestro-scene.json`, label: 'Video 2D · plano 3' },
      },
    ],
    assets,
    approvals: {
      overview: { approvedAt: now, version: 1 },
      world: { approvedAt: now, version: 1 },
      characters: { approvedAt: now, version: 1 },
      relationships: { approvedAt: now, version: 1 },
      structure: { approvedAt: now, version: 1 },
    },
    createdAt: now,
    updatedAt: now,
  }
}

export const TIJERAL_STORY_ID = `story-${CUT_PAPER_KIT_ID}`
