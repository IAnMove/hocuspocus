import { EXPRESSIONS, VISEMES, type Expression, type Viseme } from './types'

/** Cube-front rest plane. Fill `{skin}` with the material (felt, clay, gold spray…). */
export const FACE_PLANE_REST_PROMPT = [
  'A square Minecraft-style face texture for the front of a cube.',
  'The entire image is {skin} filling the frame edge to edge — only two eyes, a tiny nose and a short rest-mouth dash.',
  'No circular head silhouette, no 3/4 cube, no body, no ears outside the square, no background around a round face.',
  'Same skin color from corner to corner. Flat 2D skin plane, 1:1.',
].join(' ')

export const FACE_PLANE_LOCK = [
  'Keep this exact square face texture filling the entire frame —',
  'same skin, same color, same eye position, same nose, same scale.',
  'No circular head. Flat 2D cube-front skin.',
].join(' ')

export const VISEME_MOUTHS: Record<Exclude<Viseme, 'rest'>, string> = {
  M: 'Change only the mouth: press it fully closed into a thick sealed dash, like humming mmm, no opening.',
  A: 'Change only the mouth: a tall open oval, like saying ah.',
  E: 'Change only the mouth: a wide short rectangle showing a thin gap, like saying eh.',
  I: 'Change only the mouth: a slightly narrower opening than E, like saying ee.',
  O: 'Change only the mouth: a small round O, like saying oh.',
  U: 'Change only the mouth: a tiny tight circle, smaller than O, like saying oo.',
  F: 'Change only the mouth: closed lips with a thin upper-teeth line, like fff.',
  L: 'Change only the mouth: a short opening with a tongue bar, like lll.',
}

export const EXPRESSION_EYES: Record<Exclude<Expression, 'neutral'>, string> = {
  happy: 'Keep the rest mouth (short dash). Change only the eyes: happy crescent squints.',
  angry: 'Keep the rest mouth (short dash). Change only the eyes: angry glare, inner brows down in a V.',
  worried: 'Keep the rest mouth (short dash). Change only the eyes: inner brows up and pinched, smaller anxious eyes.',
  surprised: 'Keep the rest mouth (short dash). Change only the eyes: huge round dilated pupils.',
  sleepy: 'Keep the rest mouth (short dash). Change only the eyes: half-lidded drooping eyes.',
}

export const VISEME_ALIASES: Partial<Record<Viseme, Viseme>> = { I: 'E', U: 'O', F: 'M', L: 'A' }

export function fillFacePrompt(template: string, skin: string) {
  const material = skin.trim() || 'cream skin'
  return template.replaceAll('{skin}', material)
}

export function visemePrompt(viseme: Exclude<Viseme, 'rest'>, skin = '') {
  const lock = fillFacePrompt(FACE_PLANE_LOCK, skin)
  return `${lock} ${VISEME_MOUTHS[viseme]}`
}

export function expressionPrompt(expression: Exclude<Expression, 'neutral'>, skin = '') {
  const lock = fillFacePrompt(FACE_PLANE_LOCK, skin)
  return `${lock} ${EXPRESSION_EYES[expression]}`
}

const VIS_BY_LOWER = new Map(VISEMES.map(id => [id.toLowerCase(), id]))
const EXPR_BY_LOWER = new Map(EXPRESSIONS.map(id => [id.toLowerCase(), id]))

export function parseFacePackStillName(filename: string): { kind: 'rest' } | { kind: 'viseme'; id: Viseme } | { kind: 'expression'; id: Expression } | undefined {
  const base = filename.trim().toLowerCase().replace(/\.[a-z0-9]+$/, '')
  const token = base.split(/[/\\]/).pop() ?? base
  const name = token.replace(/^(viseme|mouth|expr|expression|face)[-_]/, '')
  if (name === 'rest' || name === 'neutral' || name === 'plane' || name === 'canonical') return { kind: 'rest' }
  const viseme = VIS_BY_LOWER.get(name)
  if (viseme) return viseme === 'rest' ? { kind: 'rest' } : { kind: 'viseme', id: viseme }
  const expression = EXPR_BY_LOWER.get(name)
  if (expression) return expression === 'neutral' ? { kind: 'rest' } : { kind: 'expression', id: expression }
  return undefined
}
