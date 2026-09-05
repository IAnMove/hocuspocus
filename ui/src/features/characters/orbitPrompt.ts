export type OrbitSubjectKind = 'character' | 'object'
export type OrbitRefRole = 'subject' | 'face' | 'outfit' | 'extra' | 'accessory'
export type HunyuanView = 'front' | 'left' | 'right' | 'back'

export interface OrbitRefSpec {
  role: OrbitRefRole
}

/** PoopMan333 6-panel body grabs (H3_CharSheetMaker_6_Panel.json ImageFromBatch). */
export const CHARACTER_ORBIT_VIEWS = [
  { id: 'front', hunyuan: 'front' as const, label: 'Frente', objectLabel: 'Frente', frame: 2 },
  { id: 'left', hunyuan: 'left' as const, label: 'Izquierda', objectLabel: 'Izquierda', frame: 21 },
  { id: 'back', hunyuan: 'back' as const, label: 'Espalda', objectLabel: 'Trasera', frame: 42 },
  { id: 'right', hunyuan: 'right' as const, label: 'Derecha', objectLabel: 'Derecha', frame: 63 },
] as const

export const CHARACTER_SHEET_RESOLUTION = '768x1344'
// PoopMan333's 6-panel workflow uses H3's native five-second pass. The four
// geometry views are sampled from its first 3-second orbit beat.
export const CHARACTER_SHEET_FRAMES = 124
export const CHARACTER_SHEET_STEPS = 25
export const CHARACTER_SHEET_FPS = 24

const ROLE_KEEP: Record<OrbitRefRole, string> = {
  subject: 'keep the complete subject: shape, colors, materials, wardrobe and identifying details. Ignore the background, floor and lighting',
  face: 'keep only the face, hair and art style. Ignore body, wardrobe, background, floor and lighting',
  outfit: 'keep only the outfit colors, cut, material and details. Remove any face, hair, background, floor and lighting',
  extra: 'keep this extra angle or appearance cue for the same subject. Ignore background, floor and lighting',
  accessory: 'keep only this attached prop or accessory. Ignore background, floor, lighting and any other person',
}

export function viewCaptureTime(frame: number, fps = CHARACTER_SHEET_FPS): number {
  return Math.max(0, frame / fps)
}

export function buildAPrompt(
  kind: OrbitSubjectKind = 'character',
  refs: OrbitRefSpec[] = [{ role: 'subject' }],
): string {
  const pictures = refs.length > 0 ? refs : [{ role: 'subject' as const }]
  return pictures.map((ref, index) => {
    const n = index + 1
    const noun = kind === 'object' && ref.role === 'subject' ? 'object' : 'subject'
    return `<Picture ${n}> - ${ROLE_KEEP[ref.role]}. This is a ${noun} reference only.`
  }).join('\n')
}

const SHARED_STAGING = [
  'Solid light grey seamless backdrop, one flat uniform tone edge to edge, with no gradient, no vignette, no texture and no floor line. Nothing else is in frame. the subject casts no shadow onto the backdrop and no contact shadow on the ground beneath it, and it does not sit in its own shadow. Soft form shading on the subject itself is fine and should read its shape. Long telephoto lens, near-orthographic.',
].join(' ')

const STATUE_LOCK = [
  'The subject is a rigid physical statue or mannequin on a turntable. Every body part, hand, face, hair strand, garment, fold and attached prop is locked together as one solid object. The only allowed motion is the entire subject rotating rigidly around its vertical center axis; the subject rotates as one rigid object. There is no walking, acting, talking, breathing, blinking, gesturing, looking around, cloth motion, hair motion or independent body movement. The subject remains centered and the same size in every frame.',
].join(' ')

const TURN_TABLE_360 = [
  '[0-3 seconds] tight full shot of the subject. The camera makes one smooth fixed-speed orbit right around it, a full 360 degrees: starting square on the front, passing the left side a quarter of the way round, directly behind at halfway, the right side three quarters of the way round, and returning to the front. The subject does not move at all. Ends back on the front view at 3 seconds.',
  '[3-4 seconds] Camera snaps into a fast push-in on the character\'s face. Locked-off head and shoulders close-up, face square to camera, eyes into the lens. Ends on a sharp front-on face at 4 seconds.',
  '[4-5 seconds] Camera whip-pans and rotates to an orthogonal angle. Locked-off head and shoulders close-up, head turned to a three-quarter angle, eyes still forward. Ends on a clean three-quarter face.',
].join(' ')

/** Official B prompt from PoopMan333 6-panel workflow (Keep Picture 1's Style). */
export const CHARACTER_ORBIT_B_PROMPT = `[STYLE]
The output is matches the style of <Picture 1>. Sharp detail on eyes and face. The style never changes and never drifts between shots. No shadows.

[STAGING]
${SHARED_STAGING}

The character holds one relaxed A-pose throughout: arms hanging slightly away from the body, palms toward the thighs, feet shoulder-width apart, head level, calm neutral expression, eyes open and looking forward. The character keeps the exact same pose, expression, clothing, hair and attached props from the reference throughout the rotation. Do not reposition the hands, limbs or props.
${STATUE_LOCK}

${TURN_TABLE_360}

[CAMERA] One constant-speed orbit in beat 1, then locked off and static. The camera is the only thing in the scene that moves at any point. No zoom, no dolly, no tilt, no roll, no handheld shake, no motion blur, no dissolves beyond the intended beat changes.
[AUDIO] Silence. No music, no room tone, no voices.
`

export const OBJECT_ORBIT_B_PROMPT = `[STYLE]
The output is matches the style of <Picture 1>. Sharp detail on silhouette and materials. The style never changes and never drifts between shots. No shadows.

[STAGING]
${SHARED_STAGING}

The object is completely frozen, as rigid as a studio product turntable. Only the camera moves. No secondary motion of any kind.
${STATUE_LOCK}

${TURN_TABLE_360}

[CAMERA] One constant-speed orbit in beat 1, then locked off and static. The camera is the only thing in the scene that moves at any point. No zoom, no dolly, no tilt, no roll, no handheld shake, no motion blur, no dissolves beyond the intended beat changes.
[AUDIO] Silence. No music, no room tone, no voices.
`

export function buildOrbitBPrompt(kind: OrbitSubjectKind = 'character'): string {
  return kind === 'object' ? OBJECT_ORBIT_B_PROMPT : CHARACTER_ORBIT_B_PROMPT
}

export function buildCharacterOrbitPrompt(
  kind: OrbitSubjectKind = 'character',
  refs: OrbitRefSpec[] = [{ role: 'subject' }, { role: 'outfit' }],
  aPrompt?: string,
): string {
  const a = (aPrompt ?? buildAPrompt(kind, refs)).trim()
  return `${a}\n\n${buildOrbitBPrompt(kind)}`
}

export function needsVisionDescribe(aPrompt: string | null | undefined): boolean {
  return !String(aPrompt || '').trim()
}
