/* Video JS scene runtime. Loaded as text and started as a Worker inside the
 * sandboxed iframe (opaque origin, no network). It is never imported by the
 * app bundle. Pixels are a pure function of time: preview and export ask for
 * the same frame and get the same image. */
'use strict'

const TAU = Math.PI * 2
const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value))
const lerp = (a, b, p) => a + (b - a) * p
const invLerp = (a, b, value) => (a === b ? 0 : (value - a) / (b - a))
const smoothstep = (a, b, value) => {
  const x = clamp(invLerp(a, b, value))
  return x * x * (3 - 2 * x)
}

function bounce(x) {
  const n = 7.5625
  const d = 2.75
  if (x < 1 / d) return n * x * x
  if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75
  if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375
  return n * (x -= 2.625 / d) * x + 0.984375
}

const ease = {
  linear: x => x,
  inQuad: x => x * x,
  outQuad: x => 1 - (1 - x) * (1 - x),
  inOutQuad: x => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2),
  inCubic: x => x * x * x,
  outCubic: x => 1 - Math.pow(1 - x, 3),
  inOutCubic: x => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  outQuart: x => 1 - Math.pow(1 - x, 4),
  inOutQuart: x => (x < 0.5 ? 8 * x * x * x * x : 1 - Math.pow(-2 * x + 2, 4) / 2),
  outExpo: x => (x === 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inOutExpo: x => (x === 0 || x === 1 ? x : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2),
  outSine: x => Math.sin((x * Math.PI) / 2),
  inOutSine: x => -(Math.cos(Math.PI * x) - 1) / 2,
  outBack: x => 1 + 2.70158 * Math.pow(x - 1, 3) + 1.70158 * Math.pow(x - 1, 2),
  outElastic: x => (x === 0 || x === 1 ? x : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * (TAU / 3)) + 1),
  outBounce: bounce,
}

function applyEase(name, x) {
  const fn = typeof name === 'function' ? name : ease[name] || ease.linear
  return fn(clamp(x))
}

function hashSeed(value) {
  const text = String(value)
  let hash = 2166136261
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function random(seed = 1) {
  let state = (typeof seed === 'number' ? seed : hashSeed(seed)) >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function lattice(index, seed) {
  return random(hashSeed(`${seed}:${index}`))()
}

function noise(x, seed = 0) {
  const i = Math.floor(x)
  const f = x - i
  return lerp(lattice(i, seed), lattice(i + 1, seed), f * f * (3 - 2 * f)) * 2 - 1
}

function tween(t, start, duration, easing = 'outCubic') {
  if (!(duration > 0)) return t >= start ? 1 : 0
  return applyEase(easing, (t - start) / duration)
}

function stagger(t, index, options = {}) {
  const { start = 0, each = 0.12, duration = 0.6, ease: easing = 'outCubic' } = options
  return tween(t, start + index * each, duration, easing)
}

function mixValue(a, b, p) {
  if (Array.isArray(a) && Array.isArray(b)) return a.map((value, index) => lerp(value, b[index] ?? value, p))
  return lerp(a, b, p)
}

/** frames: [[time, value, ease?], ...]. Values may be numbers or number arrays. */
function keyframes(t, frames) {
  if (!Array.isArray(frames) || !frames.length) return 0
  const sorted = [...frames].sort((a, b) => a[0] - b[0])
  if (t <= sorted[0][0]) return sorted[0][1]
  for (let index = 1; index < sorted.length; index += 1) {
    const [time, value, easing] = sorted[index]
    const [previousTime, previousValue] = sorted[index - 1]
    if (t <= time) return mixValue(previousValue, value, applyEase(easing || 'inOutCubic', invLerp(previousTime, time, t)))
  }
  return sorted[sorted.length - 1][1]
}

function parseColor(value) {
  const text = String(value || '').trim()
  const hex = text.match(/^#([0-9a-f]{3,8})$/i)
  if (hex) {
    const raw = hex[1].length <= 4 ? hex[1].split('').map(c => c + c).join('') : hex[1]
    const alpha = raw.length === 8 ? parseInt(raw.slice(6, 8), 16) / 255 : 1
    return [parseInt(raw.slice(0, 2), 16), parseInt(raw.slice(2, 4), 16), parseInt(raw.slice(4, 6), 16), alpha]
  }
  const rgb = text.match(/^rgba?\(([^)]+)\)$/i)
  if (rgb) {
    const parts = rgb[1].split(/[\s,/]+/).filter(Boolean).map(Number)
    return [parts[0] || 0, parts[1] || 0, parts[2] || 0, parts[3] ?? 1]
  }
  return [0, 0, 0, 1]
}

const rgba = ([r, g, b, a]) => `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${Math.round(clamp(a) * 1000) / 1000})`

const color = {
  mix: (a, b, p) => rgba(mixValue(parseColor(a), parseColor(b), clamp(p))),
  alpha: (value, alpha) => {
    const parsed = parseColor(value)
    return rgba([parsed[0], parsed[1], parsed[2], parsed[3] * alpha])
  },
  hsl: (h, s, l, a = 1) => `hsla(${h}, ${s}%, ${l}%, ${a})`,
}

function createKit(env) {
  const { width, height, fps, theme } = env
  const font = (size, weight = 600, family = theme.font) => `${weight} ${Math.max(1, Math.round(size))}px ${family}`
  const kit = {
    width, height, fps, theme, TAU,
    math: { clamp, lerp, invLerp, smoothstep, remap: (v, a, b, c, d, e) => lerp(c, d, applyEase(e, invLerp(a, b, v))) },
    ease, tween, stagger, keyframes, random, noise, color, font,
    loop: (t, period) => ((t % period) + period) % period / period,
    wave: (t, frequency = 1, phase = 0) => Math.sin((t * frequency + phase) * TAU),
  }
  kit.text = createTextKit(kit)
  kit.layout = createLayoutKit(width, height)
  kit.draw = createDrawKit(kit)
  kit.three = createThreeKit(env)
  return kit
}

function createTextKit(kit) {
  const wrap = (ctx, value, maxWidth) => {
    const lines = []
    for (const paragraph of String(value ?? '').split('\n')) {
      let line = ''
      for (const word of paragraph.split(/\s+/).filter(Boolean)) {
        const candidate = line ? `${line} ${word}` : word
        if (line && maxWidth && ctx.measureText(candidate).width > maxWidth) {
          lines.push(line)
          line = word
        } else line = candidate
      }
      lines.push(line)
    }
    return lines
  }
  return {
    wrap,
    typewriter: (value, progress) => {
      const text = String(value ?? '')
      return text.slice(0, Math.round(text.length * clamp(progress)))
    },
    number: (value, options = {}) => {
      const { decimals = 0, prefix = '', suffix = '', locale = 'en-US' } = options
      return `${prefix}${Number(value).toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`
    },
    fit: (ctx, value, maxWidth, maxSize, options = {}) => {
      const { minSize = 8, weight = 700, family = kit.theme.display } = options
      let size = maxSize
      ctx.font = kit.font(size, weight, family)
      const measured = ctx.measureText(String(value ?? '')).width
      if (measured > maxWidth) size = Math.max(minSize, (size * maxWidth) / measured)
      return size
    },
  }
}

function createLayoutKit(width, height) {
  const safe = (margin = 0.06) => {
    const pad = Math.round(Math.min(width, height) * margin)
    return { x: pad, y: pad, w: width - pad * 2, h: height - pad * 2, cx: width / 2, cy: height / 2, right: width - pad, bottom: height - pad }
  }
  const grid = (area, columns = 2, rows = 1, gap = 24) => {
    const cells = []
    const cellW = (area.w - gap * (columns - 1)) / columns
    const cellH = (area.h - gap * (rows - 1)) / rows
    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const x = area.x + column * (cellW + gap)
        const y = area.y + row * (cellH + gap)
        cells.push({ x, y, w: cellW, h: cellH, cx: x + cellW / 2, cy: y + cellH / 2 })
      }
    }
    return cells
  }
  return { safe, grid }
}

function withStyle(ctx, options, draw) {
  ctx.save()
  if (options.alpha !== undefined) ctx.globalAlpha *= clamp(options.alpha)
  if (options.shadow) {
    ctx.shadowColor = options.shadow.color || 'rgba(0,0,0,0.45)'
    ctx.shadowBlur = options.shadow.blur ?? 24
    ctx.shadowOffsetX = options.shadow.x ?? 0
    ctx.shadowOffsetY = options.shadow.y ?? 8
  }
  try {
    return draw()
  } finally {
    ctx.restore()
  }
}

function paint(ctx, options) {
  if (options.fill) {
    ctx.fillStyle = options.fill
    ctx.fill()
  }
  if (options.stroke) {
    ctx.strokeStyle = options.stroke
    ctx.lineWidth = options.lineWidth ?? 2
    ctx.stroke()
  }
}

function createDrawKit(kit) {
  const { theme } = kit
  const canvasSize = ctx => [ctx.canvas.width, ctx.canvas.height]
  const draw = {
    background(ctx, fill = theme.background, options = {}) {
      const [w, h] = canvasSize(ctx)
      if (Array.isArray(fill)) {
        const angle = ((options.angle ?? 135) * Math.PI) / 180
        const dx = (Math.cos(angle) * w) / 2
        const dy = (Math.sin(angle) * h) / 2
        const gradient = ctx.createLinearGradient(w / 2 - dx, h / 2 - dy, w / 2 + dx, h / 2 + dy)
        fill.forEach((stop, index) => gradient.addColorStop(fill.length === 1 ? 0 : index / (fill.length - 1), stop))
        ctx.fillStyle = gradient
      } else ctx.fillStyle = fill
      ctx.fillRect(0, 0, w, h)
    },
    text(ctx, value, x, y, options = {}) {
      return withStyle(ctx, options, () => {
        const size = options.size ?? 48
        ctx.font = kit.font(size, options.weight ?? 600, options.family ?? theme.font)
        ctx.fillStyle = options.color ?? theme.text
        ctx.textAlign = options.align ?? 'left'
        ctx.textBaseline = options.baseline ?? 'alphabetic'
        if ('letterSpacing' in ctx) ctx.letterSpacing = `${options.letterSpacing ?? 0}px`
        const lines = kit.text.wrap(ctx, value, options.maxWidth)
        const lineHeight = size * (options.lineHeight ?? 1.2)
        let width = 0
        lines.forEach((line, index) => {
          ctx.fillText(line, x, y + index * lineHeight)
          width = Math.max(width, ctx.measureText(line).width)
        })
        return { width, height: lines.length * lineHeight, lines }
      })
    },
    roundRect(ctx, x, y, w, h, radius = 16, options = {}) {
      withStyle(ctx, options, () => {
        ctx.beginPath()
        ctx.roundRect(x, y, w, h, radius)
        paint(ctx, options.fill || options.stroke ? options : { fill: theme.surface })
      })
    },
    circle(ctx, x, y, radius, options = {}) {
      withStyle(ctx, options, () => {
        ctx.beginPath()
        ctx.arc(x, y, Math.max(0, radius), 0, TAU)
        paint(ctx, options.fill || options.stroke ? options : { fill: theme.primary })
      })
    },
    line(ctx, x1, y1, x2, y2, options = {}) {
      withStyle(ctx, options, () => {
        const progress = clamp(options.progress ?? 1)
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(lerp(x1, x2, progress), lerp(y1, y2, progress))
        ctx.lineCap = options.cap ?? 'round'
        ctx.strokeStyle = options.color ?? theme.primary
        ctx.lineWidth = options.width ?? 4
        ctx.stroke()
      })
    },
    glow(ctx, x, y, radius, fill = theme.primary, alpha = 0.5) {
      const gradient = ctx.createRadialGradient(x, y, 0, x, y, Math.max(1, radius))
      gradient.addColorStop(0, color.alpha(fill, alpha))
      gradient.addColorStop(1, color.alpha(fill, 0))
      ctx.fillStyle = gradient
      ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2)
    },
    vignette(ctx, strength = 0.55) {
      const [w, h] = canvasSize(ctx)
      const gradient = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.3, w / 2, h / 2, Math.hypot(w, h) / 2)
      gradient.addColorStop(0, 'rgba(0,0,0,0)')
      gradient.addColorStop(1, `rgba(0,0,0,${clamp(strength)})`)
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, w, h)
    },
    grid(ctx, options = {}) {
      const [w, h] = canvasSize(ctx)
      const { spacing = 80, color: stroke = theme.text, alpha = 0.06, lineWidth = 1, offsetX = 0, offsetY = 0 } = options
      withStyle(ctx, { alpha }, () => {
        ctx.beginPath()
        for (let x = ((offsetX % spacing) + spacing) % spacing; x <= w; x += spacing) { ctx.moveTo(x, 0); ctx.lineTo(x, h) }
        for (let y = ((offsetY % spacing) + spacing) % spacing; y <= h; y += spacing) { ctx.moveTo(0, y); ctx.lineTo(w, y) }
        ctx.strokeStyle = stroke
        ctx.lineWidth = lineWidth
        ctx.stroke()
      })
    },
    grain(ctx, options = {}) {
      const [w, h] = canvasSize(ctx)
      const { amount = 0.05, seed = 0 } = options
      const next = random(hashSeed(`grain:${seed}`))
      withStyle(ctx, { alpha: amount }, () => {
        ctx.globalCompositeOperation = 'overlay'
        ctx.fillStyle = grainPattern(ctx)
        ctx.translate(-next() * 256, -next() * 256)
        ctx.fillRect(0, 0, w + 256, h + 256)
      })
    },
    progressBar(ctx, x, y, w, h, progress, options = {}) {
      draw.roundRect(ctx, x, y, w, h, options.radius ?? h / 2, { fill: options.track ?? color.alpha(theme.text, 0.12) })
      if (progress > 0) draw.roundRect(ctx, x, y, Math.max(h, w * clamp(progress)), h, options.radius ?? h / 2, { fill: options.fill ?? theme.primary })
    },
    bullets(ctx, items, x, y, options = {}) {
      const { size = 40, gap = 1.7, t = Infinity, start = 0, each = 0.25, maxWidth } = options
      let offset = 0
      items.forEach((item, index) => {
        const enter = Number.isFinite(t) ? stagger(t, index, { start, each, duration: 0.6 }) : 1
        const shift = (1 - enter) * size
        draw.circle(ctx, x + size * 0.25 - shift, y + offset - size * 0.32, size * 0.16, { fill: options.bulletColor ?? theme.primary, alpha: enter })
        const block = draw.text(ctx, item, x + size - shift, y + offset, { size, maxWidth, color: options.color ?? theme.text, weight: options.weight ?? 500, alpha: enter, family: options.family })
        offset += Math.max(block.height, size) + size * (gap - 1.2)
      })
      return offset
    },
    barChart(ctx, data, area, options = {}) {
      const { t = Infinity, start = 0, each = 0.12, colors = [theme.primary, theme.secondary, theme.accent] } = options
      const max = options.max ?? Math.max(1, ...data.map(item => Number(item.value) || 0))
      const gap = area.w * 0.04
      const barW = (area.w - gap * (data.length - 1)) / Math.max(1, data.length)
      data.forEach((item, index) => {
        const grow = Number.isFinite(t) ? stagger(t, index, { start, each, duration: 0.9 }) : 1
        const barH = (area.h - 60) * clamp((Number(item.value) || 0) / max) * grow
        const bx = area.x + index * (barW + gap)
        draw.roundRect(ctx, bx, area.y + area.h - 44 - barH, barW, barH, Math.min(12, barW / 4), { fill: colors[index % colors.length] })
        draw.text(ctx, item.label, bx + barW / 2, area.y + area.h - 8, { size: 26, align: 'center', color: theme.muted, alpha: grow })
      })
    },
  }
  return draw
}

let grainCanvas = null
function grainPattern(ctx) {
  if (!grainCanvas) {
    grainCanvas = new OffscreenCanvas(256, 256)
    const context = grainCanvas.getContext('2d')
    const image = context.createImageData(256, 256)
    const next = random(1337)
    for (let index = 0; index < image.data.length; index += 4) {
      const value = Math.round(next() * 255)
      image.data.set([value, value, value, 255], index)
    }
    context.putImageData(image, 0, 0)
  }
  return ctx.createPattern(grainCanvas, 'repeat')
}

function createThreeKit(env) {
  return {
    studioLights(scene, options = {}) {
      const THREE = env.THREE
      if (!THREE) throw new Error('kit.three is only available in 3D scenes')
      const intensity = options.intensity ?? 1
      scene.add(new THREE.HemisphereLight(0xffffff, 0x223344, 1.1 * intensity))
      const key = new THREE.DirectionalLight(0xffffff, 2.2 * intensity)
      key.position.set(4, 6, 5)
      const rim = new THREE.DirectionalLight(env.theme.secondary, 1.4 * intensity)
      rim.position.set(-5, 3, -4)
      scene.add(key, rim)
      return { key, rim }
    },
    orbit(camera, t, options = {}) {
      const { radius = 6, height = 1.5, speed = 0.1, start = 0, target = [0, 0, 0] } = options
      const angle = (start + t * speed) * TAU
      camera.position.set(target[0] + Math.sin(angle) * radius, target[1] + height, target[2] + Math.cos(angle) * radius)
      camera.lookAt(target[0], target[1], target[2])
    },
  }
}

/* ---------- determinism guards ---------- */

let clockMs = 0
let seeded = random(1)
Math.random = () => seeded()
Date.now = () => clockMs
if (self.performance) self.performance.now = () => clockMs
for (const name of ['setTimeout', 'setInterval', 'requestAnimationFrame']) {
  self[name] = () => { throw new Error(`${name} is disabled: Video JS renders each frame from render({ t })`) }
}
self.fetch = () => Promise.reject(new Error('Network access is disabled in Video JS scenes'))

function useClock(sceneId, seconds, frame) {
  clockMs = Math.round(seconds * 1000)
  seeded = random(hashSeed(`${sceneId}:${frame}`))
}

/* ---------- scenes ---------- */

// Chrome/Node report Function bodies as `<anonymous>:line:col`, Firefox as `> Function:line:col`.
const CODE_FRAME = /(?:<anonymous>|> Function):(\d+):\d+/

const LINE_OFFSET = (() => {
  try {
    new Function('kit', 'THREE', '"use strict";\nthrow new Error("probe")')()
  } catch (error) {
    const match = String(error.stack || '').match(CODE_FRAME)
    return match ? Number(match[1]) - 1 : 0
  }
  return 0
})()

function errorInfo(sceneId, phase, error) {
  const message = error instanceof Error ? `${error.name}: ${error.message}` : String(error)
  const match = String(error?.stack || '').match(CODE_FRAME)
  const line = match && LINE_OFFSET ? Number(match[1]) - LINE_OFFSET : undefined
  return { sceneId, phase, message: message.slice(0, 1000), ...(line > 0 ? { line } : {}) }
}

let runtime = null

function loadThree(source) {
  if (!source) return null
  const module = { exports: {} }
  new Function('module', 'exports', source)(module, module.exports)
  return module.exports
}

function compileScene(spec, env) {
  const body = String(spec.code || '').replace(/^\s*export\s+default\s+/m, 'return ')
  const factory = new Function('kit', 'THREE', `"use strict";\n${body}`)
  const definition = factory(env.kit, env.THREE)
  if (!definition || typeof definition.render !== 'function') {
    throw new Error('Scene code must return an object with render({ ctx, t, ... })')
  }
  return definition
}

function setupScene(spec, env) {
  const entry = { spec, definition: null, state: undefined, three: null, error: null }
  postMessage({ type: 'begin', sceneId: spec.id })
  try {
    entry.definition = compileScene(spec, env)
  } catch (error) {
    entry.error = errorInfo(spec.id, 'compile', error)
    return entry
  }
  try {
    useClock(spec.id, 0, 0)
    if (spec.kind === '3d') entry.three = createThreeScene(env)
    const base = { kit: env.kit, width: env.width, height: env.height, fps: env.fps, duration: spec.duration, theme: env.theme }
    entry.state = entry.definition.setup?.({ ...base, ...(entry.three || {}), THREE: env.THREE })
  } catch (error) {
    entry.error = errorInfo(spec.id, 'setup', error)
  }
  return entry
}

function createThreeScene(env) {
  const THREE = env.THREE
  if (!THREE) throw new Error('THREE is not loaded for this 3D scene')
  if (!env.renderer) {
    env.renderer = new THREE.WebGLRenderer({ canvas: new OffscreenCanvas(env.width, env.height), antialias: true, preserveDrawingBuffer: true })
    env.renderer.setPixelRatio(1)
    env.renderer.setSize(env.width, env.height, false)
    env.renderer.outputColorSpace = THREE.SRGBColorSpace
    env.renderer.toneMapping = THREE.ACESFilmicToneMapping
  }
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(env.theme.background)
  const camera = new THREE.PerspectiveCamera(45, env.width / env.height, 0.1, 1000)
  camera.position.set(0, 1.2, 6)
  camera.lookAt(0, 0, 0)
  return { scene, camera, renderer: env.renderer }
}

function drawSceneError(ctx, env, error) {
  ctx.fillStyle = '#1a0b12'
  ctx.fillRect(0, 0, env.width, env.height)
  const size = Math.round(env.height * 0.035)
  ctx.font = `600 ${size}px ${env.theme.font}`
  ctx.fillStyle = '#fda4af'
  ctx.textAlign = 'left'
  ctx.textBaseline = 'top'
  env.kit.text.wrap(ctx, `⚠ ${error.phase}: ${error.message}`, env.width * 0.84).slice(0, 8).forEach((line, index) => {
    ctx.fillText(line, env.width * 0.08, env.height * 0.1 + index * size * 1.4)
  })
}

function resetContext(ctx, env) {
  if (typeof ctx.reset === 'function') ctx.reset()
  else {
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
  }
  ctx.clearRect(0, 0, env.width, env.height)
}

function renderScene(entry, seconds, ctx, env, errors) {
  resetContext(ctx, env)
  if (entry.error) {
    drawSceneError(ctx, env, entry.error)
    return
  }
  const { spec, definition } = entry
  const t = clamp(seconds, 0, spec.duration)
  const frame = Math.round(t * env.fps)
  postMessage({ type: 'begin', sceneId: spec.id })
  useClock(spec.id, t, frame)
  const args = {
    ctx, t, p: spec.duration > 0 ? t / spec.duration : 1, frame, fps: env.fps, duration: spec.duration,
    width: env.width, height: env.height, kit: env.kit, theme: env.theme, state: entry.state, THREE: env.THREE,
    ...(entry.three || {}),
  }
  try {
    definition.render(args)
    if (entry.three) {
      entry.three.renderer.render(entry.three.scene, entry.three.camera)
      ctx.drawImage(entry.three.renderer.domElement, 0, 0, env.width, env.height)
    }
    definition.overlay?.(args)
  } catch (error) {
    const info = errorInfo(spec.id, 'render', error)
    errors.push(info)
    resetContext(ctx, env)
    drawSceneError(ctx, env, info)
  }
}

function composite(ctx, env, previous, current, transition, progress) {
  const { width: w, height: h } = env
  const e = ease.inOutCubic(clamp(progress))
  ctx.save()
  if (transition === 'slide-left' || transition === 'slide-up') {
    const horizontal = transition === 'slide-left'
    ctx.drawImage(previous, horizontal ? -e * w : 0, horizontal ? 0 : -e * h)
    ctx.drawImage(current, horizontal ? (1 - e) * w : 0, horizontal ? 0 : (1 - e) * h)
  } else if (transition === 'wipe') {
    ctx.drawImage(previous, 0, 0)
    ctx.beginPath()
    ctx.rect(0, 0, e * w, h)
    ctx.clip()
    ctx.drawImage(current, 0, 0)
  } else if (transition === 'zoom') {
    const drawScaled = (image, scale, alpha) => {
      ctx.globalAlpha = alpha
      ctx.drawImage(image, (w - w * scale) / 2, (h - h * scale) / 2, w * scale, h * scale)
    }
    drawScaled(previous, 1 + 0.12 * e, 1)
    drawScaled(current, 1.12 - 0.12 * e, e)
  } else {
    ctx.drawImage(previous, 0, 0)
    ctx.globalAlpha = e
    ctx.drawImage(current, 0, 0)
  }
  ctx.restore()
}

function spanAt(scenes, seconds) {
  let start = 0
  for (let index = 0; index < scenes.length; index += 1) {
    const end = start + scenes[index].spec.duration
    if (seconds < end || index === scenes.length - 1) return { index, local: Math.max(0, seconds - start) }
    start = end
  }
  return null
}

function renderFrame(seconds) {
  const env = runtime
  const errors = []
  const out = env.output.getContext('2d')
  resetContext(out, env)
  const span = spanAt(env.scenes, seconds)
  if (!span) {
    out.fillStyle = env.theme.background
    out.fillRect(0, 0, env.width, env.height)
    return errors
  }
  const current = env.scenes[span.index]
  renderScene(current, span.local, env.bufferA.getContext('2d'), env, errors)
  const { transition, transitionDuration } = current.spec
  if (span.index > 0 && transition !== 'none' && transitionDuration > 0 && span.local < transitionDuration) {
    const previous = env.scenes[span.index - 1]
    renderScene(previous, previous.spec.duration, env.bufferB.getContext('2d'), env, errors)
    composite(out, env, env.bufferB, env.bufferA, transition, span.local / transitionDuration)
  } else out.drawImage(env.bufferA, 0, 0)
  return errors
}

function init(message) {
  const doc = message.document
  const env = {
    width: doc.width, height: doc.height, fps: doc.fps, theme: doc.theme,
    THREE: doc.scenes.some(scene => scene.kind === '3d') ? loadThree(message.three) : null,
    output: new OffscreenCanvas(doc.width, doc.height),
    bufferA: new OffscreenCanvas(doc.width, doc.height),
    bufferB: new OffscreenCanvas(doc.width, doc.height),
    renderer: null,
  }
  env.kit = createKit(env)
  runtime = env
  env.scenes = doc.scenes.map(spec => setupScene(spec, env))
  postMessage({ type: 'ready', errors: env.scenes.filter(entry => entry.error).map(entry => entry.error) })
}

self.onmessage = event => {
  const message = event.data || {}
  try {
    if (message.type === 'init') init(message)
    else if (message.type === 'frame' && runtime) {
      const errors = renderFrame(Number(message.time) || 0)
      const bitmap = runtime.output.transferToImageBitmap()
      postMessage({ type: 'frame', id: message.id, bitmap, errors }, [bitmap])
    }
  } catch (error) {
    postMessage({ type: 'fatal', id: message.id, error: errorInfo('', 'runtime', error) })
  }
}

// Test hook: node:vm loads this file with a `module` object. Workers have none.
if (typeof module !== 'undefined') {
  module.exports = { applyEase, clamp, color, createKit, ease, hashSeed, keyframes, noise, random, spanAt, stagger, tween }
}
