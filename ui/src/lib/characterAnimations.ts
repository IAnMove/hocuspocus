import catalog from '../../../app/shared/character_animations.json' with { type: 'json' }
import type { CharacterKit, CharacterKitReviewState } from './characterKit'

/** Small animations of one character: a few poses of the same figure joined into an equal-cell sprite sheet.
 * Shared with MCP through app/shared/character_animations.json (see services/character_animations.py). */
export type AnimationLoop = 'loop' | 'pingpong' | 'once'
export type AnimationFacing = 'left' | 'right' | 'front'
export type AnimationGroupId = 'cycle' | 'gesture' | 'expression' | 'custom'
export type Localized = { es: string; en: string }
export type AnimationPoseDef = { id: string; label: Localized; prompt: string }
/** What keeps the figure one size from pose to pose: its height (cycles), the width of its legs (a standing gesture) or the size of its
 * head (a bust, read with the face landmarks; the server falls back to the height when it finds no face). */
export type AnimationScaleBy = 'height' | 'base' | 'face'
export type AnimationDef = {
  id: string; group: AnimationGroupId; view: 'side' | 'front' | 'bust'; scaleBy: AnimationScaleBy; facing: AnimationFacing; loop: AnimationLoop
  fps: number; template: string; resolution: string; title: Localized; summary: Localized; poses: AnimationPoseDef[]
  /** An animation the author described, not one the catalog lists: its poses are made from the words in `poses[].prompt`. */
  custom?: boolean
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
  frames: Array<{ id: string; source: string; prompt?: string; label?: string }>
  fps: number; loop: AnimationLoop; facing: AnimationFacing; reviewState: CharacterKitReviewState
  view?: string; title?: string; scaleBy?: AnimationScaleBy; prompt?: string; model?: string; createdAt?: string
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

/** The controls a Video 2D card needs to play a made animation. A cycle plays at its step (two steps make a cycle, one for a two-pose sheet); a
 * reaction plays at its own fps and loop. */
export function templateControls(animation: KitAnimation, template: string): Record<string, number | string> {
  const sheet = { frames: animation.sheet.count, columns: animation.sheet.columns }
  if (template === 'walk-cycle-sheet' || template === 'walk-two-pose') {
    // A cycle of the gait is two steps; a two-pose sheet is one.
    const steps = template === 'walk-cycle-sheet' ? 2 : 1
    return { ...sheet, facing: animation.facing === 'left' ? 'left' : 'right', step: Math.min(1, Math.max(.3, +(sheet.frames / (steps * animation.fps)).toFixed(2))) }
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

const CUSTOM_VIEWS = { bust: '1024x1024', front: '896x1152', side: '896x1152' } as const
export type CustomView = keyof typeof CUSTOM_VIEWS
export const customViews = Object.keys(CUSTOM_VIEWS) as CustomView[]
/** The most poses of one animation the author describes, and the most words for one pose (the server's limit). */
export const MAX_CUSTOM_POSES = 6
export const MAX_CUSTOM_TEXT = 600
/** The catalog lists 34; a kit also keeps the author's own. Must match ``character_animations.MAX_ANIMATIONS``. */
export const MAX_ANIMATIONS = 48

/** A slug for an animation the author names: lowercase letters and digits, no accents, one hyphen between words. */
export function animationSlug(name: string): string {
  const slug = name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/g, '')
  return slug || 'animacion'
}

/** A slug that no catalog animation and no animation of the kit has yet. */
export function freeAnimationId(kit: CharacterKit, name: string): string {
  const base = animationSlug(name)
  const taken = (id: string) => Boolean(animationDef(id)) || Boolean(kit.animations?.[id])
  let id = base
  for (let count = 2; taken(id); count += 1) id = `${base.slice(0, 36)}-${count}`
  return id
}

const poseLabel = (text: string) => text.replace(/^(anime expression|expression)\s*:\s*/i, '').split(/\s+/).slice(0, 4).join(' ').replace(/[.,;:]+$/, '')

/** The definition of an animation the author describes: one pose per line, made like the catalog's from the character's picture. */
export function customAnimationDef(id: string, title: string, view: CustomView, lines: string[]): AnimationDef {
  const poses = lines.map(line => line.trim()).filter(Boolean).slice(0, MAX_CUSTOM_POSES)
  return {
    id, group: 'custom', view, scaleBy: ({ front: 'base', bust: 'face', side: 'height' } as const)[view], facing: view === 'side' ? 'right' : 'front', loop: 'once', fps: 3,
    template: 'character-reaction', resolution: CUSTOM_VIEWS[view], title: { es: title, en: title }, summary: { es: '', en: '' }, custom: true,
    poses: poses.map((prompt, index) => ({ id: `pose-${index + 1}`, label: { es: poseLabel(prompt), en: poseLabel(prompt) }, prompt: prompt.slice(0, MAX_CUSTOM_TEXT) })),
  }
}

/** The animations of a kit that the catalog does not list, as definitions: what the author wrote is kept on the kit, so any pose
 * of them can be made again alone. */
export function kitCustomDefs(kit: CharacterKit): AnimationDef[] {
  return Object.entries(kit.animations ?? {}).filter(([id]) => !animationDef(id)).map(([id, made]) => {
    const view = (customViews as string[]).includes(made.view ?? '') ? made.view as CustomView : 'bust'
    const def = customAnimationDef(id, made.title || id, view, made.frames.map(frame => frame.prompt ?? ''))
    // A pose whose words were not kept stays in its place (and cannot be made again alone).
    return { ...def, loop: made.loop, fps: made.fps, facing: made.facing, poses: made.frames.map(frame => ({ id: frame.id, label: { es: frame.label ?? frame.id, en: frame.label ?? frame.id }, prompt: frame.prompt ?? '' })) }
  })
}

/** Whether a kit can take one more animation. */
export const canAddAnimation = (kit: CharacterKit): boolean => Object.keys(kit.animations ?? {}).length < MAX_ANIMATIONS
