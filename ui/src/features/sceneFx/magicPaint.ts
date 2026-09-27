import { fxRandom } from './types'
import { withAlpha } from './color'
import { glow, ring, star, strokeEnergy, TAU, type FxPainter } from './energyBrush'

const magicCircle: FxPainter = (ctx, cue, time, progress) => {
  ctx.globalAlpha = Math.min(1, progress * 8, (1 - progress) * 8)
  ctx.globalCompositeOperation = 'screen'; glow(ctx, cue.color, .62, .2)
  for (let layer = 0; layer < 3; layer++) {
    ctx.save(); ctx.rotate(time * (layer % 2 ? -.3 : .22)); ctx.strokeStyle = cue.color
    const r = .23 + layer * .095; ring(ctx, r); ring(ctx, r + .018, .0015)
    const count = 12 + layer * 6
    for (let i = 0; i < count; i++) {
      ctx.save(); ctx.rotate(i * TAU / count); ctx.translate(0, -r)
      ctx.beginPath(); ctx.moveTo(-.012, -.024); ctx.lineTo(.012, .024); ctx.moveTo(.012, -.018); ctx.lineTo(-.012, .018)
      ctx.moveTo(-.015, 0); ctx.lineTo(.015, 0); strokeEnergy(ctx, cue.color, .002); ctx.restore()
    }
    ctx.restore()
  }
  ctx.save(); ctx.rotate(-time * .2); ctx.beginPath()
  for (let triangle = 0; triangle < 2; triangle++) {
    for (let i = 0; i <= 3; i++) { const a = i * TAU / 3 + triangle * TAU / 6; const x = Math.cos(a) * .22, y = Math.sin(a) * .22; if (!i) ctx.moveTo(x, y); else ctx.lineTo(x, y) }
  }
  strokeEnergy(ctx, cue.color, .003); ctx.restore()
  ctx.fillStyle = '#fff5dd'; star(ctx, 0, 0, .045 + Math.sin(time * 3) * .01)
}
const missiles: FxPainter = (ctx, cue, time) => {
  ctx.globalCompositeOperation = 'screen'
  for (let i = 0; i < Math.round(7 * cue.intensity); i++) {
    const phase = (time * .45 + i * .137) % 1, a = i * 2.4 + time * .25
    const r = .58 * (1 - phase), x = Math.cos(a) * r, y = Math.sin(a) * r
    ctx.beginPath(); ctx.moveTo(Math.cos(a - .5) * (r + .18), Math.sin(a - .5) * (r + .18))
    ctx.quadraticCurveTo(x - Math.sin(a) * .15, y + Math.cos(a) * .15, x, y)
    ctx.globalAlpha = Math.sin(phase * Math.PI); strokeEnergy(ctx, cue.color, .012)
    ctx.save(); ctx.translate(x, y); glow(ctx, cue.color, .065); ctx.restore()
  }
  ctx.globalAlpha = .7; glow(ctx, cue.color, .12)
}
const gate: FxPainter = (ctx, cue, time, progress) => {
  ctx.save(); ctx.scale(.75, 1.12); magicCircle(ctx, cue, time, progress)
  ctx.globalCompositeOperation = 'source-over'; ctx.fillStyle = '#100321'
  ctx.beginPath(); ctx.arc(0, 0, .205, 0, TAU); ctx.fill()
  ctx.globalCompositeOperation = 'screen'; glow(ctx, cue.color, .22, .4)
  ctx.fillStyle = '#e5dcff'
  for (let i = 0; i < 45; i++) {
    const a = fxRandom(cue.seed, i) * TAU + time, r = .18 * ((time * .25 + fxRandom(cue.seed, i + 80)) % 1)
    star(ctx, Math.cos(a) * r, Math.sin(a) * r, .002 + r * .022)
  }
  ctx.restore()
}
const blackHole: FxPainter = (ctx, cue, time, progress) => {
  ctx.globalAlpha = Math.min(1, progress * 6, (1 - progress) * 6); ctx.globalCompositeOperation = 'screen'
  glow(ctx, cue.color, .52, .4)
  for (let arm = 0; arm < 5; arm++) {
    ctx.beginPath()
    for (let i = 0; i <= 65; i++) {
      const r = .095 + i / 65 * .36, a = arm * TAU / 5 + i * .1 - time * 1.2
      const x = Math.cos(a) * r, y = Math.sin(a) * r * .55
      if (!i) ctx.moveTo(x, y); else ctx.lineTo(x, y)
    }
    strokeEnergy(ctx, cue.color, .009)
  }
  ctx.globalCompositeOperation = 'source-over'; ctx.fillStyle = '#030108'; ctx.beginPath(); ctx.arc(0, 0, .095, 0, TAU); ctx.fill()
  ctx.strokeStyle = '#fff0c8'; ring(ctx, .102, .008)
}
const ice: FxPainter = (ctx, cue, _time, progress) => {
  const growth = Math.sin(Math.min(1, progress * 3) * Math.PI / 2)
  ctx.globalAlpha = Math.min(1, (1 - progress) * 4); glow(ctx, cue.color, .46, .35)
  for (let i = 0; i < 16; i++) {
    ctx.save(); ctx.rotate(i * TAU / 16); const reach = (.18 + fxRandom(cue.seed, i) * .3) * growth
    ctx.beginPath(); ctx.moveTo(-.025, 0); ctx.lineTo(0, -reach); ctx.lineTo(.038, -.06); ctx.closePath()
    ctx.fillStyle = withAlpha(cue.color, '70'); ctx.fill(); strokeEnergy(ctx, cue.color, .003)
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, -reach); ctx.stroke(); ctx.restore()
  }
}
const meteors: FxPainter = (ctx, cue, time) => {
  ctx.globalCompositeOperation = 'screen'
  for (let i = 0; i < Math.round(10 * cue.intensity); i++) {
    const p = (time * .6 + fxRandom(cue.seed, i)) % 1, x = fxRandom(cue.seed, i + 50) * 1.5 - .75 + p * .35, y = p * 1.4 - .7
    ctx.globalAlpha = Math.sin(p * Math.PI); ctx.beginPath(); ctx.moveTo(x - .13, y - .25); ctx.lineTo(x, y); strokeEnergy(ctx, cue.color, .012)
    ctx.save(); ctx.translate(x, y); glow(ctx, cue.color, .07); ctx.restore()
  }
}
export const magicPainters: Record<string, FxPainter> = { magic_circle: magicCircle, arcane_missiles: missiles, summoning_gate: gate, black_hole: blackHole, ice_burst: ice, meteor_shower: meteors }
