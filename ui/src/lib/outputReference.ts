type ReferenceableOutput = {
  name: string
  type: string
}

const TYPE_PREFIXES: Record<string, string> = {
  image: 'IMG',
  video: 'VID',
  audio: 'AUD',
  model3d: 'MOD',
  scene: 'SCN',
  comic: 'COM',
}

function fallbackToken(name: string): string {
  let hash = 0x811c9dc5
  for (let index = 0; index < name.length; index++) {
    hash ^= name.charCodeAt(index)
    hash = Math.imul(hash, 0x01000193)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}

/** A short, stable reference users can quote when reporting one output. */
export function getOutputReference(output: ReferenceableOutput): string {
  const matches = [...output.name.matchAll(/(?:^|[_-])([a-f0-9]{8,16})(?=[_.-]|$)/gi)]
  const token = matches.at(-1)?.[1] ?? fallbackToken(output.name)
  const prefix = TYPE_PREFIXES[output.type] ?? 'OUT'
  return `${prefix}-${token.toUpperCase()}`
}
