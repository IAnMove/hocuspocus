// Pure Video 2D layer styling: effects, strips, masks and procedural atmosphere.
// Shared by the Scene Animator preview/export and the headless scene2d renderer.
import { withAlpha } from '../../features/sceneFx/color'
import type { SceneAtmosphereKind, SceneBlendMode, SceneLayer, SceneMask } from '../../types'
import { normalizeSeamOccluder } from '../seamOccluder'
import type { AnimatorLayer, Atmosphere, LayerEffects, LayerStrip, VisualAnimatorLayer } from './types'
export const DEFAULT_EFFECTS: LayerEffects = { blur: 0, brightness: 1, contrast: 1, saturation: 1, hue: 0, glow: 0, shadow: 0, blendMode: 'normal', mask: 'none', maskRadius: 12 }
export const DEFAULT_STRIP: LayerStrip = { enabled: false, count: 5, spacing: 24, direction: 'down', speed: 18, phase: 0, seamOccluder: { enabled: false, kind: 'pole', scale: 1, opacity: .82 } }
export const ATMOSPHERE_KINDS: SceneAtmosphereKind[] = ['rain', 'snow', 'dust', 'embers', 'fog', 'smoke', 'ash', 'fireflies', 'confetti', 'bokeh', 'sparkles', 'bubbles', 'speedlines', 'leaves']
export const ATMOSPHERE_OPACITY: Record<SceneAtmosphereKind, number> = {
  rain: .92, snow: .95, dust: .78, embers: .92, fog: .58, smoke: .62, ash: .72,
  fireflies: .95, confetti: 1, bokeh: .58, sparkles: .9, bubbles: .85, speedlines: .7, leaves: .95,
}
export const ATMOSPHERE_PRESETS: Record<SceneAtmosphereKind, Atmosphere> = {
  rain: { kind: 'rain', density: 145, speed: 1.3, size: 1.65, wind: -10, color: '#dbeafe' },
  snow: { kind: 'snow', density: 90, speed: .42, size: 2.15, wind: 8, color: '#ffffff' },
  dust: { kind: 'dust', density: 58, speed: .25, size: 2.5, wind: 18, color: '#fde68a' },
  embers: { kind: 'embers', density: 68, speed: .62, size: 1.55, wind: 10, color: '#fb923c' },
  fog: { kind: 'fog', density: 16, speed: .18, size: 1.15, wind: 28, color: '#dbeafe' },
  smoke: { kind: 'smoke', density: 22, speed: .3, size: .85, wind: 12, color: '#cbd5e1' },
  ash: { kind: 'ash', density: 95, speed: .34, size: 1.35, wind: 14, color: '#d1d5db' },
  fireflies: { kind: 'fireflies', density: 38, speed: .22, size: 1.4, wind: 4, color: '#fde047' },
  confetti: { kind: 'confetti', density: 86, speed: .72, size: 1.65, wind: 12, color: '#f472b6' },
  bokeh: { kind: 'bokeh', density: 24, speed: .12, size: 2.8, wind: 6, color: '#f0abfc' },
  sparkles: { kind: 'sparkles', density: 42, speed: .18, size: 1.8, wind: 4, color: '#ffffff' },
  bubbles: { kind: 'bubbles', density: 46, speed: .45, size: 1.6, wind: 5, color: '#bae6fd' },
  speedlines: { kind: 'speedlines', density: 72, speed: 1.65, size: 1.15, wind: 45, color: '#e0f2fe' },
  leaves: { kind: 'leaves', density: 54, speed: .48, size: 1.8, wind: 20, color: '#f59e0b' },
}
export const finiteNumber = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
export const boundedNumber = (value: unknown, fallback: number, min: number, max: number) => Math.max(min, Math.min(max, finiteNumber(value, fallback)))
export const normalizedEffects = (value: SceneLayer['effects'] | undefined): LayerEffects => ({
  blur: boundedNumber(value?.blur, DEFAULT_EFFECTS.blur, 0, 3),
  brightness: boundedNumber(value?.brightness, DEFAULT_EFFECTS.brightness, 0, 3),
  contrast: boundedNumber(value?.contrast, DEFAULT_EFFECTS.contrast, 0, 3),
  saturation: boundedNumber(value?.saturation, DEFAULT_EFFECTS.saturation, 0, 4),
  hue: boundedNumber(value?.hue, DEFAULT_EFFECTS.hue, -180, 180),
  glow: boundedNumber(value?.glow, DEFAULT_EFFECTS.glow, 0, 5),
  shadow: boundedNumber(value?.shadow, DEFAULT_EFFECTS.shadow, 0, 8),
  blendMode: ['normal', 'multiply', 'screen', 'overlay', 'lighten', 'darken'].includes(value?.blendMode ?? '') ? value?.blendMode as SceneBlendMode : 'normal',
  mask: ['none', 'rounded', 'ellipse'].includes(value?.mask ?? '') ? value?.mask as SceneMask : 'none',
  maskRadius: boundedNumber(value?.maskRadius, DEFAULT_EFFECTS.maskRadius, 0, 50),
})
export const normalizedStrip = (value: SceneLayer['strip'] | undefined): LayerStrip => ({
  enabled: value?.enabled === true,
  count: Math.round(boundedNumber(value?.count, DEFAULT_STRIP.count, 1, 12)),
  spacing: boundedNumber(value?.spacing, DEFAULT_STRIP.spacing, 2, 200),
  direction: ['up', 'down', 'left', 'right'].includes(value?.direction ?? '') ? value?.direction as LayerStrip['direction'] : DEFAULT_STRIP.direction,
  speed: boundedNumber(value?.speed, DEFAULT_STRIP.speed, 0, 300),
  phase: boundedNumber(value?.phase, DEFAULT_STRIP.phase, -1000, 1000),
  seamOccluder: normalizeSeamOccluder(value?.seamOccluder),
})
export const normalizedAtmosphere = (value: SceneLayer['atmosphere'] | undefined): Atmosphere => {
  const kind = ATMOSPHERE_KINDS.includes(value?.kind as SceneAtmosphereKind) ? value!.kind : 'rain'
  const preset = ATMOSPHERE_PRESETS[kind]
  return {
    kind,
    density: Math.round(boundedNumber(value?.density, preset.density, 5, 240)),
    speed: boundedNumber(value?.speed, preset.speed, .05, 4),
    size: boundedNumber(value?.size, preset.size, .2, 8),
    wind: boundedNumber(value?.wind, preset.wind, -100, 100),
    color: typeof value?.color === 'string' && /^#[0-9a-f]{6}$/i.test(value.color) ? value.color : preset.color,
  }
}
export const particleNoise = (index: number, salt: number) => {
  const value = Math.sin((index + 1) * 12.9898 + salt * 78.233) * 43758.5453
  return value - Math.floor(value)
}
const PARTICLE_RATE: Partial<Record<SceneAtmosphereKind, number>> = { rain: .55, snow: .09, embers: .16, bubbles: .16, confetti: .12, leaves: .12, ash: .075, speedlines: .5 }
export const atmosphereParticles = (atmosphere: Atmosphere, seconds: number) => Array.from({ length: atmosphere.density }, (_, index) => {
  const phase = particleNoise(index, 1.7)
  const baseX = particleNoise(index, 4.1) * 120 - 10
  const baseY = particleNoise(index, 8.3) * 120 - 10
  const depth = .35 + particleNoise(index, 11.9) * .65
  const pulse = .35 + .65 * Math.abs(Math.sin(seconds * (1.2 + depth * 2.4) + phase * Math.PI * 2))
  const rotation = (particleNoise(index, 15.3) * 360 + seconds * atmosphere.speed * (30 + depth * 100)) % 360
  const rate = PARTICLE_RATE[atmosphere.kind] ?? .045
  const travel = ((phase + seconds * atmosphere.speed * rate * depth) % 1 + 1) % 1
  const wind = atmosphere.wind * travel * .18
  const shared = { size: atmosphere.size * depth, pulse, rotation, variant: Math.floor(particleNoise(index, 19.7) * 6) }
  if (atmosphere.kind === 'embers' || atmosphere.kind === 'smoke' || atmosphere.kind === 'bubbles') return { ...shared, x: baseX + wind + Math.sin(seconds * 1.7 + index) * (atmosphere.kind === 'smoke' ? 4 : 1.8), y: 110 - travel * 120, alpha: atmosphere.kind === 'smoke' ? .12 + depth * .22 : .3 + depth * .65 }
  if (atmosphere.kind === 'dust' || atmosphere.kind === 'fog') return { ...shared, x: ((baseX + travel * (18 + atmosphere.wind) + 10) % 120 + 120) % 120 - 10, y: baseY + Math.sin(seconds * atmosphere.speed + index * 2.1) * (atmosphere.kind === 'fog' ? 5 : 3), alpha: atmosphere.kind === 'fog' ? .1 + depth * .16 : .14 + depth * .32 }
  if (atmosphere.kind === 'fireflies' || atmosphere.kind === 'bokeh' || atmosphere.kind === 'sparkles') return { ...shared, x: baseX + Math.sin(seconds * atmosphere.speed * 2 + index) * (2 + atmosphere.wind * .05), y: baseY + Math.cos(seconds * atmosphere.speed * 1.7 + index * 1.8) * 3, alpha: pulse * (atmosphere.kind === 'bokeh' ? .28 : .85) }
  if (atmosphere.kind === 'speedlines') return { ...shared, x: -10 + travel * 120, y: baseY, alpha: .18 + depth * .58 }
  return { ...shared, x: baseX + wind + (atmosphere.kind === 'snow' || atmosphere.kind === 'ash' || atmosphere.kind === 'leaves' ? Math.sin(seconds * 1.2 + index) * 2.8 : 0), y: -10 + travel * 120, alpha: atmosphere.kind === 'rain' ? .28 + depth * .55 : atmosphere.kind === 'ash' ? .18 + depth * .45 : .35 + depth * .65 }
})
export const drawAtmosphere = (context: CanvasRenderingContext2D, atmosphere: Atmosphere, seconds: number, width: number, height: number) => {
  const shortSide = Math.min(width, height)
  const confettiPalette = ['#f472b6', '#60a5fa', '#facc15', '#34d399', '#c084fc', '#fb7185']
  const leafPalette = ['#f59e0b', '#dc2626', '#84cc16', '#d97706', '#a16207', '#fbbf24']
  for (const particle of atmosphereParticles(atmosphere, seconds)) {
    const x = -width / 2 + width * particle.x / 100
    const y = -height / 2 + height * particle.y / 100
    const color = atmosphere.kind === 'confetti' ? confettiPalette[particle.variant] : atmosphere.kind === 'leaves' ? leafPalette[particle.variant] : atmosphere.color
    context.save()
    context.globalAlpha *= particle.alpha
    context.fillStyle = color
    context.strokeStyle = color
    context.lineCap = 'round'
    if (atmosphere.kind === 'rain') {
      context.lineWidth = Math.max(1, shortSide * particle.size / 520)
      context.beginPath(); context.moveTo(x, y); context.lineTo(x + atmosphere.wind * width / 1900, y + height * particle.size / 30); context.stroke()
    } else if (atmosphere.kind === 'fog' || atmosphere.kind === 'smoke') {
      const radius = shortSide * particle.size / (atmosphere.kind === 'fog' ? 8 : 11)
      const gradient = context.createRadialGradient(x, y, 0, x, y, radius)
      gradient.addColorStop(0, color)
      gradient.addColorStop(.45, withAlpha(color, '88'))
      gradient.addColorStop(1, withAlpha(color, '00'))
      context.fillStyle = gradient
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
    } else if (atmosphere.kind === 'fireflies' || atmosphere.kind === 'embers') {
      const radius = Math.max(1, shortSide * particle.size / 420)
      context.shadowColor = color; context.shadowBlur = radius * (atmosphere.kind === 'fireflies' ? 7 : 4)
      context.globalAlpha *= atmosphere.kind === 'fireflies' ? particle.pulse : 1
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
    } else if (atmosphere.kind === 'confetti') {
      const unit = shortSide * particle.size / 270
      context.translate(x, y); context.rotate(particle.rotation * Math.PI / 180)
      context.fillRect(-unit / 2, -unit * 1.4, unit, unit * 2.8)
    } else if (atmosphere.kind === 'bokeh') {
      const radius = shortSide * particle.size / 42
      context.lineWidth = Math.max(1, radius * .08)
      context.globalAlpha *= particle.pulse
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
      context.globalAlpha *= .8; context.strokeStyle = '#ffffff'; context.stroke()
    } else if (atmosphere.kind === 'sparkles') {
      const radius = shortSide * particle.size * particle.pulse / 135
      context.shadowColor = color; context.shadowBlur = radius * 2
      context.lineWidth = Math.max(1, radius * .14)
      context.beginPath(); context.moveTo(x - radius, y); context.lineTo(x + radius, y); context.moveTo(x, y - radius); context.lineTo(x, y + radius); context.stroke()
    } else if (atmosphere.kind === 'bubbles') {
      const radius = shortSide * particle.size / 145
      context.lineWidth = Math.max(1, radius * .16)
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.stroke()
      context.globalAlpha *= .65; context.fillStyle = '#ffffff'; context.beginPath(); context.arc(x - radius * .32, y - radius * .3, radius * .16, 0, Math.PI * 2); context.fill()
    } else if (atmosphere.kind === 'speedlines') {
      const length = width * particle.size / 9
      context.lineWidth = Math.max(1, shortSide * particle.size / 480)
      context.beginPath(); context.moveTo(x - length, y - atmosphere.wind * height / 3500); context.lineTo(x, y); context.stroke()
    } else if (atmosphere.kind === 'leaves') {
      const radius = shortSide * particle.size / 180
      context.translate(x, y); context.rotate(particle.rotation * Math.PI / 180)
      context.beginPath(); context.ellipse(0, 0, radius, radius * .48, 0, 0, Math.PI * 2); context.fill()
      context.strokeStyle = '#78350f'; context.lineWidth = Math.max(.5, radius * .08); context.beginPath(); context.moveTo(-radius, 0); context.lineTo(radius, 0); context.stroke()
    } else {
      const radius = Math.max(.8, shortSide * particle.size / (atmosphere.kind === 'dust' ? 330 : atmosphere.kind === 'ash' ? 520 : 470))
      context.beginPath(); context.arc(x, y, radius, 0, Math.PI * 2); context.fill()
    }
    context.restore()
  }
}
export const stripOffsets = (layer: AnimatorLayer, sceneSeconds: number) => {
  const strip = normalizedStrip(layer.strip)
  if (!strip.enabled || strip.count <= 1) return [{ x: 0, y: 0 }]
  const period = strip.count * strip.spacing
  const sign = strip.direction === 'up' || strip.direction === 'left' ? -1 : 1
  const travel = sign * (strip.phase + sceneSeconds * strip.speed)
  const wrap = (value: number) => ((value + period / 2) % period + period) % period - period / 2
  return Array.from({ length: strip.count }, (_, index) => {
    const offset = wrap((index - (strip.count - 1) / 2) * strip.spacing + travel)
    return strip.direction === 'up' || strip.direction === 'down' ? { x: 0, y: offset } : { x: offset, y: 0 }
  })
}
export const effectFilter = (effects: LayerEffects, pixelUnit: number) => {
  const filters = [`brightness(${effects.brightness})`, `contrast(${effects.contrast})`, `saturate(${effects.saturation})`, `hue-rotate(${effects.hue}deg)`]
  if (effects.blur > 0) filters.unshift(`blur(${(effects.blur * pixelUnit).toFixed(2)}px)`)
  if (effects.glow > 0) filters.push(`drop-shadow(0 0 ${(effects.glow * pixelUnit).toFixed(2)}px rgba(96,165,250,.9))`)
  if (effects.shadow > 0) filters.push(`drop-shadow(0 ${(effects.shadow * pixelUnit * .35).toFixed(2)}px ${(effects.shadow * pixelUnit * .7).toFixed(2)}px rgba(0,0,0,.8))`)
  return filters.join(' ')
}
export const hasCanvasFilterEffects = (effects: LayerEffects) => effects.blur > 0 || effects.glow > 0 || effects.shadow > 0 || effects.brightness !== 1 || effects.contrast !== 1 || effects.saturation !== 1 || effects.hue !== 0
export const applyLayerMask = (context: CanvasRenderingContext2D, effects: LayerEffects, width: number, height: number) => {
  context.beginPath()
  if (effects.mask === 'none') context.rect(-width / 2, -height / 2, width, height)
  else if (effects.mask === 'ellipse') context.ellipse(0, 0, width / 2, height / 2, 0, 0, Math.PI * 2)
  else {
    const x = -width / 2; const y = -height / 2; const radius = Math.min(width, height) * effects.maskRadius / 100
    context.moveTo(x + radius, y); context.lineTo(x + width - radius, y); context.arcTo(x + width, y, x + width, y + radius, radius)
    context.lineTo(x + width, y + height - radius); context.arcTo(x + width, y + height, x + width - radius, y + height, radius)
    context.lineTo(x + radius, y + height); context.arcTo(x, y + height, x, y + height - radius, radius)
    context.lineTo(x, y + radius); context.arcTo(x, y, x + radius, y, radius)
  }
  context.closePath(); context.clip()
}
export const isVisualLayer = (layer: AnimatorLayer): layer is VisualAnimatorLayer => layer.type !== 'camera'
