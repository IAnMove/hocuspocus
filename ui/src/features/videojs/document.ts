import {
  VIDEOJS_SCHEMA,
  VIDEOJS_TRANSITIONS,
  type VideoJsDocument,
  type VideoJsScene,
  type VideoJsSceneKind,
  type VideoJsTheme,
  type VideoJsTransition,
} from './types.ts'

export const VIDEOJS_LIMITS = {
  scenes: 40,
  codeChars: 60_000,
  minSceneSeconds: 0.5,
  maxSceneSeconds: 60,
  maxVideoSeconds: 600,
  maxTransitionSeconds: 2,
} as const

export const VIDEOJS_FORMATS = {
  landscape: { width: 1920, height: 1080 },
  portrait: { width: 1080, height: 1920 },
  square: { width: 1080, height: 1080 },
} as const

export type VideoJsFormat = keyof typeof VIDEOJS_FORMATS

export const DEFAULT_VIDEOJS_THEME: VideoJsTheme = {
  background: '#0b1020',
  surface: '#161c33',
  primary: '#7c5cff',
  secondary: '#22d3ee',
  accent: '#f472b6',
  text: '#f8fafc',
  muted: '#94a3b8',
  font: 'Inter, "Segoe UI", Roboto, system-ui, sans-serif',
  display: '"Montserrat", "Segoe UI", Roboto, system-ui, sans-serif',
}

export const BLANK_2D_CODE = `return {
  render({ ctx, t, width, height, kit }) {
    const { theme } = kit
    kit.draw.background(ctx, [theme.background, theme.surface])
    const enter = kit.tween(t, 0.2, 0.8, 'outCubic')
    kit.draw.text(ctx, 'New scene', width / 2, height / 2 + (1 - enter) * 40, {
      size: height * 0.09, weight: 800, color: theme.text, align: 'center', alpha: enter, family: theme.display,
    })
  },
}`

export const BLANK_3D_CODE = `return {
  setup({ THREE, scene, kit }) {
    kit.three.studioLights(scene)
    const mesh = new THREE.Mesh(
      new THREE.TorusKnotGeometry(1, 0.32, 180, 24),
      new THREE.MeshStandardMaterial({ color: kit.theme.primary, metalness: 0.4, roughness: 0.25 }),
    )
    scene.add(mesh)
    return { mesh }
  },
  render({ camera, t, state, kit }) {
    state.mesh.rotation.set(t * 0.4, t * 0.7, 0)
    kit.three.orbit(camera, t, { radius: 5, height: 1.2, speed: 0.15 })
  },
}`

function text(value: unknown, fallback: string, max: number): string {
  return typeof value === 'string' ? value.slice(0, max) : fallback
}

function finite(value: unknown, fallback: number, min: number, max: number): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback
}

function color(value: unknown, fallback: string): string {
  return typeof value === 'string' && /^#[0-9a-f]{3,8}$/i.test(value.trim()) ? value.trim() : fallback
}

export function newVideoJsId(prefix = 'scene'): string {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10)
  return `${prefix}-${random}`
}

export function normalizeKind(value: unknown): VideoJsSceneKind {
  return typeof value === 'string' && value.trim().toLowerCase() === '3d' ? '3d' : '2d'
}

export function normalizeTransition(value: unknown): VideoJsTransition {
  const candidate = typeof value === 'string' ? value.trim().toLowerCase() : ''
  return (VIDEOJS_TRANSITIONS as readonly string[]).includes(candidate) ? candidate as VideoJsTransition : 'fade'
}

export function normalizeTheme(value: unknown): VideoJsTheme {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const base = DEFAULT_VIDEOJS_THEME
  return {
    background: color(raw.background, base.background),
    surface: color(raw.surface, base.surface),
    primary: color(raw.primary, base.primary),
    secondary: color(raw.secondary, base.secondary),
    accent: color(raw.accent, base.accent),
    text: color(raw.text, base.text),
    muted: color(raw.muted, base.muted),
    font: text(raw.font, base.font, 200).replace(/[;{}<>]/g, '') || base.font,
    display: text(raw.display, base.display, 200).replace(/[;{}<>]/g, '') || base.display,
  }
}

export function createVideoJsScene(kind: VideoJsSceneKind = '2d', patch: Partial<VideoJsScene> = {}): VideoJsScene {
  return normalizeVideoJsScene({
    id: newVideoJsId(),
    title: kind === '3d' ? '3D scene' : 'Scene',
    kind,
    duration: 4,
    transition: 'fade',
    transitionDuration: 0.5,
    code: kind === '3d' ? BLANK_3D_CODE : BLANK_2D_CODE,
    ...patch,
  })
}

export function normalizeVideoJsScene(value: unknown, index = 0): VideoJsScene {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const id = typeof raw.id === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(raw.id) ? raw.id : newVideoJsId()
  const duration = finite(raw.duration, 4, VIDEOJS_LIMITS.minSceneSeconds, VIDEOJS_LIMITS.maxSceneSeconds)
  return {
    id,
    title: text(raw.title, `Scene ${index + 1}`, 120).trim() || `Scene ${index + 1}`,
    kind: normalizeKind(raw.kind),
    duration,
    transition: normalizeTransition(raw.transition),
    transitionDuration: finite(raw.transitionDuration, 0.5, 0, Math.min(VIDEOJS_LIMITS.maxTransitionSeconds, duration)),
    code: text(raw.code, '', VIDEOJS_LIMITS.codeChars),
    ...(typeof raw.notes === 'string' && raw.notes.trim() ? { notes: raw.notes.slice(0, 2000) } : {}),
  }
}

/** Accepts untrusted JSON (imports, drafts, sidecars) and returns a valid document. */
export function normalizeVideoJsDocument(value: unknown): VideoJsDocument {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const scenes = Array.isArray(raw.scenes) ? raw.scenes.slice(0, VIDEOJS_LIMITS.scenes) : []
  const seen = new Set<string>()
  const normalized = scenes.map((scene, index) => {
    const next = normalizeVideoJsScene(scene, index)
    if (seen.has(next.id)) next.id = newVideoJsId()
    seen.add(next.id)
    return next
  })
  const fps = raw.fps === 60 ? 60 : 30
  return {
    schema: VIDEOJS_SCHEMA,
    id: typeof raw.id === 'string' && raw.id ? raw.id.slice(0, 64) : newVideoJsId('video'),
    title: text(raw.title, 'Untitled video', 160).trim() || 'Untitled video',
    width: Math.round(finite(raw.width, 1920, 320, 3840)),
    height: Math.round(finite(raw.height, 1080, 320, 3840)),
    fps,
    theme: normalizeTheme(raw.theme),
    scenes: capTotalDuration(normalized),
    prompt: text(raw.prompt, '', 20_000),
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : new Date(0).toISOString(),
  }
}

function capTotalDuration(scenes: VideoJsScene[]): VideoJsScene[] {
  let total = 0
  return scenes.filter(scene => {
    total += scene.duration
    return total <= VIDEOJS_LIMITS.maxVideoSeconds
  })
}

export function createVideoJsDocument(patch: Partial<VideoJsDocument> = {}): VideoJsDocument {
  return normalizeVideoJsDocument({
    title: 'Untitled video',
    width: 1920,
    height: 1080,
    fps: 30,
    theme: DEFAULT_VIDEOJS_THEME,
    scenes: [createVideoJsScene('2d', { title: 'Opening' })],
    ...patch,
    updatedAt: new Date().toISOString(),
  })
}

export function videoJsDuration(document: Pick<VideoJsDocument, 'scenes'>): number {
  return document.scenes.reduce((sum, scene) => sum + scene.duration, 0)
}

export interface VideoJsSceneSpan {
  scene: VideoJsScene
  index: number
  start: number
  end: number
}

export function videoJsTimeline(document: Pick<VideoJsDocument, 'scenes'>): VideoJsSceneSpan[] {
  let start = 0
  return document.scenes.map((scene, index) => {
    const span = { scene, index, start, end: start + scene.duration }
    start = span.end
    return span
  })
}

/** Scene visible at a global time. The last scene holds its final frame. */
export function videoJsSpanAt(document: Pick<VideoJsDocument, 'scenes'>, seconds: number): VideoJsSceneSpan | null {
  const timeline = videoJsTimeline(document)
  if (!timeline.length) return null
  const time = Number.isFinite(seconds) ? Math.max(0, seconds) : 0
  return timeline.find(span => time < span.end) ?? timeline[timeline.length - 1]
}

/** Just after the entry transition, so a selected scene is shown on its own. */
export function videoJsSceneFocusTime(document: Pick<VideoJsDocument, 'scenes'>, sceneId: string): number {
  const span = videoJsTimeline(document).find(item => item.scene.id === sceneId)
  if (!span) return 0
  const { scene, index, start } = span
  const settle = index > 0 && scene.transition !== 'none' ? scene.transitionDuration : 0
  return start + Math.min(settle + 0.01, scene.duration / 2)
}

export function videoJsFormatOf(document: Pick<VideoJsDocument, 'width' | 'height'>): VideoJsFormat {
  if (document.width === document.height) return 'square'
  return document.width > document.height ? 'landscape' : 'portrait'
}

export function touchVideoJsDocument(document: VideoJsDocument): VideoJsDocument {
  return { ...document, updatedAt: new Date().toISOString() }
}

export function moveVideoJsScene(document: VideoJsDocument, sceneId: string, offset: -1 | 1): VideoJsDocument {
  const index = document.scenes.findIndex(scene => scene.id === sceneId)
  const target = index + offset
  if (index < 0 || target < 0 || target >= document.scenes.length) return document
  const scenes = [...document.scenes]
  const [scene] = scenes.splice(index, 1)
  scenes.splice(target, 0, scene)
  return touchVideoJsDocument({ ...document, scenes })
}

export function updateVideoJsScene(document: VideoJsDocument, sceneId: string, patch: Partial<VideoJsScene>): VideoJsDocument {
  return touchVideoJsDocument({
    ...document,
    scenes: document.scenes.map((scene, index) => scene.id === sceneId
      ? normalizeVideoJsScene({ ...scene, ...patch, id: scene.id }, index)
      : scene),
  })
}

export function duplicateVideoJsScene(document: VideoJsDocument, sceneId: string): VideoJsDocument {
  const index = document.scenes.findIndex(scene => scene.id === sceneId)
  if (index < 0 || document.scenes.length >= VIDEOJS_LIMITS.scenes) return document
  const copy = { ...document.scenes[index], id: newVideoJsId(), title: `${document.scenes[index].title} copy`.slice(0, 120) }
  const scenes = [...document.scenes]
  scenes.splice(index + 1, 0, copy)
  return touchVideoJsDocument({ ...document, scenes })
}
