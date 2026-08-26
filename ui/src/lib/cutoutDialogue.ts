import type { SceneKeyframe, SceneLayer } from '../types'

export type CutoutViseme = 'closed' | 'small' | 'wide' | 'round'

export type CutoutDialoguePlan = {
  start: number
  end: number
  visemes: Array<{ start: number; end: number; state: CutoutViseme }>
}

type MouthLayerPair = {
  open: SceneLayer
  closed?: SceneLayer
}

const VOWEL = /[aeiouáéíóúäëïöü]/i
const ROUND_VOWEL = /[ouóúöü]/i
const pointFor = (layer: SceneLayer, time: number, opacity: number): SceneKeyframe => {
  const reference = layer.animation.keyframes?.[0] ?? layer.animation.start
  return {
    id: `${layer.id}-dialogue-${Math.round(time * 1000)}`,
    time,
    x: reference.x,
    y: reference.y,
    scale: reference.scale,
    opacity,
    rotation: reference.rotation ?? 0,
    curve: 'hold',
  }
}

/**
 * Turns known dialogue into intentionally limited animation. This is not an
 * attempt at phoneme-perfect lipsync: it creates a readable held/snap rhythm
 * at a bounded cadence, so it remains coherent with paper-cutout characters.
 */
export function planCutoutDialogue(text: string, start: number, end: number, fps = 30): CutoutDialoguePlan {
  const safeStart = Math.max(0, start)
  const safeEnd = Math.max(safeStart + 1 / Math.max(1, fps), end)
  const glyphs = [...text.replace(/\s+/g, ' ').trim()]
  if (!glyphs.length) return { start: safeStart, end: safeEnd, visemes: [{ start: safeStart, end: safeEnd, state: 'closed' }] }
  const frame = 1 / Math.max(1, fps)
  const minHold = Math.max(frame * 2, .12)
  const available = safeEnd - safeStart
  const maxBeats = Math.max(2, Math.floor(available / minHold))
  const stride = Math.max(1, Math.ceil(glyphs.length / maxBeats))
  const beats = glyphs.filter((_, index) => index % stride === 0 || index === glyphs.length - 1)
  const interval = available / Math.max(1, beats.length)
  const visemes = beats.map((glyph, index) => {
    const beatStart = safeStart + interval * index
    const beatEnd = index === beats.length - 1 ? safeEnd : Math.max(beatStart + frame, safeStart + interval * (index + 1))
    const state: CutoutViseme = /[.,;:!?—-]/.test(glyph) || !VOWEL.test(glyph)
      ? 'closed'
      : ROUND_VOWEL.test(glyph) ? 'round' : /[aeáé]/i.test(glyph) ? 'wide' : 'small'
    return { start: beatStart, end: beatEnd, state }
  })
  // First and last frames should always settle on a closed mouth so a cut into
  // or out of the shot does not freeze on an arbitrary open shape.
  visemes[0] = { ...visemes[0], state: 'closed' }
  visemes[visemes.length - 1] = { ...visemes[visemes.length - 1], state: 'closed' }
  // Word-aligned transcription commonly supplies very short units ("la",
  // "de", "sí"). A two-beat unit would otherwise become closed/closed
  // after the edge guard. Preserve one readable centre pulse whenever the
  // word has a vowel; its terminal closed keyframe still protects edits/cuts.
  if (!visemes.some(beat => beat.state !== 'closed') && glyphs.some(glyph => VOWEL.test(glyph)) && available >= frame * 3) {
    const middle = safeStart + available / 2
    return {
      start: safeStart,
      end: safeEnd,
      visemes: [
        { start: safeStart, end: middle, state: 'closed' },
        { start: middle, end: safeEnd, state: ROUND_VOWEL.test(glyphs.join('')) ? 'round' : 'wide' },
        { start: safeEnd, end: safeEnd, state: 'closed' },
      ],
    }
  }
  return { start: safeStart, end: safeEnd, visemes }
}

export function applyCutoutDialogue(pair: MouthLayerPair, plan: CutoutDialoguePlan): Record<string, SceneKeyframe[]> {
  const openFrames: SceneKeyframe[] = []
  const closedFrames: SceneKeyframe[] = []
  for (const beat of plan.visemes) {
    const isOpen = beat.state !== 'closed'
    openFrames.push(pointFor(pair.open, beat.start, Number(isOpen)))
    if (pair.closed) closedFrames.push(pointFor(pair.closed, beat.start, Number(!isOpen)))
  }
  // Keyframe arrays need a terminal pose even when the final beat began before
  // the requested end, otherwise an imported scene may normalize it away.
  const last = plan.visemes.at(-1)
  if (!last || last.start < plan.end) {
    openFrames.push(pointFor(pair.open, plan.end, 0))
    if (pair.closed) closedFrames.push(pointFor(pair.closed, plan.end, 1))
  }
  return {
    [pair.open.id]: openFrames,
    ...(pair.closed ? { [pair.closed.id]: closedFrames } : {}),
  }
}
