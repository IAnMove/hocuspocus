import {
  AddEquation, CustomBlending, DataTexture, DoubleSide, InstancedBufferAttribute, InstancedBufferGeometry, LinearFilter, Mesh,
  OneFactor, OneMinusSrcAlphaFactor, OrthographicCamera, PlaneGeometry, RepeatWrapping, RGBAFormat, Scene, ShaderMaterial,
  UnsignedByteType, Vector2, Vector3, Vector4, WebGLRenderer, type BufferGeometry, type IUniform,
} from 'three'
import { smoothstep, rgb } from '../cinematicPaint'
import { fxRandom, type SceneFx } from '../types'
import { INSTANCED_FRAGMENT_HEAD, WINDOW_FRAGMENT_HEAD, WINDOW_VERTEX, instancedVertex } from './glsl'

/** The presence effects of Series' screen effects, drawn with Three.js: a real orthographic WebGL pass per layer, on one
 * shared canvas, painted back onto the frame's 2D context. Nothing is kept between frames: a layer is a pure function of
 * the cue's seed and clock, so a Series render, which paints frame by frame, and a scrub give the same pixels.
 *
 * A layer paints a window of the cue's space (cue units, y down: the unit square around the cue's x/y, scaled by its size)
 * clipped to what the frame shows, at the frame's own resolution up to a pixel budget (a soft effect scales up for free).
 * Where WebGL is not there `drawLayer` says so and the caller falls back to the 2D painter that has always been the effect. */
export type Region = readonly [number, number, number, number]
export type Uniform = number | readonly number[]
export type LayerDef = {
  /** Fragment body: it ends by writing `gl_FragColor` as premultiplied colour and alpha. */
  fragment: string
  /** Particles: this many quads, placed by the vertex stage `particle()` (see `instancedVertex`). One quad over the window when absent. */
  instances?: number
  particle?: string
  /** `add` sums light into the layer, `over` composites the layer's premultiplied colour over it. */
  blend: 'add' | 'over'
  /** How the layer lands on the frame. */
  composite: GlobalCompositeOperation
  /** Pixels at most rendered for the layer's window. */
  maxPixels: number
  /** Where the layer paints, in cue units; the whole visible window when absent (an effect that fills the frame). */
  region?: Region
  /** The layer works in frame pixels, not cue units. */
  frame?: boolean
  extra?: Record<string, IUniform>
  noise?: boolean
}
export type Layer = { def: LayerDef; mesh: Mesh<BufferGeometry, ShaderMaterial> }

/** One cue's clock and look, as the layers read them. */
export type PresenceFrame = {
  cue: SceneFx
  /** The effect's own clock (seconds since the cue started, times its speed). */
  time: number
  /** Seconds since the cue started on the wall clock: what the fades follow, whatever the speed. */
  real: number
  /** 0 to 1: in over half a second and out over the last half second. */
  env: number
  /** The cue's intensity. */
  power: number
  rgb: readonly [number, number, number]
  width: number
  height: number
}

export function presenceFrame(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number): PresenceFrame {
  const real = time / (cue.speed ?? 1), span = Math.max(.001, cue.end - cue.start)
  const edge = Math.min(.5, span * .3)
  const color = rgb(cue.color)
  return {
    cue, time, real, power: cue.intensity,
    env: smoothstep(0, edge, real) * smoothstep(0, edge, span - real),
    rgb: [color[0] / 255, color[1] / 255, color[2] / 255],
    width: ctx.canvas?.width ?? 1, height: ctx.canvas?.height ?? 1,
  }
}

// ---------------------------------------------------------------------------------------------
// The shared canvas.

type Stage = { renderer: WebGLRenderer; canvas: HTMLCanvasElement; scene: Scene; camera: OrthographicCamera; mounted: Mesh | null }
let stage: Stage | null | undefined

function ensureStage(): Stage | null {
  if (stage === null || typeof document === 'undefined') return null
  if (stage && !stage.renderer.getContext().isContextLost()) return stage
  try {
    // Without WebGL the renderer would log an error to the console: ask a throwaway canvas first.
    const probe = document.createElement('canvas').getContext('webgl2')
    if (!probe) { stage = null; return null }
    probe.getExtension('WEBGL_lose_context')?.loseContext()
    const canvas = document.createElement('canvas')
    canvas.width = 16; canvas.height = 16
    const renderer = new WebGLRenderer({ canvas, alpha: true, antialias: false, premultipliedAlpha: true, preserveDrawingBuffer: true, depth: false, stencil: false })
    renderer.setPixelRatio(1)
    renderer.setClearColor(0x000000, 0)
    stage = { renderer, canvas, scene: new Scene(), camera: new OrthographicCamera(-1, 1, 1, -1, 0, 1), mounted: null }
  } catch {
    stage = null
  }
  return stage ?? null
}

/** Whether the stage can paint here: false without WebGL (no DOM, no context, a lost one). */
export function presenceAvailable(ctx: CanvasRenderingContext2D): boolean {
  return typeof ctx.getTransform === 'function' && typeof ctx.drawImage === 'function' && ensureStage() !== null
}

// ---------------------------------------------------------------------------------------------
// Noise, made in code: four tileable value-noise stacks (four octaves each), one per channel.

const NOISE_SIZE = 128
let noise: DataTexture | undefined

function latticeValue(channel: number, octave: number, size: number, x: number, y: number) {
  return fxRandom(channel * 977 + octave * 31 + 5, (((y % size) + size) % size) * size + (((x % size) + size) % size))
}

function noiseTexture(): DataTexture {
  if (noise) return noise
  const data = new Uint8Array(NOISE_SIZE * NOISE_SIZE * 4)
  for (let channel = 0; channel < 4; channel++) for (let y = 0; y < NOISE_SIZE; y++) for (let x = 0; x < NOISE_SIZE; x++) {
    let sum = 0, amplitude = .5, norm = 0
    for (let octave = 0; octave < 4; octave++) {
      const cells = 4 << octave, fx = x / NOISE_SIZE * cells, fy = y / NOISE_SIZE * cells
      const ix = Math.floor(fx), iy = Math.floor(fy), tx = fx - ix, ty = fy - iy
      const sx = tx * tx * (3 - 2 * tx), sy = ty * ty * (3 - 2 * ty)
      const a = latticeValue(channel, octave, cells, ix, iy), b = latticeValue(channel, octave, cells, ix + 1, iy)
      const c = latticeValue(channel, octave, cells, ix, iy + 1), d = latticeValue(channel, octave, cells, ix + 1, iy + 1)
      sum += amplitude * (a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy)
      norm += amplitude; amplitude *= .5
    }
    // Value noise sums cluster around the middle: stretch them over the range.
    data[(y * NOISE_SIZE + x) * 4 + channel] = Math.round(Math.max(0, Math.min(1, (sum / norm - .5) * 2.1 + .5)) * 255)
  }
  noise = new DataTexture(data, NOISE_SIZE, NOISE_SIZE, RGBAFormat, UnsignedByteType)
  noise.wrapS = noise.wrapT = RepeatWrapping
  noise.magFilter = noise.minFilter = LinearFilter
  noise.generateMipmaps = false
  noise.needsUpdate = true
  return noise
}

// ---------------------------------------------------------------------------------------------
// Layers.

function geometry(instances?: number): BufferGeometry {
  const quad = new PlaneGeometry(1, 1)
  if (!instances) return quad
  const grid = new InstancedBufferGeometry()
  grid.index = quad.index
  grid.setAttribute('position', quad.getAttribute('position'))
  grid.setAttribute('uv', quad.getAttribute('uv'))
  grid.instanceCount = instances
  grid.setAttribute('aId', new InstancedBufferAttribute(Float32Array.from({ length: instances }, (_, index) => index), 1))
  return grid
}

export function makeLayer(def: LayerDef): Layer {
  const instanced = Boolean(def.instances)
  const factor = def.blend === 'add' ? OneFactor : OneMinusSrcAlphaFactor
  const material = new ShaderMaterial({
    vertexShader: instanced ? instancedVertex(def.particle ?? '') : WINDOW_VERTEX,
    fragmentShader: `${instanced ? INSTANCED_FRAGMENT_HEAD : WINDOW_FRAGMENT_HEAD}\n${def.noise ? 'uniform sampler2D uNoise;' : ''}\n${def.fragment}`,
    uniforms: {
      uWin: { value: new Vector4() }, uTime: { value: 0 }, uSeed: { value: 1 }, uPower: { value: 1 }, uEnv: { value: 1 }, uUnit: { value: 1 },
      uColor: { value: new Vector3(1, 1, 1) }, uFrame: { value: new Vector2(1, 1) },
      ...(def.noise ? { uNoise: { value: null } } : {}), ...def.extra,
    },
    transparent: true, depthTest: false, depthWrite: false, side: DoubleSide,
    blending: CustomBlending, blendEquation: AddEquation, blendSrc: OneFactor, blendDst: factor, blendSrcAlpha: OneFactor, blendDstAlpha: factor,
  })
  const mesh = new Mesh(geometry(def.instances), material)
  mesh.frustumCulled = false
  return { def, mesh }
}

/** A layer built when first used, so importing the effects costs nothing where there is no WebGL. */
export function lazyLayer(def: () => LayerDef): () => Layer {
  let layer: Layer | undefined
  return () => layer ??= makeLayer(def())
}

export type Window = readonly [number, number, number, number]

/** The part of the layer's region the frame shows, in the context's current space; null when none of it is on the frame. */
export function visibleWindow(ctx: CanvasRenderingContext2D, region?: Region): { win: Window; scale: number } | null {
  const matrix = ctx.getTransform(), scale = Math.hypot(matrix.a, matrix.b)
  if (!(scale > 1e-6) || !Number.isFinite(scale)) return null
  const inverse = matrix.inverse(), width = ctx.canvas.width, height = ctx.canvas.height
  const corners = [[0, 0], [width, 0], [0, height], [width, height]].map(([x, y]) => inverse.transformPoint({ x, y }))
  const xs = corners.map(point => point.x), ys = corners.map(point => point.y)
  const win: [number, number, number, number] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
  if (region) {
    win[0] = Math.max(win[0], region[0]); win[1] = Math.max(win[1], region[1])
    win[2] = Math.min(win[2], region[2]); win[3] = Math.min(win[3], region[3])
  }
  return win[2] - win[0] > 1e-6 && win[3] - win[1] > 1e-6 ? { win, scale } : null
}

/** Render pixels for a window: the frame's resolution, shrunk to the layer's budget. */
export function renderSize(win: Window, scale: number, maxPixels: number): [number, number] {
  let w = Math.max(2, Math.ceil((win[2] - win[0]) * scale)), h = Math.max(2, Math.ceil((win[3] - win[1]) * scale))
  const shrink = Math.sqrt(maxPixels / (w * h))
  if (shrink < 1) { w = Math.max(2, Math.round(w * shrink)); h = Math.max(2, Math.round(h * shrink)) }
  return [Math.min(w, 4096), Math.min(h, 4096)]
}

function setUniform(uniform: IUniform | undefined, value: Uniform) {
  if (!uniform) return
  if (typeof value === 'number') uniform.value = value
  else (uniform.value as { set: (...args: number[]) => void }).set(...value)
}

/** Paint one layer of a cue onto `ctx`, in the context's current space (the cue's, unless the layer is `frame`). Returns
 * false when the stage cannot paint, before anything is drawn. */
export function drawLayer(ctx: CanvasRenderingContext2D, layer: Layer, frame: PresenceFrame, extra: Record<string, Uniform> = {}): boolean {
  const target = ensureStage()
  if (!target) return false
  const { def } = layer
  if (def.frame) { ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0) }
  try {
    const seen = visibleWindow(ctx, def.region)
    if (!seen) return true
    const [w, h] = renderSize(seen.win, seen.scale, def.maxPixels)
    const uniforms = layer.mesh.material.uniforms
    setUniform(uniforms.uWin, seen.win); setUniform(uniforms.uTime, frame.time); setUniform(uniforms.uSeed, frame.cue.seed)
    setUniform(uniforms.uPower, frame.power); setUniform(uniforms.uEnv, frame.env); setUniform(uniforms.uUnit, seen.scale)
    setUniform(uniforms.uColor, frame.rgb); setUniform(uniforms.uFrame, [frame.width, frame.height])
    if (def.noise) uniforms.uNoise.value = noiseTexture()
    for (const [name, value] of Object.entries(extra)) setUniform(uniforms[name], value)
    if (target.canvas.width !== w || target.canvas.height !== h) target.renderer.setSize(w, h, false)
    if (target.mounted !== layer.mesh) {
      if (target.mounted) target.scene.remove(target.mounted)
      target.scene.add(layer.mesh); target.mounted = layer.mesh
    }
    target.renderer.clear()
    target.renderer.render(target.scene, target.camera)
    ctx.save()
    ctx.globalCompositeOperation = def.composite
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'
    ctx.drawImage(target.canvas, seen.win[0], seen.win[1], seen.win[2] - seen.win[0], seen.win[3] - seen.win[1])
    ctx.restore()
    return true
  } finally {
    if (def.frame) ctx.restore()
  }
}
