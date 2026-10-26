import { createDefaultScene3DDocument } from './document.ts'
import { framingFov, framingPose, framingProgress } from './framing.ts'
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
  exitDuration?: number
  enterDuration?: number
  hold?: number
  yawDeg?: number
  yawArc?: number
}
export type ComicCardCopy = { title: string; description: string; requirements: string[] }

/** 2×2 page. A uniform gutter cannot keep every panel at the frame aspect and the page at 16:9, so the page is a few percent off and the wide pose fits it inside the frame. */
const GRID = {
  landscape: { panelW: 640, panelH: 360, gutter: 16, margin: 28 },
  portrait: { panelW: 360, panelH: 640, gutter: 16, margin: 28 },
} as const

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
export const COMIC_FIT_MARGIN = 0.02
/** Panels sit a few millimetres in front of the paper. A cutout sits 4 cm in front of its panel. */
export const COMIC_PANEL_Z = 0.004
export const COMIC_CUTOUT_AHEAD = 0.04
/** A filler cutout is drawn this much larger than the compensated size, so it crosses the ink border in the wide view. */
export const COMIC_POP = 1.12
/** Fraction of the panel's half-width the popped cutout slides away from the page centre. */
export const COMIC_POP_SHIFT = 0.16

const PAPER_PAGE = { en: 'Paper page (included)', es: 'Página de papel (incluida)' }
const FOUR_PANELS = {
  en: 'Four panel images with the video frame\'s aspect',
  es: 'Cuatro imágenes de viñeta con el aspecto del fotograma',
}
const CUTOUT_NOTE = {
  en: 'A subject cutout 4 cm in front of each panel, scaled so the fill frame still matches',
  es: 'Un recorte del sujeto a 4 cm de cada viñeta, escalado para que el plano lleno siga coincidiendo',
}

type Grid = { panelW: number; panelH: number; gutter: number; margin: number; pageW: number; pageH: number }
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

/** Pixel size of the authored page. Panel pixels are exactly 16:9 or 9:16, so a panel can fill the frame. */
export function comicPagePixels(format: ComicFormat): Grid {
  const grid = GRID[format]
  return {
    ...grid,
    pageW: grid.margin * 2 + grid.panelW * 2 + grid.gutter,
    pageH: grid.margin * 2 + grid.panelH * 2 + grid.gutter,
  }
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

function layoutOf(format: ComicFormat): PageLayout {
  const px = comicPagePixels(format)
  const pageW = meters(px.pageW)
  const pageH = meters(px.pageH)
  const panelW = meters(px.panelW)
  const panelH = meters(px.panelH)
  const gutter = meters(px.gutter)
  const margin = meters(px.margin)
  const left = -pageW / 2
  const panels = [0, 1, 2, 3].map(index => {
    const col = index % 2
    const row = Math.floor(index / 2)
    const x = left + margin + panelW / 2 + col * (panelW + gutter)
    const top = pageH - margin - row * (panelH + gutter)
    return { x, y: top - panelH, z: COMIC_PANEL_Z, scale: panelH / 2, aspect: panelW / panelH }
  })
  return { pageW, pageH, pageScale: pageH / 2, panels }
}

/** One wide pose, in metres, shared by the exit's last frame and the enter's first frame.
 * The eye orbits the page centre by `yawDeg`, so the held view is not a straight zoom. */
export function comicWidePose(format: ComicFormat, frameAspect?: number, yawDeg = COMIC_YAW_DEG): Pose {
  const layout = layoutOf(format)
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

function filler(format: ComicFormat) {
  const tag = format === 'portrait' ? 'portrait' : 'landscape'
  return {
    page: `/scene3d/comic/page-${tag}.png`,
    panels: [0, 1, 2, 3].map(index => `/scene3d/comic/panel-${tag}-${index}.png`),
    cutout: `/scene3d/comic/cutout-${tag}.png`,
  }
}

function panelSources(input: ComicPairInput, format: ComicFormat): ComicPanelInput[] {
  if (input.panels && input.panels.length === COMIC_PANEL_COUNT) return input.panels
  const stock = filler(format)
  return stock.panels.map(url => ({ url, cutout: stock.cutout }))
}

function requireIndex(value: number): number {
  if (!Number.isInteger(value) || value < 0 || value >= COMIC_PANEL_COUNT) throw new Error('panel_index')
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

/** Centre stays on the fill axis. A popped filler is larger and slid outward so it crosses the border once the camera leaves that axis. */
export function comicCutoutPlacement(panel: Placed, popped = false): { position: Vec3; scale: number } {
  const scale = panel.scale * cutoutFactor(panel.scale) * (popped ? COMIC_POP : 1)
  const shift = popped ? Math.sign(panel.x || 1) * panel.scale * panel.aspect * COMIC_POP_SHIFT : 0
  return { position: [panel.x + shift, panel.y + panel.scale - scale, panel.z + COMIC_CUTOUT_AHEAD], scale }
}

function slotsOf(layout: PageLayout, pageUrl: string, panels: ComicPanelInput[], fromPanel: number, toPanel: number): Scene3DSlot[] {
  const page = imageSlot('page', [0, 0, 0], layout.pageScale, pageUrl)
  const pictures = layout.panels.map((panel, index) => imageSlot(`panel-${index}`, [panel.x, panel.y, panel.z], panel.scale, panels[index]?.url || ''))
  const popped = popPanel(panels, fromPanel, toPanel)
  const cutouts = layout.panels.flatMap((panel, index) => {
    const url = panels[index]?.cutout
    if (!url) return []
    const placed = comicCutoutPlacement(panel, index === popped)
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
  const fromPanel = requireIndex(input.fromPanel ?? 0)
  const toPanel = requireIndex(input.toPanel ?? 3)
  if (fromPanel === toPanel) throw new Error('same_panel')
  const size = input.width && input.height ? { width: input.width, height: input.height } : comicCatalogueSize(format)
  const layout = layoutOf(format)
  const sources = panelSources(input, format)
  const pageUrl = input.pageUrl || filler(format).page
  const slots = slotsOf(layout, pageUrl, sources, fromPanel, toPanel)
  const yawDeg = input.yawDeg ?? COMIC_YAW_DEG
  const yawArc = input.yawArc ?? COMIC_YAW_ARC
  const hold = input.hold ?? COMIC_HOLD
  const exitDuration = input.exitDuration ?? COMIC_DURATION
  const enterDuration = input.enterDuration ?? COMIC_DURATION
  const wide = comicWidePose(format, size.width / size.height, yawDeg)
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
