// The perspective of a 2D location plate (``location.layout2d.stage``): the size of a person comes from where their feet
// stand and how tall they are, not from the framing alone. Mirrors app/services/series_stage.py (a table in
// tests/fixtures/series_stage_table.json holds both to the same numbers); see that file for the model.
//
// All plate numbers are fractions of the plate's height from the top. A camera at eye height looks level, so the horizon
// is the y of the eye line and a person h metres tall with their feet at y is, on the plate,
//   h / ref.heightM * ref.heightPct * (y - horizon) / (ref.baseY - horizon)
// of its height. ``depth`` (0 far, 1 near, as a set layer's) moves the feet from the far floor line to the framing's feet line.

/** One object of known height standing on the floor, and where the camera's eye line is. */
export type Stage = { horizon: number; ref: { baseY: number; heightPct: number; heightM: number }; floorTop?: number }
/** How the plate is shown in the frame: its zoom and the frame y (%) of its centre (``backgroundLayer``). */
export type PlateView = { zoom: number; y: number }

/** The framing's feet line (% of the frame height) where a cast member stands at depth 1. */
export const FEET_LINE = 94
/** A standing adult, for a character that says no height. */
export const ADULT_M = 1.75
/** The framings that follow the stage; medium shots and close-ups keep their eye-line framing. */
export const STAGE_FRAMINGS = ['wide', 'two'] as const
/** The margin the rig leaves around a figure, as a share of the pose image's longest side (``flat_rig.crop_figure``). */
export const FIGURE_MARGIN = 0.02
/** The least a figure's feet may be below the horizon (plate fraction): at it the perspective height is nil. */
const MIN_BELOW = 0.01
const round = (value: number) => Math.round(value * 1000) / 1000

/** Where a plate y (fraction) falls in the frame (%). */
export function frameY(view: PlateView, plate: number): number {
  return view.y + (plate - 0.5) * 100 * view.zoom
}

/** The plate y (fraction) a frame y (%) shows. */
export function plateY(view: PlateView, frame: number): number {
  return 0.5 + (frame - view.y) / (100 * view.zoom)
}

/** A figure's height as a fraction of the plate height when its feet are at plate y ``feet``. */
export function perspectiveHeight(stage: Stage, heightM: number, feet: number): number {
  const below = Math.max(feet - stage.horizon, MIN_BELOW)
  return heightM / stage.ref.heightM * stage.ref.heightPct * below / (stage.ref.baseY - stage.horizon)
}

/** The feet line and height (both % of the frame height) of a ``heightM`` figure standing at ``depth`` on the plate in ``view``.
 * ``near`` is the frame feet line of depth 1. */
export function stageStanding(stage: Stage, heightM: number, depth: number, view: PlateView, near = FEET_LINE): { feetY: number; height: number } {
  const far = stage.floorTop ?? stage.ref.baseY
  const nearPlate = Math.max(plateY(view, near), far)
  const feet = far + (nearPlate - far) * depth
  return { feetY: round(frameY(view, feet)), height: round(perspectiveHeight(stage, heightM, feet) * 100 * view.zoom) }
}

/** What the perspective gives (% of the frame height) for a figure whose feet are at frame y ``feet``. */
export function expectedHeight(stage: Stage, heightM: number, feet: number, view: PlateView): number {
  return perspectiveHeight(stage, heightM, plateY(view, feet)) * 100 * view.zoom
}

/** The share of a pose image's height the figure takes: the rig crops each pose with ``FIGURE_MARGIN`` above and below the figure. */
export function figureShare(size: { width: number; height: number }): number {
  return Math.max(0.5, 1 - 2 * FIGURE_MARGIN * Math.max(size.width, size.height) / size.height)
}
