// The Face Rig mouth line editor's model (flat-rig warp mouths). Everything is in % of the pose image the rig reads
// (the keyed original, before the rig cropped it), as the rig's hints are: a point on the line between the lips and
// the mouth's width corner to corner.
import type { CharacterKit } from './characterKit'
import type { FlatRigHint, FlatRigMouthLine } from '../api/characters'

export type MouthLineDraft = { mouth: [number, number]; mouthWidth: number }
/** A square window of the pose image, in % of its width (x, width) and height (y, height). */
export type MouthZoom = { x: number; y: number; width: number; height: number }

/** The states the editor previews: rest, then the vowels i, e, a, o, u. */
export const MOUTH_LINE_PREVIEW_STATES = [
  { state: 'closed', sound: 'rest' }, { state: 'small', sound: 'i' }, { state: 'medium', sound: 'e' },
  { state: 'wide', sound: 'a' }, { state: 'round', sound: 'o' }, { state: 'pucker', sound: 'u' },
] as const

export const MOUTH_WIDTH_LIMITS = [0.5, 100] as const

/** The Face Rig's busy state while the mouth line editor saves: it takes the slot when it starts and frees only its own. */
export function mouthLineBusyState<T>(current: T | 'mouth-line' | null, busy: boolean): T | 'mouth-line' | null {
  if (busy) return 'mouth-line'
  return current === 'mouth-line' ? null : current
}

/** Whether other Face Rig work than the mouth line editor's is running. */
export function otherFaceRigWork(current: string | null): boolean {
  return Boolean(current) && current !== 'mouth-line'
}

type RigEntry = { method?: unknown; sources?: Record<string, string>; hints?: Record<string, FlatRigHint>
  style?: Record<string, number | boolean | string>; mouthLines?: Record<string, FlatRigMouthLine> }

function lastRig(kit: CharacterKit): RigEntry | undefined {
  return [...kit.provenance].reverse().find(entry => entry.method === 'flat-rig') as RigEntry | undefined
}

/** Whether the flat rig made this kit (only then can the editor re-rig a pose). */
export function isFlatRigged(kit: CharacterKit): boolean {
  return Boolean(lastRig(kit))
}

/** Whether the kit's last rig made warp mouths. */
export function isWarpRigged(kit: CharacterKit): boolean {
  return lastRig(kit)?.style?.mouthStyle === 'warp'
}

const MOUTH_LINE_WARNINGS = new Set(['mouth_line_guessed', 'mouth_line_unsure'])

/** The poses a rig flagged (its `warnings`): those whose warp mouth line is worth placing by hand in the mouth line
 * editor, and those with another warning (eyes or a mark found in the wrong place). */
export function flaggedRigPoses(warnings: Record<string, string[]> = {}): { mouthLine: string[]; other: string[] } {
  const poses = (test: (code: string) => boolean) => Object.entries(warnings)
    .filter(([, codes]) => codes.some(test)).map(([pose]) => pose).sort((a, b) => Number(b === 'base') - Number(a === 'base') || a.localeCompare(b))
  return { mouthLine: poses(code => MOUTH_LINE_WARNINGS.has(code)), other: poses(code => !MOUTH_LINE_WARNINGS.has(code)) }
}

/** The image a pose is rigged from: the recorded original stands in for the rig's own output (as the server does). */
export function flatRigPoseSource(kit: CharacterKit, poseId: string): string | undefined {
  const current = poseId === 'base' ? kit.base?.source : kit.poses[poseId]?.source
  const original = lastRig(kit)?.sources?.[poseId]
  return original && current?.includes(`kit-${kit.id}-${poseId}-rig-`) ? original : current
}

/** The pose's saved mouth line: its hint, else the line the last warp rig found. */
export function savedMouthLine(kit: CharacterKit, poseId: string): MouthLineDraft | undefined {
  const rig = lastRig(kit)
  const hint = rig?.hints?.[poseId], line = rig?.mouthLines?.[poseId]
  const mouth = hint?.mouth ?? line?.mouth
  const width = hint?.mouthWidth ?? line?.mouthWidth
  return mouth && width ? { mouth: [mouth[0], mouth[1]], mouthWidth: width } : undefined
}

const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))
const round = (value: number) => Math.round(value * 1000) / 1000

export function cleanMouthLine(draft: MouthLineDraft): MouthLineDraft {
  return { mouth: [round(clamp(draft.mouth[0], 0, 100)), round(clamp(draft.mouth[1], 0, 100))],
    mouthWidth: round(clamp(draft.mouthWidth, ...MOUTH_WIDTH_LIMITS)) }
}

export function sameMouthLine(a?: MouthLineDraft, b?: MouthLineDraft): boolean {
  if (!a || !b) return a === b
  return Math.abs(a.mouth[0] - b.mouth[0]) < 0.01 && Math.abs(a.mouth[1] - b.mouth[1]) < 0.01
    && Math.abs(a.mouthWidth - b.mouthWidth) < 0.01
}

/** A square window round the mouth, `span` mouth widths across, inside the image when it can be. */
export function mouthZoom(draft: MouthLineDraft, aspect: number, span = 4.5): MouthZoom {
  const width = clamp(draft.mouthWidth * span, 2, 100)
  const height = Math.min(100, width * aspect)
  const square = height < width * aspect ? height / aspect : width
  const top = clamp(draft.mouth[1] - height * 0.42, 0, 100 - height)
  return { x: clamp(draft.mouth[0] - square / 2, 0, 100 - square), y: top, width: square, height }
}

/** A point in the zoom box (0-1 across and down) as % of the pose image, and back. */
export function zoomToImage(zoom: MouthZoom, fx: number, fy: number): [number, number] {
  return [zoom.x + clamp(fx, 0, 1) * zoom.width, zoom.y + clamp(fy, 0, 1) * zoom.height]
}

export function imageToZoom(zoom: MouthZoom, x: number, y: number): [number, number] {
  return [(x - zoom.x) / zoom.width * 100, (y - zoom.y) / zoom.height * 100]
}

/** How the zoom box shows the pose image: its size and offset in % of the box. */
export function zoomImageStyle(zoom: MouthZoom) {
  return { width: `${10000 / zoom.width}%`, height: `${10000 / zoom.height}%`,
    left: `${-zoom.x / zoom.width * 100}%`, top: `${-zoom.y / zoom.height * 100}%` }
}

/** The re-rig that saves a pose's mouth line: warp mouths in the kit's last look and the pose's hint with this line
 * (its eyes hint kept). A warp kit re-rigs that pose and the base (the rig always takes it: the blink comes from
 * it); a kit switching to warp mouths re-rigs every pose, since in a warp kit a pose without mouths of its own shows
 * none. */
export function mouthLineRigRequest(kit: CharacterKit, poseId: string, draft: MouthLineDraft) {
  const rig = lastRig(kit)
  const clean = cleanMouthLine(draft)
  const eyes = rig?.hints?.[poseId]?.eyes
  return {
    ...(isWarpRigged(kit) ? { poses: [...new Set(['base', poseId])] } : {}),
    style: { ...(rig?.style ?? {}), mouthStyle: 'warp' },
    // Placed by a person on the image: the rig keeps it there (exact) instead of snapping it or trusting the landmarks.
    hints: { [poseId]: { ...(eyes ? { eyes } : {}), mouth: clean.mouth, mouthWidth: clean.mouthWidth, exact: true } } as Record<string, FlatRigHint>,
  }
}
