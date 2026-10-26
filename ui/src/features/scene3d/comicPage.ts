import { projectPoint } from './camera.ts'
import { createDefaultScene3DDocument } from './document.ts'
import { framingFov, framingPose, framingProgress } from './framing.ts'
import { COMIC_HOLE, chooseComicLayout } from './comicLayout.ts'
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
/** Cutout and picture sit behind the page. The picture is further back, so the sticker slides across it. */
export const COMIC_CUTOUT_DEPTH = 0.02
export const COMIC_BASE_DEPTH = 0.15

const PAPER_PAGE = { en: 'Paper page (included)', es: 'Página de papel (incluida)' }
const FOUR_PANELS = {
  en: 'Three to six panel images; the two cut frames keep the video\'s aspect',
  es: 'De tres a seis imágenes; los dos fotogramas del corte conservan el aspecto del vídeo',
}
const CUTOUT_NOTE = {
  en: 'A window per panel: the sticker sits behind the page and the picture further behind, scaled so the fill frame still matches',
  es: 'Una ventana por viñeta: el recorte queda detrás de la página y la foto más atrás, escalados para que el plano lleno coincida',
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

/** Scale that puts a layer `depth` metres behind the page and still covers the same pixels from the fill camera.
 * The fill camera sits `D = scale / tan(fov/2)` metres in front of the page. A plane `d` metres further is smaller
 * on screen by `D / (D + d)`, so the layer is scaled by `(D + d) / D` about that camera's axis (the panel centre). */
export function behindFactor(panelScale: number, depth: number, fovDeg = COMIC_FOV): number {
  const distance = panelScale * fillFrameOffset(fovDeg)
  if (!(depth >= 0) || !(distance > 0)) throw new Error('layer_depth')
  return (distance + depth) / distance
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
      z: 0, scale: panelH / 2, aspect: cell.w / cell.h,
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

/** A layer behind the page, scaled about the fill axis. Depth 0 is the cell on the page. */
export function comicLayerPlacement(panel: Placed, depth: number): { position: Vec3; scale: number } {
  const scale = panel.scale * (depth > 0 ? behindFactor(panel.scale, depth) : 1)
  return { position: [panel.x, panel.y + panel.scale - scale, -depth], scale }
}

function layerPoint(panel: Placed, u: number, v: number, depth: number): Vec3 {
  const placed = comicLayerPlacement(panel, depth)
  const height = placed.scale * 2
  const centerY = placed.position[1] + placed.scale
  return [
    panel.x + (u - 0.5) * height * panel.aspect,
    centerY + (0.5 - v) * height,
    placed.position[2],
  ]
}

function screenDelta(pose: Pose, aspect: number, a: Vec3, b: Vec3): [number, number] {
  const left = projectPoint(a, pose.eye, pose.look, pose.fov, aspect)
  const right = projectPoint(b, pose.eye, pose.look, pose.fov, aspect)
  if (!left || !right) return [0, 0]
  return [right.x - left.x, right.y - left.y]
}

function panelScreenWidth(panel: Placed, pose: Pose, aspect: number): number {
  const delta = screenDelta(pose, aspect, layerPoint(panel, 0, 0.5, 0), layerPoint(panel, 1, 0.5, 0))
  return Math.hypot(delta[0], delta[1])
}

/** Screen gap between one UV on the page and the same UV on a layer behind it. Zero at an exact fill. */
export function comicFillGap(panel: Placed, pose: Pose, frameAspect: number, depth: number, uv: { u: number; v: number } = { u: 0, v: 0 }): number {
  const delta = screenDelta(pose, frameAspect, layerPoint(panel, uv.u, uv.v, 0), layerPoint(panel, uv.u, uv.v, depth))
  return Math.hypot(delta[0], delta[1])
}

/** Screen slide between two depths, from the fill pose to the wide hold, as a fraction of the panel width. */
export function comicPlaneSlide(panel: Placed, fill: Pose, wide: Pose, frameAspect: number, depthA: number, depthB: number, uv: { u: number; v: number } = { u: 0.5, v: 0.5 }): number {
  const from = screenDelta(fill, frameAspect, layerPoint(panel, uv.u, uv.v, depthA), layerPoint(panel, uv.u, uv.v, depthB))
  const to = screenDelta(wide, frameAspect, layerPoint(panel, uv.u, uv.v, depthA), layerPoint(panel, uv.u, uv.v, depthB))
  const width = panelScreenWidth(panel, wide, frameAspect)
  if (!(width > 0)) return 0
  return Math.hypot(to[0] - from[0], to[1] - from[1]) / width
}

/** Slide of the sticker against the picture. Both sit behind the page. */
export function comicCutoutSlide(panel: Placed, fill: Pose, wide: Pose, frameAspect: number, uv: { u: number; v: number } = { u: 0.5, v: 0.5 }): number {
  return comicPlaneSlide(panel, fill, wide, frameAspect, COMIC_CUTOUT_DEPTH, COMIC_BASE_DEPTH, uv)
}

function holePoints(panel: Placed): Vec3[] {
  const grow = COMIC_HOLE * COMIC_METERS_PER_PIXEL
  const halfW = panel.scale * panel.aspect + grow
  const halfH = panel.scale + grow
  const y = panel.y + panel.scale
  return [
    [panel.x - halfW, y - halfH, 0], [panel.x + halfW, y - halfH, 0],
    [panel.x - halfW, y + halfH, 0], [panel.x + halfW, y + halfH, 0],
    [panel.x - halfW, y, 0], [panel.x + halfW, y, 0],
    [panel.x, y - halfH, 0], [panel.x, y + halfH, 0],
  ]
}

function planeHit(eye: Vec3, point: Vec3, depth: number): Vec3 | null {
  const dz = point[2] - eye[2]
  if (!(Math.abs(dz) > 1e-8)) return null
  const t = (-depth - eye[2]) / dz
  if (!(t > 0)) return null
  return [eye[0] + t * (point[0] - eye[0]), eye[1] + t * (point[1] - eye[1]), -depth]
}

function outsideFraction(panel: Placed, hit: Vec3, depth: number): number {
  const placed = comicLayerPlacement(panel, depth)
  const halfW = placed.scale * panel.aspect
  const halfH = placed.scale
  if (!(halfW > 0) || !(halfH > 0)) return 0
  const u = (hit[0] - panel.x) / (2 * halfW) + 0.5
  const v = (placed.position[1] + placed.scale - hit[1]) / (2 * halfH) + 0.5
  return Math.max(0, -u, u - 1, -v, v - 1)
}

/** Largest share of the picture, on any side, that the camera path can reveal past the window. */
export function comicOverscanFraction(panel: Placed, poses: Pose[], depth = COMIC_BASE_DEPTH): number {
  let worst = 0
  for (const pose of poses) {
    for (const point of holePoints(panel)) {
      const hit = planeHit(pose.eye, point, depth)
      if (hit) worst = Math.max(worst, outsideFraction(panel, hit, depth))
    }
  }
  return worst
}

function slotsOf(layout: PageLayout, pageUrl: string, panels: ComicPanelInput[]): Scene3DSlot[] {
  const page = imageSlot('page', [0, 0, 0], layout.pageScale, pageUrl)
  const pictures = layout.panels.map((panel, index) => {
    const placed = comicLayerPlacement(panel, COMIC_BASE_DEPTH)
    return imageSlot(`panel-${index}`, placed.position, placed.scale, panels[index]?.url || '')
  })
  const cutouts = layout.panels.flatMap((panel, index) => {
    const url = panels[index]?.cutout
    if (!url) return []
    const placed = comicLayerPlacement(panel, COMIC_CUTOUT_DEPTH)
    return [imageSlot(`cutout-${index}`, placed.position, placed.scale, url)]
  })
  return [page, ...pictures, ...cutouts]
}

function divide(world: Vec3, center: Vec3, scale: number): Vec3 {
  return [(world[0] - center[0]) / scale, (world[1] - center[1]) / scale, (world[2] - center[2]) / scale]
}

function fillPose(panel: Placed): Pose {
  const center: Vec3 = [panel.x, panel.y + panel.scale, 0]
  const distance = panel.scale * fillFrameOffset(COMIC_FOV)
  return { eye: [center[0], center[1], center[2] + distance], look: center, fov: COMIC_FOV }
}

function framingOf(panel: Placed, index: number, start: Pose, end: Pose, move: { moveStart: number; moveEnd: number }, yawArc: number): Scene3DFraming {
  const base = comicLayerPlacement(panel, COMIC_BASE_DEPTH)
  const center: Vec3 = [base.position[0], base.position[1] + base.scale, base.position[2]]
  return {
    targetSlot: `panel-${index}`, anchor: 'center', relativeToFacing: false,
    from: divide(start.eye, center, base.scale), to: divide(end.eye, center, base.scale),
    lookFrom: divide(start.look, center, base.scale), lookTo: divide(end.look, center, base.scale),
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
  const slots = slotsOf(layout, pageUrl, sources)
  const yawArc = input.yawArc ?? COMIC_YAW_ARC
  const hold = input.hold ?? COMIC_HOLD
  const exitDuration = input.exitDuration ?? COMIC_DURATION
  const enterDuration = input.enterDuration ?? COMIC_DURATION
  const leave = fillPose(layout.panels[fromPanel])
  const arrive = fillPose(layout.panels[toPanel])
  const exit = documentOf(comicTemplateId('exit', format), format, size, slots, layout.panels[fromPanel], fromPanel, leave, wide, exitDuration, comicMoveWindow('exit', exitDuration, hold), yawArc)
  const enter = documentOf(comicTemplateId('enter', format), format, size, slots, layout.panels[toPanel], toPanel, wide, arrive, enterDuration, comicMoveWindow('enter', enterDuration, hold), yawArc)
  stampOverscan(slots, [exit, enter], layout)
  return { exit, enter }
}

/** Every frame of both halves. The yaw arc peaks between the sampled endpoints, so the bound has to walk the path. */
export function comicSamplePoses(doc: Scene3DDocument): Pose[] {
  const frames = comicFrameCount(doc.duration, doc.fps)
  const poses: Pose[] = []
  for (let index = 0; index < frames; index += 1) poses.push(comicCameraAt(doc, comicFrameSeconds(index, doc.duration, doc.fps)))
  return poses
}

function stampOverscan(slots: Scene3DSlot[], docs: Scene3DDocument[], layout: PageLayout) {
  const poses = docs.flatMap(comicSamplePoses)
  let cover = 0
  layout.panels.forEach((panel, index) => {
    const slot = slots.find(item => item.id === `panel-${index}`)
    const fraction = comicOverscanFraction(panel, poses)
    if (slot?.imageLook && fraction > 1e-4) slot.imageLook.overscan = Math.min(1, fraction)
    cover = Math.max(cover, fraction)
  })
  const page = slots.find(item => item.id === 'page')
  // The same fraction of the larger page reaches past every picture that sticks out of a cell.
  if (page?.imageLook && cover > 1e-4) page.imageLook.overscan = Math.min(1, cover)
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
