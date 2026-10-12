import catalog from '../../../app/shared/character_styles.json' with { type: 'json' }

/** Shared with MCP through app/shared/character_styles.json (see services/character_styles.py). */
export type CharacterStyleId = string
export type ChromaScreen = 'green' | 'blue' | 'magenta'
export type CharacterStyleKind = 'character' | 'pose' | 'prop'
/** The preset's default look for characters.rig.flat (`style`): paper mouths for paper cutouts, warp mouths for
 * graphic-novel art. */
export type CharacterStyleRig = Record<string, number | boolean | string>
export type CharacterStyle = Omit<(typeof catalog.styles)[number], 'rig'> & { rig: CharacterStyleRig }

export const characterStyles: CharacterStyle[] = catalog.styles.map(style => ({ ...style,
  rig: Object.fromEntries(Object.entries(style.rig).filter(([, value]) => value !== undefined)) as CharacterStyleRig }))

export function characterStyle(id: CharacterStyleId): CharacterStyle | undefined {
  return characterStyles.find(style => style.id === id)
}

export function characterStyleLabel(style: CharacterStyle, language: string): string {
  return language.startsWith('es') ? style.label.es : style.label.en
}

export function characterStyleSummary(style: CharacterStyle, language: string): string {
  return language.startsWith('es') ? style.summary.es : style.summary.en
}

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Keying green removes green clothes, so a green subject gets a magenta screen. */
export function screenFor(description: string): ChromaScreen {
  const text = description.toLowerCase()
  return catalog.greenWords.some(word => new RegExp(`\\b${escape(word)}`, 'u').test(text)) ? 'magenta' : 'green'
}

export function characterStylePrompt(style: CharacterStyle, kind: CharacterStyleKind, description: string,
  screen: ChromaScreen = screenFor(description)): { prompt: string; negative: string; screen: ChromaScreen } {
  const background = style.background.replace('{screen}', catalog.screens[screen])
  const prompt = style[kind].replace('{description}', description.split(/\s+/).filter(Boolean).join(' ')).trim()
  return { prompt: `${prompt} ${background}`, negative: style.negative, screen }
}
