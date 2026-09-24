import { fxRandom } from './types'
import { glow, ring, star, strokeEnergy, TAU, type FxPainter } from './energyBrush'

const aura: FxPainter = (ctx, cue, time, progress) => {
  ctx.globalAlpha = Math.min(1, progress * 6, (1 - progress) * 5); ctx.globalCompositeOperation = 'screen'
  ctx.save(); ctx.scale(.65, 1.05); glow(ctx, cue.color, .55, .3)
  for (let layer = 0; layer < 4; layer++) {
    ctx.beginPath()
    for (let i = 0; i <= 96; i++) {
      const a = i / 96 * TAU, pulse = Math.sin(a * 13 - time * 7 + layer) * .045
      const r = .28 + layer * .035 + pulse * cue.intensity, x = Math.cos(a) * r, y = Math.sin(a) * r
      if (!i) ctx.moveTo(x, y); else ctx.lineTo(x, y)
    }
    strokeEnergy(ctx, cue.color, .008 - layer * .001)
  }
  ctx.restore(); ctx.fillStyle = '#ffffe8'
  for (let i = 0; i < 35; i++) {
    const phase = (time * .65 + fxRandom(cue.seed, i)) % 1
    star(ctx, (fxRandom(cue.seed, i + 100) - .5) * .55, .38 - phase * .9, .008 * Math.sin(phase * Math.PI))
  }
}
const orb: FxPainter = (ctx, cue, time, progress) => {
  ctx.globalCompositeOperation = 'screen'; ctx.globalAlpha = Math.min(1, progress * 6, (1 - progress) * 6)
  const size = .12 + .12 * Math.min(1, progress * 2)
  glow(ctx, cue.color, size * 2.1)
  for (let i = 0; i < 4; i++) { ctx.save(); ctx.rotate(time * (i % 2 ? 1 : -1) + i); ctx.scale(1, .32); ctx.strokeStyle = cue.color; ring(ctx, size * 1.3, .008); ctx.restore() }
  ctx.fillStyle = '#ffffff'; star(ctx, 0, 0, size * .5)
  for (let i = 0; i < 25; i++) {
    const a = i * 2.4, phase = (time * .5 + i * .137) % 1, r = .6 * (1 - phase)
    ctx.globalAlpha = Math.sin(phase * Math.PI); ctx.beginPath(); ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r)
    ctx.lineTo(Math.cos(a) * (r + .06), Math.sin(a) * (r + .06)); strokeEnergy(ctx, cue.color, .004)
  }
}
const beam: FxPainter = (ctx, cue, time, progress) => {
  ctx.globalCompositeOperation = 'screen'; ctx.globalAlpha = Math.min(1, progress * 8, (1 - progress) * 5)
  const width = (.055 + Math.sin(time * 20) * .007) * cue.intensity
  const gradient = ctx.createLinearGradient(0, -width * 3, 0, width * 3)
  gradient.addColorStop(0, cue.color + '00'); gradient.addColorStop(.35, cue.color); gradient.addColorStop(.5, '#ffffff'); gradient.addColorStop(.65, cue.color); gradient.addColorStop(1, cue.color + '00')
  ctx.fillStyle = gradient; ctx.fillRect(-.32, -width * 3, 1.25, width * 6)
  for (let i = 0; i < 5; i++) {
    ctx.save(); ctx.translate(-.3 + ((time * 1.2 + i / 5) % 1) * 1.1, 0); ctx.scale(.28, 1); ctx.strokeStyle = '#ffffff'; ring(ctx, width * 1.7, .003); ctx.restore()
  }
  ctx.save(); ctx.translate(-.32, 0); glow(ctx, cue.color, .24); ctx.restore()
}
const slash: FxPainter = (ctx, cue, _time, progress) => {
  ctx.rotate(-.5); ctx.globalAlpha = Math.sin(Math.PI * progress); ctx.globalCompositeOperation = 'screen'
  for (let i = 0; i < 3; i++) {
    ctx.beginPath(); ctx.moveTo(-.65, .18 + i * .035); ctx.bezierCurveTo(-.15, -.25, .28, .2, .7, -.2 - i * .035)
    strokeEnergy(ctx, cue.color, (.025 - i * .007) * cue.intensity)
  }
  ctx.fillStyle = '#ffffff'; star(ctx, -.1 + progress * .35, 0, .12 * Math.sin(progress * Math.PI))
}
const impact: FxPainter = (ctx, cue, _time, progress) => {
  ctx.globalAlpha = Math.min(1, (1 - progress) * 3); const reach = .12 + Math.pow(progress, .4) * .48
  for (let i = 0; i < 28; i++) {
    const a = i * TAU / 28, r = reach * (.55 + fxRandom(cue.seed, i) * .7)
    ctx.save(); ctx.rotate(a); ctx.beginPath(); ctx.moveTo(.07, -.008); ctx.lineTo(r, -.025); ctx.lineTo(r * .8, .022); ctx.closePath()
    ctx.fillStyle = i % 3 ? cue.color : '#ffffff'; ctx.fill(); ctx.strokeStyle = '#11121b'; ctx.lineWidth = .002; ctx.stroke(); ctx.restore()
  }
  ctx.fillStyle = '#ffffff'; star(ctx, 0, 0, .11 * (1 - progress)); ctx.strokeStyle = cue.color; ring(ctx, reach * .6, .016 * (1 - progress))
}
export const animePainters: Record<string, FxPainter> = { anime_aura: aura, energy_orb: orb, energy_beam: beam, sword_slash: slash, manga_impact: impact }
