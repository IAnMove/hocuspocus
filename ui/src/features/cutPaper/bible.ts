/** Original cut-paper series kit. Not a clone of any existing show. */

export const CUT_PAPER_KIT_ID = 'tijeral-cut-paper'
export const CUT_PAPER_PUBLIC_ROOT = '/examples/cut-paper'

export const CUT_PAPER_VISEMES = ['closed', 'small', 'wide', 'round'] as const
export type CutPaperViseme = (typeof CUT_PAPER_VISEMES)[number]

export const CUT_PAPER_EXPRESSIONS = ['neutral', 'happy', 'worried'] as const
export type CutPaperExpression = (typeof CUT_PAPER_EXPRESSIONS)[number]

export const CUT_PAPER_PIECES = ['legs', 'torso', 'arm-back', 'arm-front', 'head', 'face', 'hat'] as const
export type CutPaperPiece = (typeof CUT_PAPER_PIECES)[number]

export type CutPaperVoice = {
  id: string
  pitch: 'grave' | 'nasal' | 'acute' | 'ronca' | 'seca' | 'calida'
  notes: string
}

export type CutPaperCharacter = {
  id: string
  name: string
  role: 'kid' | 'adult'
  silhouette: string
  palette: string[]
  voice: CutPaperVoice
  hat: string
  notes: string
}

export type CutPaperLocation = {
  id: string
  name: string
  shot: string
}

export const CUT_PAPER_TOWN = {
  id: 'tijeral',
  name: 'Tijeral',
  range: 'Sierra Cartulina',
  summary: 'A highland paper village of scalloped tile roofs and grey-blue cardstock streets. Winter happens; the architecture is not a North-American suburb.',
}

export const CUT_PAPER_CAST: CutPaperCharacter[] = [
  {
    id: 'nilo', name: 'Nilo Carda', role: 'kid',
    silhouette: 'very tall thin rectangle',
    palette: ['#1d2b5a', '#d8c7a2', '#2a2a2a'],
    voice: { id: 'nilo-grave', pitch: 'grave', notes: 'Slow, formal, slightly too precise.' },
    hat: 'none — stacked black paper strips for hair, round paper-clip glasses',
    notes: 'Inventor of glue. Navy dungarees. Never an orange coat.',
  },
  {
    id: 'berta', name: 'Berta Miga', role: 'kid',
    silhouette: 'wide short pentagon',
    palette: ['#d4a017', '#5a3a1c', '#f3e6c4'],
    voice: { id: 'berta-nasal', pitch: 'nasal', notes: 'Fast, hungry, always tasting things.' },
    hat: 'two paper buns, no beanie',
    notes: 'Mustard slicker, punched-dot freckles. Mustard is not orange.',
  },
  {
    id: 'kito', name: 'Kito Veleta', role: 'kid',
    silhouette: 'tiny triangle body under a huge paper-boat hat',
    palette: ['#1f6f6a', '#f2ead4', '#c45c2a'],
    voice: { id: 'kito-acute', pitch: 'acute', notes: 'Short lines, high, always arriving.' },
    hat: 'folded paper boat, cream and teal stripes',
    notes: 'Boat hat, not a pom-pom beanie. Teal-cream, not orange-cyan.',
  },
  {
    id: 'rami', name: 'Rami Tambo', role: 'kid',
    silhouette: 'square block with a drum',
    palette: ['#4a5c28', '#6b4423', '#c4a574'],
    voice: { id: 'rami-ronca', pitch: 'ronca', notes: 'Few words, dry, a drum hit is a sentence.' },
    hat: 'none — torn brown paper hair',
    notes: 'Olive patched vest, cardboard drum on a strap.',
  },
  {
    id: 'paca', name: 'Doña Paca', role: 'adult',
    silhouette: 'very tall trapezoid',
    palette: ['#3a3a3a', '#8a8a8a', '#1d2b5a'],
    voice: { id: 'paca-seca', pitch: 'seca', notes: 'Dry adult alto. School caretaker.' },
    hat: 'grey paper-roll bun',
    notes: 'Charcoal apron. Not a parent sitcom type.',
  },
  {
    id: 'lino', name: 'Lino Horna', role: 'adult',
    silhouette: 'wide oval baker',
    palette: ['#8b3a1e', '#f4efe4', '#d8c7a2'],
    voice: { id: 'lino-calida', pitch: 'calida', notes: 'Warm mid-baritone. Speaks with flour in the air.' },
    hat: 'none — flour as torn white flakes',
    notes: 'Rust-red cardstock apron.',
  },
]

export const CUT_PAPER_LOCATIONS: CutPaperLocation[] = [
  { id: 'plaza', name: 'Plaza nevada', shot: 'Front, slightly high. Fountain of stacked paper discs, scalloped tile roofs, torn-paper snow. Not a bus stop.' },
  { id: 'porche', name: 'Porche de la panadería', shot: '3/4 very flat. Rust awning, flour dust, a bench of corrugated card.' },
  { id: 'aula', name: 'Aula del cole', shot: 'Front. Paper desks, a tin-bell silhouette in the window, charcoal blackboard.' },
  { id: 'cocina', name: 'Cocina de Doña Paca', shot: 'Front. Shelf of jars, navy stove, cream wall of construction paper.' },
  { id: 'sierra', name: 'Sierra al fondo', shot: 'Wide. Folded-paper mountains, tiny village stamp, late-afternoon mustard light.' },
]

export const CUT_PAPER_FORBIDDEN = [
  'iconic orange parka',
  'orange-and-turquoise pom-pom beanie',
  'four kids waiting at a suburban snowy bus stop as the identity of the show',
  'cloned actor voices',
  'round painted portrait in a circle for a face',
  'tv-head-humanoid.glb as a body',
] as const

export function cutPaperAssetUrl(kind: 'cardboard' | 'location' | 'piece' | 'mouth' | 'brow', id: string, extra = ''): string {
  const suffix = extra ? `-${extra}` : ''
  if (kind === 'cardboard') return `${CUT_PAPER_PUBLIC_ROOT}/cardboard.png`
  if (kind === 'location') return `${CUT_PAPER_PUBLIC_ROOT}/locations/${id}.png`
  if (kind === 'piece') return `${CUT_PAPER_PUBLIC_ROOT}/puppets/${id}${suffix}.png`
  if (kind === 'mouth') return `${CUT_PAPER_PUBLIC_ROOT}/mouths/${id}-${extra}.png`
  return `${CUT_PAPER_PUBLIC_ROOT}/brows/${id}-${extra}.png`
}

export function cutPaperCharacter(id: string): CutPaperCharacter | undefined {
  return CUT_PAPER_CAST.find(item => item.id === id)
}
