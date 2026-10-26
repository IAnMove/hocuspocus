import { projectPoint } from './camera.ts'
import { createDefaultScene3DDocument } from './document.ts'
import { framingFov, framingPose, framingProgress } from './framing.ts'
import { chooseComicLayout } from './comicLayout.ts'
import { COMIC_TEMPLATE_IDS, type ComicTemplateId } from './comicTemplateIds.ts'
import type { Scene3DCamera, Scene3DDocument, Scene3DFraming, Scene3DSlot, Vec3 } from './types.ts'

export { COMIC_TEMPLATE_IDS, type ComicTemplateId }

export type ComicFormat = 'landscape' | 'portrait'
export type ComicRole = 'exit' | 'enter'
export type ComicPanelInput = { url: string; cutout?: string }
export type ComicPairInput = {
  format: ComicFormat
  width?: number
  height?: number
  pageUrl?: string
  panels?: ComicPanelInput[]
  fromPanel?: number
  toPanel?: number
  seed?: number
  exitDuration?: number
  enterDuration?: number
  hold?: number
  yawDeg?: number
  yawArc?: number
  /** Opt-in: one filler cutout breaks its border at the wide pose. */
  pop?: boolean
}
export type ComicCardCopy = { title: string; description: string; requirements: string[] }

/** Catalogue page: four panels, seed 0, the first and last panels are the cut. */
export const COMIC_PANEL_COUNT = 4
/** Metres per filler pixel. A landscape panel is 0.8 × 0.45 m. */
export const COMIC_METERS_PER_PIXEL = 0.00125
export const COMIC_FOV = 36
export const COMIC_DURATION = 1.8
export const COMIC_FPS = 30
/** Seconds the wide pose is held on each half, so the page can be read. */
export const COMIC_HOLD = 0.4
/** Wide pose yaw, and the extra mid-move yaw that is zero at both endpoints. */
export const COMIC_YAW_DEG = 8
export const COMIC_YAW_ARC = 8
/** Pulls the wide camera back so an 8° yaw keeps the page inside the frame.
 * At 0.09 the paper still covers at least 85% of the frame's longer side. */
export const COMIC_FIT_MARGIN = 0.09
/** Panels sit a few millimetres in front of the paper. A cutout sits 10.8 cm in front of its panel. */
export const COMIC_PANEL_Z = 0.004
export const COMIC_CUTOUT_AHEAD = 0.108
/** Apparent width of one filler cutout at the wide pose, relative to its panel. The mesh is larger than this: the cutout is closer to the camera. */
export const COMIC_POP = 1.12
/** Fraction of the panel's half-width the popped cutout slides away from the page centre. */
export const COMIC_POP_SHIFT = 0.16

const PAPER_PAGE = { en: 'Paper page (included)', es: 'Página de papel (incluida)' }
const FOUR_PANELS = {
  en: 'Three to six panel images; the two cut frames keep the video\'s aspect',
  es: 'De tres a seis imágenes; los dos fotogramas del corte conservan el aspecto del vídeo',
}
const CUTOUT_NOTE = {
  en: 'A subject cutout 10.8 cm in front of each panel, scaled so the fill frame still matches',
  es: 'Un recorte del sujeto a 10,8 cm de cada viñeta, escalado para que el plano lleno siga coincidiendo',
}

type Placed = { x: number; y: number; z: number; scale: number; aspect: number }
type PageLayout = { pageW: number; pageH: number; pageScale: number; panels: Placed[] }
type Pose = { eye: Vec3; look: Vec3; fov: number }

export function isComicTemplateId(id: string): id is ComicTemplateId {
  return (COMIC_TEMPLATE_IDS as readonly string[]).includes(id)
}

export function comicFormatOf(id: string): ComicFormat {
  return id.endsWith('-portrait') ? 'portrait' : 'landscape'
}

export function comicRoleOf(id: string): ComicRole {
  return id.includes('enter') ? 'enter' : 'exit'
}

/** Pixel size of the catalogue page (four panels, seed 0, cut on the first and last). */
export function comicPagePixels(format: ComicFormat) {
  const layout = chooseComicLayout(format, COMIC_PANEL_COUNT, 0, 0, COMIC_PANEL_COUNT - 1)
  return { pageW: layout.pageW, pageH: layout.pageH, cells: layout.cells }
}

export function comicCatalogueSize(format: ComicFormat): { width: number; height: number } {
  return format === 'portrait' ? { width: 1080, height: 1920 } : { width: 1920, height: 1080 }
}

/** Framing offset that fills a panel. Three.js fov is vertical. A plane of height 2, drawn at `slot.scale`,
 * fills the frame when the camera is `scale / tan(fov/2)` metres in front of its centre. Framing offsets are
 * multiplied by `slot.scale`, so the offset is `1 / tan(fov/2)` and the scale cancels.
 * The viewport aspect must equal the panel aspect or the horizontal fit is a different size. */
export function fillFrameOffset(fovDeg: number): number {
  return 1 / Math.tan((fovDeg * Math.PI) / 360)
}

/** Scale that puts a cutout `ahead` metres in front of a panel and still covers the same pixels from the fill camera.
 * The fill camera sits `D = scale / tan(fov/2)` metres in front of the panel. A plane `d` metres closer is larger
 * on screen by `D / (D - d)`, so the cutout is scaled by `(D - d) / D` about that camera's axis (the panel centre). */
export function cutoutFactor(panelScale: number, ahead = COMIC_CUTOUT_AHEAD, fovDeg = COMIC_FOV): number {
  const distance = panelScale * fillFrameOffset(fovDeg)
  if (!(distance > ahead)) throw new Error('cutout_ahead')
  return (distance - ahead) / distance
}

/** Distance at which the whole page fits in the frame, with a margin, at a constant fov. */
export function fitDistance(pageW: number, pageH: number, frameAspect: number, fovDeg = COMIC_FOV, margin = COMIC_FIT_MARGIN): number {
  const tan = Math.tan((fovDeg * Math.PI) / 360)
  const pad = 1 + margin
  return Math.max((pageH * pad) / (2 * tan), (pageW * pad) / (2 * tan * frameAspect))
}

export function comicFrameCount(duration = COMIC_DURATION, fps = COMIC_FPS): number {
  return Math.max(1, Math.round(duration * fps))
}

/** Same clock as the exporter: frame `index` is `min(duration, index / fps)`. */
export function comicFrameSeconds(index: number, duration = COMIC_DURATION, fps = COMIC_FPS): number {
  return Math.min(duration, index / fps)
}

function meters(pixels: number): number {
  return pixels * COMIC_METERS_PER_PIXEL
}

function layoutOf(format: ComicFormat, count = COMIC_PANEL_COUNT, seed = 0, from = 0, to = count - 1): PageLayout {
  const px = chooseComicLayout(format, count, seed, from, to)
  const pageW = meters(px.pageW)
  const pageH = meters(px.pageH)
  const panels = px.cells.map(cell => {
    const panelW = meters(cell.w)
    const panelH = meters(cell.h)
    return {
      x: -pageW / 2 + meters(cell.x) + panelW / 2,
      y: meters(px.pageH - cell.y - cell.h),
      z: COMIC_PANEL_Z, scale: panelH / 2, aspect: cell.w / cell.h,
    }
  })
  return { pageW, pageH, pageScale: pageH / 2, panels }
}

/** One wide pose, in metres, shared by the exit's last frame and the enter's first frame.
 * The eye orbits the page centre by `yawDeg`, so the held view is not a straight zoom.
 * `page` is that pair's page in metres; omitted, it is the catalogue page. */
export function comicWidePose(format: ComicFormat, frameAspect?: number, yawDeg = COMIC_YAW_DEG, page?: { pageW: number; pageH: number }): Pose {
  const layout = page ?? layoutOf(format)
  const aspect = frameAspect ?? (format === 'portrait' ? 9 / 16 : 16 / 9)
  const lookY = layout.pageH / 2
  const distance = fitDistance(layout.pageW, layout.pageH, aspect)
  const yaw = yawDeg * Math.PI / 180
  return {
    eye: [Math.sin(yaw) * distance, lookY, Math.cos(yaw) * distance],
    look: [0, lookY, 0],
    fov: COMIC_FOV,
  }
}

/** Hold the wide pose for `hold` seconds. Exit settles before its last frame; enter is already there at frame 0 and reaches the fill on its last frame. */
export function comicMoveWindow(role: ComicRole, duration = COMIC_DURATION, hold = COMIC_HOLD): { moveStart: number; moveEnd: number } {
  const last = comicFrameSeconds(comicFrameCount(duration) - 1, duration) / duration
  if (role === 'exit') return { moveStart: 0, moveEnd: Math.min(last, Math.max(0.05, (duration - hold) / duration)) }
  return { moveStart: Math.min(Math.max(0, hold / duration), last / 2), moveEnd: last }
}

/** Centre of a bottom-anchored cutout: the mesh is lifted by its scale (`poseImageCutout`). */
export function comicSlotCenter(slot: Scene3DSlot): Vec3 {
  return [slot.position[0], slot.position[1] + slot.scale, slot.position[2]]
}

function pagePicture(format: ComicFormat): string {
  return `/scene3d/comic/page-${format === 'portrait' ? 'portrait' : 'landscape'}.png`
}

function filler(format: ComicFormat): ComicPanelInput[] {
  const tag = format === 'portrait' ? 'portrait' : 'landscape'
  return [0, 1, 2, 3].map(index => ({
    url: `/scene3d/comic/panel-${tag}-${index}.png`,
    cutout: `/scene3d/comic/cutout-${tag}-${index}.png`,
  }))
}

function panelSources(input: ComicPairInput, format: ComicFormat, count: number): ComicPanelInput[] {
  if (input.panels && input.panels.length === count) return input.panels
  return filler(format)
}

function requireIndex(value: number, count: number): number {
  if (!Number.isInteger(value) || value < 0 || value >= count) throw new Error('panel_index')
  return value
}

function imageSlot(id: string, position: Vec3, scale: number, url: string): Scene3DSlot {
  return {
    id, slot: 'prop', media: 'image', surface: 'cutout', imageLook: { unlit: true, sharp: true },
    sourceUrl: url, clip: null, position, rotationY: 0, scale,
  }
}

function popPanel(panels: ComicPanelInput[], fromPanel: number, toPanel: number): number | null {
  const found = panels.findIndex((panel, index) => Boolean(panel.cutout) && index !== fromPanel && index !== toPanel)
  return found < 0 ? null : found
}

function layerPoint(panel: Placed, u: number, v: number, ahead: number, factor: number): Vec3 {
  const height = panel.scale * 2 * factor
  return [
    panel.x + (u - 0.5) * height * panel.aspect,
    panel.y + panel.scale + (0.5 - v) * height,
    panel.z + ahead,
  ]
}

function screenDelta(pose: Pose, aspect: number, a: Vec3, b: Vec3): [number, number] {
  const left = projectPoint(a, pose.eye, pose.look, pose.fov, aspect)
  const right = projectPoint(b, pose.eye, pose.look, pose.fov, aspect)
  if (!left || !right) return [0, 0]
  return [right.x - left.x, right.y - left.y]
}

function panelScreenWidth(panel: Placed, pose: Pose, aspect: number): number {
  const delta = screenDelta(pose, aspect, layerPoint(panel, 0, 0.5, 0, 1), layerPoint(panel, 1, 0.5, 0, 1))
  return Math.hypot(delta[0], delta[1])
}

/** Screen slide of one panel UV from the fill pose to the wide hold, as a fraction of that panel's width at the wide hold. */
export function comicCutoutSlide(panel: Placed, fill: Pose, wide: Pose, frameAspect: number, ahead = COMIC_CUTOUT_AHEAD, uv: { u: number; v: number } = { u: 0.5, v: 0.5 }): number {
  const factor = cutoutFactor(panel.scale, ahead)
  const base = layerPoint(panel, uv.u, uv.v, 0, 1)
  const cut = layerPoint(panel, uv.u, uv.v, ahead, factor)
  const from = screenDelta(fill, frameAspect, base, cut)
  const to = screenDelta(wide, frameAspect, base, cut)
  const width = panelScreenWidth(panel, wide, frameAspect)
  if (!(width > 0)) return 0
  return Math.hypot(to[0] - from[0], to[1] - from[1]) / width
}

function popShift(panel: Placed): number {
  return Math.sign(panel.x || 1) * panel.scale * panel.aspect * COMIC_POP_SHIFT
}

function cutoutScreenWidth(panel: Placed, scale: number, pose: Pose, aspect: number, ahead: number): number {
  const centerY = panel.y + panel.scale
  const half = scale * panel.aspect
  const z = panel.z + ahead
  const delta = screenDelta(pose, aspect, [panel.x + popShift(panel) - half, centerY, z], [panel.x + popShift(panel) + half, centerY, z])
  return Math.hypot(delta[0], delta[1])
}

/** Mesh scale whose projected width at the wide pose is `COMIC_POP` times the panel. */
export function comicPopScale(panel: Placed, wide: Pose, frameAspect: number, ahead = COMIC_CUTOUT_AHEAD): number {
  const base = panelScreenWidth(panel, wide, frameAspect)
  let scale = panel.scale * cutoutFactor(panel.scale, ahead) * COMIC_POP
  for (let step = 0; step < 6; step += 1) {
    const width = cutoutScreenWidth(panel, scale, wide, frameAspect, ahead)
    if (!(width > 0) || !(base > 0)) return scale
    const ratio = width / base
    if (Math.abs(ratio - COMIC_POP) < 1e-6) return scale
    scale *= COMIC_POP / ratio
  }
  return scale
}

/** Centre stays on the fill axis. A popped filler is sized for the wide pose and slid outward. Without that pose the old `COMIC_POP` mesh factor is kept. */
export function comicCutoutPlacement(panel: Placed, popped = false, view?: { pose: Pose; aspect: number }): { position: Vec3; scale: number } {
  const shift = popped ? popShift(panel) : 0
  const scale = popped && view ? comicPopScale(panel, view.pose, view.aspect) : panel.scale * cutoutFactor(panel.scale) * (popped ? COMIC_POP : 1)
  return { position: [panel.x + shift, panel.y + panel.scale - scale, panel.z + COMIC_CUTOUT_AHEAD], scale }
}

function slotsOf(layout: PageLayout, pageUrl: string, panels: ComicPanelInput[], fromPanel: number, toPanel: number, wide: Pose, frameAspect: number, pop: boolean): Scene3DSlot[] {
  const page = imageSlot('page', [0, 0, 0], layout.pageScale, pageUrl)
  const pictures = layout.panels.map((panel, index) => imageSlot(`panel-${index}`, [panel.x, panel.y, panel.z], panel.scale, panels[index]?.url || ''))
  const popped = pop ? popPanel(panels, fromPanel, toPanel) : null
  const view = { pose: wide, aspect: frameAspect }
  const cutouts = layout.panels.flatMap((panel, index) => {
    const url = panels[index]?.cutout
    if (!url) return []
    const placed = comicCutoutPlacement(panel, index === popped, view)
    return [imageSlot(`cutout-${index}`, placed.position, placed.scale, url)]
  })
  return [page, ...pictures, ...cutouts]
}

function divide(world: Vec3, center: Vec3, scale: number): Vec3 {
  return [(world[0] - center[0]) / scale, (world[1] - center[1]) / scale, (world[2] - center[2]) / scale]
}

function fillPose(panel: Placed): Pose {
  const center: Vec3 = [panel.x, panel.y + panel.scale, panel.z]
  const distance = panel.scale * fillFrameOffset(COMIC_FOV)
  return { eye: [center[0], center[1], center[2] + distance], look: center, fov: COMIC_FOV }
}

function framingOf(panel: Placed, index: number, start: Pose, end: Pose, move: { moveStart: number; moveEnd: number }, yawArc: number): Scene3DFraming {
  const center: Vec3 = [panel.x, panel.y + panel.scale, panel.z]
  return {
    targetSlot: `panel-${index}`, anchor: 'center', relativeToFacing: false,
    from: divide(start.eye, center, panel.scale), to: divide(end.eye, center, panel.scale),
    lookFrom: divide(start.look, center, panel.scale), lookTo: divide(end.look, center, panel.scale),
    fovFrom: COMIC_FOV, fovTo: COMIC_FOV, moveStart: move.moveStart, moveEnd: move.moveEnd, ease: 'smooth',
    yawArc,
  }
}

function documentOf(id: ComicTemplateId, format: ComicFormat, size: { width: number; height: number }, slots: Scene3DSlot[], panel: Placed, index: number, start: Pose, end: Pose, duration: number, move: { moveStart: number; moveEnd: number }, yawArc: number): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  doc.templateId = id
  doc.width = size.width
  doc.height = size.height
  doc.fps = COMIC_FPS
  doc.duration = duration
  doc.look = { toneMapping: 'none', exposure: 0 }
  doc.light = { kind: 'directional', direction: [-0.2, -1, -0.3], intensity: 1, color: '#ffffff' }
  const camera: Scene3DCamera = {
    family: 'establishment', eye: start.eye, look: start.look, fov: COMIC_FOV,
    framing: framingOf(panel, index, start, end, move, yawArc),
  }
  if (format === 'portrait') camera.frameFormat = 'portrait'
  doc.camera = camera
  doc.slots = slots
  return doc
}

export function comicTemplateId(role: ComicRole, format: ComicFormat): ComicTemplateId {
  if (format === 'portrait') return role === 'exit' ? 'comic-panel-exit-portrait' : 'comic-panel-enter-portrait'
  return role === 'exit' ? 'comic-panel-exit' : 'comic-panel-enter'
}

/** Exit starts filling `fromPanel` and ends on the wide page. Enter starts on that same wide pose and ends filling `toPanel`. */
export function buildComicPair(input: ComicPairInput): { exit: Scene3DDocument; enter: Scene3DDocument } {
  const format: ComicFormat = input.format === 'portrait' ? 'portrait' : 'landscape'
  const count = input.panels ? input.panels.length : COMIC_PANEL_COUNT
  const fromPanel = requireIndex(input.fromPanel ?? 0, count)
  const toPanel = requireIndex(input.toPanel ?? count - 1, count)
  if (fromPanel === toPanel) throw new Error('same_panel')
  const seed = input.seed ?? 0
  const size = input.width && input.height ? { width: input.width, height: input.height } : comicCatalogueSize(format)
  const layout = layoutOf(format, count, seed, fromPanel, toPanel)
  const sources = panelSources(input, format, count)
  const pageUrl = input.pageUrl || pagePicture(format)
  const yawDeg = input.yawDeg ?? COMIC_YAW_DEG
  const wide = comicWidePose(format, size.width / size.height, yawDeg, layout)
  const slots = slotsOf(layout, pageUrl, sources, fromPanel, toPanel, wide, size.width / size.height, input.pop === true)
  const yawArc = input.yawArc ?? COMIC_YAW_ARC
  const hold = input.hold ?? COMIC_HOLD
  const exitDuration = input.exitDuration ?? COMIC_DURATION
  const enterDuration = input.enterDuration ?? COMIC_DURATION
  const leave = fillPose(layout.panels[fromPanel])
  const arrive = fillPose(layout.panels[toPanel])
  return {
    exit: documentOf(comicTemplateId('exit', format), format, size, slots, layout.panels[fromPanel], fromPanel, leave, wide, exitDuration, comicMoveWindow('exit', exitDuration, hold), yawArc),
    enter: documentOf(comicTemplateId('enter', format), format, size, slots, layout.panels[toPanel], toPanel, wide, arrive, enterDuration, comicMoveWindow('enter', enterDuration, hold), yawArc),
  }
}

export function applyComicTemplate(id: string): Scene3DDocument | null {
  if (!isComicTemplateId(id)) return null
  const pair = buildComicPair({ format: comicFormatOf(id) })
  return comicRoleOf(id) === 'enter' ? pair.enter : pair.exit
}

export function comicTemplateDocument(id: string): Scene3DDocument | null {
  return applyComicTemplate(id)
}

/** World pose the renderer uses, via `framingPose` (offsets × slot scale, added to the cutout centre). */
export function comicCameraAt(doc: Scene3DDocument, seconds: number): Pose {
  const framing = doc.camera.framing
  if (!framing) return { eye: doc.camera.eye, look: doc.camera.look, fov: doc.camera.fov }
  const slot = doc.slots.find(item => item.id === framing.targetSlot)
  if (!slot) throw new Error('framing_target_missing')
  const pose = framingPose(framing, comicSlotCenter(slot), slot, seconds, doc.duration)
  return { eye: pose.eye, look: pose.look, fov: framingFov(framing, doc.camera.fov, seconds, doc.duration) }
}

export function comicFramingProgress(doc: Scene3DDocument, seconds: number): number {
  return framingProgress(doc.camera.framing, seconds, doc.duration)
}

const COPY: Record<ComicTemplateId, { en: ComicCardCopy; es: ComicCardCopy }> = {
  'comic-panel-exit': {
    en: { title: 'Comic panel exit', description: 'The last frame fills one panel, then the camera pulls out until the whole comic page is in frame.', requirements: [FOUR_PANELS.en, PAPER_PAGE.en, CUTOUT_NOTE.en] },
    es: { title: 'Salida de viñeta', description: 'El último fotograma llena una viñeta y la cámara se retira hasta encuadrar la página entera.', requirements: [FOUR_PANELS.es, PAPER_PAGE.es, CUTOUT_NOTE.es] },
  },
  'comic-panel-enter': {
    en: { title: 'Comic panel enter', description: 'The camera starts on the whole comic page and flies into the next panel until that frame fills the picture.', requirements: [FOUR_PANELS.en, PAPER_PAGE.en, CUTOUT_NOTE.en] },
    es: { title: 'Entrada de viñeta', description: 'La cámara empieza en la página entera y entra en la viñeta siguiente hasta que ese fotograma llena la imagen.', requirements: [FOUR_PANELS.es, PAPER_PAGE.es, CUTOUT_NOTE.es] },
  },
  'comic-panel-exit-portrait': {
    en: { title: 'Comic panel exit (portrait)', description: 'A vertical chapter change: the last frame fills one panel, then the camera pulls out to the whole page.', requirements: [FOUR_PANELS.en, PAPER_PAGE.en, CUTOUT_NOTE.en] },
    es: { title: 'Salida de viñeta (vertical)', description: 'Cambio de capítulo vertical: el último fotograma llena una viñeta y la cámara se retira hasta la página entera.', requirements: [FOUR_PANELS.es, PAPER_PAGE.es, CUTOUT_NOTE.es] },
  },
  'comic-panel-enter-portrait': {
    en: { title: 'Comic panel enter (portrait)', description: 'A vertical chapter change: the camera starts on the whole page and flies into the next panel until it fills the frame.', requirements: [FOUR_PANELS.en, PAPER_PAGE.en, CUTOUT_NOTE.en] },
    es: { title: 'Entrada de viñeta (vertical)', description: 'Cambio de capítulo vertical: la cámara empieza en la página entera y entra en la viñeta siguiente hasta llenar el cuadro.', requirements: [FOUR_PANELS.es, PAPER_PAGE.es, CUTOUT_NOTE.es] },
  },
}

export function comicCard(id: string, locale: 'en' | 'es' = 'en'): ComicCardCopy | undefined {
  if (!isComicTemplateId(id)) return undefined
  return COPY[id][locale]
}

export const COMIC_TEMPLATES = COMIC_TEMPLATE_IDS.map(id => ({
  id,
  camera: 'establishment' as const,
  duration: COMIC_DURATION,
  slots: ['prop' as const],
  tags: ['transition' as const],
  frameFormat: (id.endsWith('-portrait') ? 'portrait' : 'landscape') as 'portrait' | 'landscape',
}))

export const COMIC_CATEGORIES = Object.fromEntries(
  COMIC_TEMPLATE_IDS.map(id => [id, 'cinema']),
) as Record<ComicTemplateId, 'cinema'>
