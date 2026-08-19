export type OrbitSubjectKind = 'character' | 'object'
export type OrbitRefRole = 'subject' | 'face' | 'outfit' | 'extra' | 'accessory'

export interface OrbitRefSpec {
  role: OrbitRefRole
}

export const CHARACTER_ORBIT_VIEWS = [
  { id: 'front', label: 'Frente', objectLabel: 'Frente', fraction: 0.02 },
  { id: 'right', label: 'Mirando derecha', objectLabel: 'Derecha', fraction: 0.25 },
  { id: 'back', label: 'Espalda', objectLabel: 'Trasera', fraction: 0.5 },
  { id: 'left', label: 'Mirando izquierda', objectLabel: 'Izquierda', fraction: 0.75 },
] as const

const ROLE_KEEP: Record<OrbitRefRole, string> = {
  subject: 'keep the complete subject: shape, colors, materials and identifying details',
  face: 'keep only the face, hair and art style; ignore body, wardrobe and background',
  outfit: 'keep only the outfit colors, cut, material and details; ignore any face, hair, background, floor and lighting',
  extra: 'keep this extra angle or appearance cue for the same subject; ignore background and lighting',
  accessory: 'keep only this attached prop or accessory; ignore background and any other person',
}

function pictureLine(index: number, role: OrbitRefRole, kind: OrbitSubjectKind): string {
  const noun = kind === 'object' && role === 'subject' ? 'object' : 'subject'
  return `<Picture ${index}> - ${ROLE_KEEP[role]}. This is a ${noun} reference only.`
}

function stagingPrompt(kind: OrbitSubjectKind): string {
  const freeze = kind === 'object'
    ? 'The object is completely frozen, as rigid as a studio product turntable. Only the camera moves. No secondary motion of any kind. The object stays the same size in frame.'
    : 'The character holds one relaxed A-pose throughout: arms hanging slightly away from the body, feet shoulder-width apart, head level, eyes open and looking forward. The subject is completely frozen, as rigid as a statue. Only the camera moves. Hair, fabric and accessories stay locked. No wind, no breathing, no sway.'
  return [
    'Solid light-grey seamless backdrop, one flat uniform tone edge to edge, with no gradient, no vignette, no texture and no floor line. Nothing else is in frame. The subject casts no shadow onto the backdrop and no contact shadow on the ground. Soft form shading on the subject itself is fine.',
    freeze,
    'Near-orthographic full view. The camera makes one smooth fixed-speed 360-degree clockwise orbit starting square on the front, passing the right side, the back, the left side, and returning to the front.',
  ].join(' ')
}

export function buildCharacterOrbitPrompt(
  kind: OrbitSubjectKind = 'character',
  refs: OrbitRefSpec[] = [{ role: 'subject' }, { role: 'outfit' }],
): string {
  const pictures = refs.length > 0 ? refs : [{ role: 'subject' as const }]
  const subjectLines = pictures.map((ref, index) => {
    const n = index + 1
    if (ref.role === 'face') {
      return `<Subject ${n}> is the identity from <Picture ${n}>; face, hair and art style stay fully visible.`
    }
    if (ref.role === 'outfit') {
      return `<Subject ${n}> is wardrobe taken from <Picture ${n}> as-is. Any face in that picture is ignored.`
    }
    if (ref.role === 'accessory') {
      return `<Subject ${n}> is the accessory from <Picture ${n}>, attached to the main subject.`
    }
    if (kind === 'object') {
      return `<Subject ${n}> is the object in <Picture ${n}>; keep its exact shape, colors, materials and markings.`
    }
    return `<Subject ${n}> is the complete character in <Picture ${n}>; keep identity, wardrobe and art style.`
  })
  const keepLines = pictures.map((ref, index) => pictureLine(index + 1, ref.role, kind))
  const retention = pictures.flatMap((ref, index) => {
    const n = index + 1
    return [
      `<Subject ${n}> (appears in [Shot 1]): fully_preserved - ${ROLE_KEEP[ref.role]}.`,
      `<Picture ${n}> ([Shot 1] ${ref.role}): fully_preserved - use it only for the requested traits; do not copy its background, framing or lighting.`,
    ]
  })
  const summaryNoun = kind === 'object' ? 'object' : 'character'
  return [
    `subject_definitions: ${subjectLines.join(' ')}`,
    '',
    `summary: [reference generation] A frozen ${summaryNoun} on a seamless grey backdrop while the camera completes one 360-degree orbit.`,
    '',
    `retention_analysis: ${retention.join(' ')}`,
    '',
    `detailed_description: [Shot 1] ${keepLines.join(' ')} ${stagingPrompt(kind)}`,
    '',
    'overall_soundscape: Silence. No music, no room tone, no voices.',
    '',
    'non_diegetic_music: N/A',
  ].join('\n')
}
