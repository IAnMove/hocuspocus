export interface CreativeCharacter {
  name: string
  role: string
  personality: string
  desire: string
  flaw: string
  appearance: string
  voice: string
}

export interface CreativeLocation {
  name: string
  purpose: string
  description: string
}

export const normalizeName = (value: string): string => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, ' ')
  .trim()
  .toLowerCase()

export const boundedDuration = (value: number | undefined, fallback: number): number => (
  Math.max(15, Math.min(3_600, Math.round(value || fallback)))
)

export const explicitMusicLanguage = (value: string): string => {
  const raw = value.trim()
  const aliases: Record<string, string> = {
    es: 'Español', en: 'English', fr: 'Français', de: 'Deutsch',
    it: 'Italiano', pt: 'Português', ja: '日本語', ko: '한국어', zh: '中文',
  }
  return aliases[raw.toLowerCase()] || raw || 'English'
}

export function creativeCharacters(values: CreativeCharacter[]): CreativeCharacter[] {
  return values.length ? values : [{
    name: 'Protagonist',
    role: 'Protagonist',
    personality: 'Resourceful, curious and determined.',
    desire: 'Resolve the central conflict.',
    flaw: 'Rushes ahead when they think they are right.',
    appearance: 'Clear silhouette, recognizable wardrobe and readable expressions.',
    voice: 'Natural, expressive and consistent with the tone.',
  }]
}

export function creativeLocations(values: CreativeLocation[]): CreativeLocation[] {
  return values.length ? values : [{
    name: 'Main setting',
    purpose: 'Bring the characters together and make the conflict visible.',
    description: 'A recognizable, visually consistent place with room for the action.',
  }]
}

export function outlineBeats(values: string[], premise: string, ending: string): string[] {
  if (values.length >= 3) return values
  return [
    `Beginning: ${premise || 'the protagonist\'s desire is introduced and a complication appears.'}`,
    'Middle: the initial plan worsens the conflict and forces the characters to change strategy.',
    `Ending: ${ending || 'the final decision resolves the problem with a clear, memorable consequence.'}`,
  ]
}


