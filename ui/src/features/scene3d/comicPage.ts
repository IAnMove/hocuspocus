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
export const COMIC_DURATION = 1.6
export const COMIC_FPS = 30
/** The exporter samples `min(duration, index / fps)` and never `t = duration` (48 frames, last index 47 → 0.979). 0.94 is already settled. */
export const COMIC_MOVE_END = 0.94
export const COMIC_DRIFT = 0.12
export const COMIC_FIT_MARGIN = 0.02
/** Panels sit a few millimetres in front of the paper. A cutout sits 2.5 cm in front of its panel. */
export const COMIC_PANEL_Z = 0.004
export const COMIC_CUTOUT_AHEAD = 0.025

const PAPER_PAGE = { en: 'Paper page (included)', es: 'Página de papel (incluida)' }
const FOUR_PANELS = {
  en: 'Four panel images with the video frame\'s aspect',
  es: 'Cuatro imágenes de viñeta con el aspecto del fotograma',
}
const CUTOUT_NOTE = {
  en: 'Optional keyed cutout 2.5 cm in front of a panel that is not the exit or the entrance',
  es: 'Recorte calado opcional a 2,5 cm de una viñeta que no sea la de salida ni la de entrada',
}

type Grid = { panelW: number; panelH: number; gutter: number; margin: number; pageW: number; pageH: number }
type Placed = { x: number; y: number; z: number; scale: number }
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
    return { x, y: top - panelH, z: COMIC_PANEL_Z, scale: panelH / 2 }
  })
  return { pageW, pageH, pageScale: pageH / 2, panels }
}

/** One wide pose, in metres, shared by the exit's last frame and the enter's first frame. */
export function comicWidePose(format: ComicFormat, frameAspect?: number): Pose {
  const layout = layoutOf(format)
  const aspect = frameAspect ?? (format === 'portrait' ? 9 / 16 : 16 / 9)
  const lookY = layout.pageH / 2
  return {
    eye: [COMIC_DRIFT, lookY, fitDistance(layout.pageW, layout.pageH, aspect)],
    look: [0, lookY, 0],
    fov: COMIC_FOV,
  }
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
  return stock.panels.map((url, index) => ({ url, ...(index === 1 ? { cutout: stock.cutout } : {}) }))
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

function slotsOf(layout: PageLayout, pageUrl: string, panels: ComicPanelInput[]): Scene3DSlot[] {
  const page = imageSlot('page', [0, 0, 0], layout.pageScale, pageUrl)
  const pictures = layout.panels.map((panel, index) => imageSlot(`panel-${index}`, [panel.x, panel.y, panel.z], panel.scale, panels[index]?.url || ''))
  const cutouts = layout.panels.flatMap((panel, index) => {
    const url = panels[index]?.cutout
    return url ? [imageSlot(`cutout-${index}`, [panel.x, panel.y, panel.z + COMIC_CUTOUT_AHEAD], panel.scale, url)] : []
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

function framingOf(panel: Placed, index: number, start: Pose, end: Pose): Scene3DFraming {
  const center: Vec3 = [panel.x, panel.y + panel.scale, panel.z]
  return {
    targetSlot: `panel-${index}`, anchor: 'center', relativeToFacing: false,
    from: divide(start.eye, center, panel.scale), to: divide(end.eye, center, panel.scale),
    lookFrom: divide(start.look, center, panel.scale), lookTo: divide(end.look, center, panel.scale),
    fovFrom: COMIC_FOV, fovTo: COMIC_FOV, moveStart: 0, moveEnd: COMIC_MOVE_END, ease: 'smooth',
  }
}

function documentOf(id: ComicTemplateId, format: ComicFormat, size: { width: number; height: number }, slots: Scene3DSlot[], panel: Placed, index: number, start: Pose, end: Pose): Scene3DDocument {
  const doc = createDefaultScene3DDocument()
  doc.templateId = id
  doc.width = size.width
  doc.height = size.height
  doc.fps = COMIC_FPS
  doc.duration = COMIC_DURATION
  doc.look = { toneMapping: 'none', exposure: 0 }
  doc.light = { kind: 'directional', direction: [-0.2, -1, -0.3], intensity: 1, color: '#ffffff' }
  const camera: Scene3DCamera = {
    family: 'establishment', eye: start.eye, look: start.look, fov: COMIC_FOV,
    framing: framingOf(panel, index, start, end),
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
  const slots = slotsOf(layout, pageUrl, sources)
  const wide = comicWidePose(format, size.width / size.height)
  const leave = fillPose(layout.panels[fromPanel])
  const arrive = fillPose(layout.panels[toPanel])
  return {
    exit: documentOf(comicTemplateId('exit', format), format, size, slots, layout.panels[fromPanel], fromPanel, leave, wide),
    enter: documentOf(comicTemplateId('enter', format), format, size, slots, layout.panels[toPanel], toPanel, wide, arrive),
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
