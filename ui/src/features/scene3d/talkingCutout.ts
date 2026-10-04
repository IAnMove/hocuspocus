import { durableScene3DSourceUrl } from './slotSource'

/** A 2D Character Kit cutout that talks inside a Video 3D scene.
 * The screen canvas paints the pose, the kit's mouth for the cue at the scene time, and its blink.
 * Anchors are pose-local, as in the Character Kit: offsets in % of the longer image edge and
 * height = scale x that edge (the Video 2D mount and the flat rig use the same convention). */
export type CutoutAnchor = { offsetX: number; offsetY: number; scale: number; rotation: number }
export type TalkCue = { start: number; end: number; state: string }
export type TalkingCutout = {
  base: string
  mouths: Record<string, string>
  mouth: CutoutAnchor
  /** Per-drawing placement when the kit has one (Face Rig mouthStates). */
  mouthAnchors?: Record<string, CutoutAnchor>
  rest: string
  cues: TalkCue[]
  blink?: { source: string; anchor: CutoutAnchor }
  blinks?: number[]
}

const MAX_CUES = 10000
const finite = (value: unknown, low: number, high: number): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= low && value <= high

function parseAnchor(raw: unknown): CutoutAnchor | undefined {
  const value = raw as Partial<CutoutAnchor> | undefined
  if (!value || !finite(value.offsetX, -200, 200) || !finite(value.offsetY, -200, 200) || !finite(value.scale, 0.001, 20)) return undefined
  return { offsetX: value.offsetX, offsetY: value.offsetY, scale: value.scale, rotation: finite(value.rotation, -360, 360) ? value.rotation : 0 }
}

export function parseTalkingCutout(raw: unknown): TalkingCutout | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const base = durableScene3DSourceUrl(String(value.base ?? ''))
  const mouth = parseAnchor(value.mouth)
  const mouths = Object.fromEntries(Object.entries((value.mouths ?? {}) as Record<string, unknown>)
    .map(([state, url]) => [state, durableScene3DSourceUrl(String(url ?? ''))] as const).filter(([, url]) => Boolean(url)))
  if (!base || !mouth || !Object.keys(mouths).length) return undefined
  const rest = typeof value.rest === 'string' && mouths[value.rest] ? value.rest : Object.keys(mouths)[0]
  const cues = (Array.isArray(value.cues) ? value.cues.slice(0, MAX_CUES) : [])
    .filter((cue): cue is TalkCue => Boolean(cue) && finite(cue.start, 0, 3600) && finite(cue.end, 0, 3600) && cue.end > cue.start
      && typeof cue.state === 'string' && Boolean(mouths[cue.state]))
    .map(cue => ({ start: cue.start, end: cue.end, state: cue.state })).sort((a, b) => a.start - b.start)
  const blinkValue = value.blink as { source?: unknown; anchor?: unknown } | undefined
  const blinkSource = blinkValue ? durableScene3DSourceUrl(String(blinkValue.source ?? '')) : ''
  const blinkAnchor = blinkValue ? parseAnchor(blinkValue.anchor) : undefined
  const mouthAnchors = Object.fromEntries(Object.entries((value.mouthAnchors ?? {}) as Record<string, unknown>)
    .filter(([state]) => Boolean(mouths[state])).map(([state, anchor]) => [state, parseAnchor(anchor)] as const)
    .filter((entry): entry is readonly [string, CutoutAnchor] => Boolean(entry[1])))
  const blinks = Array.isArray(value.blinks) ? value.blinks.filter(time => finite(time, 0, 3600)).slice(0, 2000) as number[] : []
  return { base, mouths, mouth, ...(Object.keys(mouthAnchors).length ? { mouthAnchors } : {}), rest, cues, ...(blinkSource && blinkAnchor ? { blink: { source: blinkSource, anchor: blinkAnchor }, blinks } : {}) }
}

/** The mouth state at a scene time: the cue that holds it, else the rest mouth. */
export function talkStateAt(talk: Pick<TalkingCutout, 'cues' | 'rest'>, seconds: number): string {
  let low = 0, high = talk.cues.length - 1
  while (low <= high) {
    const middle = (low + high) >> 1, cue = talk.cues[middle]
    if (seconds < cue.start) high = middle - 1
    else if (seconds >= cue.end) low = middle + 1
    else return cue.state
  }
  return talk.rest
}

export const BLINK_SECONDS = 0.11
export function blinkingAt(blinks: readonly number[] | undefined, seconds: number) {
  return Boolean(blinks?.some(time => seconds >= time && seconds < time + BLINK_SECONDS))
}

/** Where an overlay sits on a pose canvas of width x height (height = scale x longer edge). */
export function anchorRect(anchor: CutoutAnchor, width: number, height: number, spriteAspect: number) {
  const edge = Math.max(width, height)
  const h = anchor.scale * edge, w = h * spriteAspect
  return { x: width / 2 + anchor.offsetX * edge / 100 - w / 2, y: height / 2 + anchor.offsetY * edge / 100 - h / 2, width: w, height: h }
}

async function decode(url: string, signal: AbortSignal): Promise<HTMLImageElement> {
  if (signal.aborted) throw new Error('screen-media-disposed')
  const image = new Image()
  image.crossOrigin = 'anonymous'
  image.src = url
  await image.decode()
  if (signal.aborted) throw new Error('screen-media-disposed')
  return image
}

type Frame = { x: number; y: number; width: number; height: number }

function drawOverlay(context: CanvasRenderingContext2D, image: HTMLImageElement, anchor: CutoutAnchor, frame: Frame) {
  const rect = anchorRect(anchor, frame.width, frame.height, image.naturalWidth / image.naturalHeight)
  context.save()
  context.translate(frame.x + rect.x + rect.width / 2, frame.y + rect.y + rect.height / 2)
  context.rotate(anchor.rotation * Math.PI / 180)
  context.drawImage(image, -rect.width / 2, -rect.height / 2, rect.width, rect.height)
  context.restore()
}

/** Load the pose, mouths and blink; paint(context, screen, seconds) composes one frame.
 * Cues, anchors and blinks are read from the screen being painted, so editing them repaints without reloading. */
export async function loadTalkingCutout(talk: TalkingCutout, signal: AbortSignal) {
  const base = await decode(talk.base, signal)
  const mouths = Object.fromEntries(await Promise.all(Object.entries(talk.mouths).map(async ([state, url]) => [state, await decode(url, signal)] as const)))
  const blink = talk.blink ? await decode(talk.blink.source, signal) : undefined
  return {
    paint(context: CanvasRenderingContext2D, screen: { talk?: TalkingCutout } | undefined, seconds: number) {
      const live = screen?.talk ?? talk
      const { width, height } = context.canvas
      const fit = Math.min(width / base.naturalWidth, height / base.naturalHeight)
      const frame = { width: base.naturalWidth * fit, height: base.naturalHeight * fit, x: 0, y: 0 }
      frame.x = (width - frame.width) / 2; frame.y = (height - frame.height) / 2
      context.clearRect(0, 0, width, height)
      context.drawImage(base, frame.x, frame.y, frame.width, frame.height)
      const cued = talkStateAt(live, seconds), state = mouths[cued] ? cued : live.rest
      if (mouths[state]) drawOverlay(context, mouths[state], live.mouthAnchors?.[state] ?? live.mouth, frame)
      if (blink && live.blink && blinkingAt(live.blinks, seconds)) drawOverlay(context, blink, live.blink.anchor, frame)
    },
    dispose() { base.src = ''; for (const image of Object.values(mouths)) image.src = ''; if (blink) blink.src = '' },
  }
}
