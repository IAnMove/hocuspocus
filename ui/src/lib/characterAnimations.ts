import catalog from '../../../app/shared/character_animations.json' with { type: 'json' }
import type { CharacterKit, CharacterKitReviewState } from './characterKit'

/** Small animations of one character: a few poses of the same figure joined into an equal-cell sprite sheet.
 * Shared with MCP through app/shared/character_animations.json (see services/character_animations.py). */
export type AnimationLoop = 'loop' | 'pingpong' | 'once'
export type AnimationFacing = 'left' | 'right' | 'front'
export type AnimationGroupId = 'cycle' | 'gesture' | 'expression'
export type Localized = { es: string; en: string }
export type AnimationPoseDef = { id: string; label: Localized; prompt: string }
export type AnimationDef = {
  id: string; group: AnimationGroupId; view: 'side' | 'front' | 'bust'; facing: AnimationFacing; loop: AnimationLoop
  fps: number; template: string; resolution: string; title: Localized; summary: Localized; poses: AnimationPoseDef[]
}

/** The sheet's contract with the Video 2D cards: boots (or the bottom of a bust) on the line `feet` of a cell, the figure
 * `figure` of the cell's height, at most `maxPoses` cells. */
export const ANIMATION_SHEET = catalog.sheet
export const animationDefs = catalog.animations as AnimationDef[]
export const animationGroups = catalog.groups as Array<{ id: AnimationGroupId; title: Localized }>

export const animationDef = (id: string): AnimationDef | undefined => animationDefs.find(item => item.id === id)
export const localized = (text: Localized, language: string): string => language.startsWith('es') ? text.es : text.en
export const animationsOf = (group: AnimationGroupId): AnimationDef[] => animationDefs.filter(item => item.group === group)

export type KitAnimationSheet = {
  source: string; width: number; height: number; count: number; columns: number; rows: number
  cell: { width: number; height: number }
}
export type KitAnimation = {
  sheet: KitAnimationSheet
  /** The keyed pose pictures the sheet was joined from, in order: one can be made again without the others. */
  frames: Array<{ id: string; source: string }>
  fps: number; loop: AnimationLoop; facing: AnimationFacing; reviewState: CharacterKitReviewState
  view?: string; prompt?: string; model?: string; createdAt?: string
}
export type AnimationState = 'none' | CharacterKitReviewState

export const kitAnimations = (kit: CharacterKit): Record<string, KitAnimation> => kit.animations ?? {}

export function animationState(kit: CharacterKit, id: string): AnimationState {
  return kit.animations?.[id]?.reviewState ?? 'none'
}

/** The picture every pose is made from: the character's own identity, never a pose of an animation. */
export function animationReference(kit: CharacterKit): string | undefined {
  const source = (kit.identityReference ?? kit.base)?.source
  return source && !source.startsWith('blob:') ? source : undefined
}

/** What the model is told about the character: the look the author wrote, else its name. */
export const animationDescription = (kit: CharacterKit): string => kit.lookNotes?.trim() || kit.name

/** The style preset a kit was made in (its provenance records it), so poses keep that look. */
export function kitStyleId(kit: CharacterKit): string | undefined {
  const made = kit.provenance.find(entry => entry.method === 'character-style-create' && typeof entry.style === 'string')
  return made ? String(made.style) : undefined
}

/** A made animation joins the kit as pending: a person plays it and approves it before a scene uses it. */
export function withKitAnimation(kit: CharacterKit, id: string, animation: Omit<KitAnimation, 'reviewState'>, now = new Date()): CharacterKit {
  const stamp = now.toISOString()
  return {
    ...kit, animations: { ...kit.animations, [id]: { ...animation, reviewState: 'pending', createdAt: animation.createdAt ?? stamp } },
    provenance: [...kit.provenance, { method: 'character-animation-make', animation: id, frames: animation.frames.map(frame => frame.id), model: animation.model }].slice(-500),
    updatedAt: stamp,
  }
}

export function reviewKitAnimation(kit: CharacterKit, id: string, reviewState: CharacterKitReviewState, now = new Date()): CharacterKit {
  const current = kit.animations?.[id]
  if (!current) throw new Error(`Character Kit “${kit.name}” has no ${id} animation.`)
  return { ...kit, animations: { ...kit.animations, [id]: { ...current, reviewState } }, updatedAt: now.toISOString() }
}

export function withoutKitAnimation(kit: CharacterKit, id: string, now = new Date()): CharacterKit {
  const rest = Object.fromEntries(Object.entries(kit.animations ?? {}).filter(([key]) => key !== id))
  const next: CharacterKit = { ...kit, updatedAt: now.toISOString() }
  if (Object.keys(rest).length) next.animations = rest
  else delete next.animations
  return next
}

/** Which cell of the sheet shows `seconds` into the animation: the Video 2D sheet sequence's own rule. */
export function animationFrame(animation: Pick<KitAnimation, 'fps' | 'loop'> & { sheet: Pick<KitAnimationSheet, 'count'> }, seconds: number): number {
  const count = Math.max(1, animation.sheet.count)
  const raw = Math.floor(Math.max(0, seconds) * animation.fps)
  if (animation.loop === 'once') return Math.min(count - 1, raw)
  if (animation.loop === 'pingpong') {
    const cycle = Math.max(1, count * 2 - 2)
    const at = raw % cycle
    return at < count ? at : cycle - at
  }
  return raw % count
}

/** CSS that shows one cell of a sheet: the sheet scaled to the grid and shifted to the cell. */
export function sheetCellStyle(sheet: Pick<KitAnimationSheet, 'columns' | 'rows' | 'source'>, index: number): Record<string, string> {
  const column = index % sheet.columns
  const row = Math.floor(index / sheet.columns)
  const place = (at: number, of: number) => of > 1 ? `${(at / (of - 1)) * 100}%` : '0%'
  return {
    backgroundImage: `url("${sheet.source}")`, backgroundRepeat: 'no-repeat',
    backgroundSize: `${sheet.columns * 100}% ${sheet.rows * 100}%`, backgroundPosition: `${place(column, sheet.columns)} ${place(row, sheet.rows)}`,
  }
}

/** The controls a Video 2D card needs to play a made animation. A cycle plays at its step (two steps make a cycle); a
 * reaction plays at its own fps and loop. */
export function templateControls(animation: KitAnimation, template: string): Record<string, number | string> {
  const sheet = { frames: animation.sheet.count, columns: animation.sheet.columns }
  if (template === 'walk-cycle-sheet') {
    return { ...sheet, facing: animation.facing === 'left' ? 'left' : 'right', step: Math.min(1, Math.max(.3, +(sheet.frames / (2 * animation.fps)).toFixed(2))) }
  }
  return { ...sheet, fps: animation.fps, loop: animation.loop }
}

/** The made animation whose sheet is this workspace file (a sheet picked in a template slot), with the kit it belongs to. */
export function findKitAnimationBySheet(kits: CharacterKit[], filename: string | undefined): { kit: CharacterKit; id: string; animation: KitAnimation } | undefined {
  if (!filename) return undefined
  const named = (source: string) => decodeURIComponent(source.split('?')[0].split('/').pop() ?? '')
  for (const kit of kits) {
    for (const [id, animation] of Object.entries(kit.animations ?? {})) {
      if (named(animation.sheet.source) === filename) return { kit, id, animation }
    }
  }
  return undefined
}

type CardControl = { readonly kind: string; readonly options?: readonly string[]; readonly min?: number; readonly max?: number }

/** `templateControls` for a card, kept to the controls the card has and to values it accepts (a choice it lists, a number inside
 * its range), so a sheet made for another card never sets a control this one lacks. */
export function controlsForCard(animation: KitAnimation, template: string, controls: Readonly<Record<string, CardControl>>): Record<string, number | string> {
  const fits = (spec: CardControl, value: number | string) => spec.kind === 'choice' ? Boolean(spec.options?.includes(String(value)))
    : typeof value === 'number' && value >= (spec.min ?? -Infinity) && value <= (spec.max ?? Infinity)
  return Object.fromEntries(Object.entries(templateControls(animation, template)).filter(([name, value]) => controls[name] && fits(controls[name], value)))
}
