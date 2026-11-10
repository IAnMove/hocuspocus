/** What a window of a room looks onto while the room moves: a skin entry `{view: "road_night", speed_mps: 15}`.
 *  The picture is a pure function of the scene second painted on a canvas, so the drive is as smooth as the frame rate asks for (no 24 fps
 *  clip resampled to 30), never jumps where a clip would loop, and every streak carries the blur of a 1/60 s shutter. One canvas covers a whole
 *  wall, so the two side windows of a car show one continuous roadside with the pillar between them. */
import { hash2 } from './atmos/noise.ts'

export const ROOM_VIEWS = ['road_night', 'road_day', 'road_dawn', 'space'] as const
export type RoomView = (typeof ROOM_VIEWS)[number]
/** `front` looks along the way (the road comes toward us), `rear` back along it; `left` and `right` are the side walls seen from inside. */
export type ViewRole = 'front' | 'rear' | 'left' | 'right'

export const isRoomView = (value: unknown): value is RoomView => typeof value === 'string' && (ROOM_VIEWS as readonly string[]).includes(value)
export const DEFAULT_SPEED_MPS = 15
export const VIEW_WIDTH = 1024
/** The horizon sits this far down the wall (the eye of a seated person, 1.05 m of a 1.45 m cabin). */
export const HORIZON = 0.3
/** The metres between two road dashes, and the loop of the road: a whole number of dashes, so the road repeats seamlessly. */
const DASH_PITCH = 7, ROAD_LOOP = 140, SHUTTER = 1 / 60

export const viewSize = (span: number, height: number): [number, number] => [VIEW_WIDTH, Math.max(64, Math.min(1024, Math.round((VIEW_WIDTH * height) / span)))]
export const viewRole = (wall: string): ViewRole => (wall === 'left' || wall === 'right' ? wall : wall === 'front' ? 'rear' : 'front')

type Palette = { top: string; horizon: string; ground: string; hill: string; near: string; road: string; line: string; dash: string; stars: number; moon: boolean; lamp: string; sky: string }
const PALETTES: Record<Exclude<RoomView, 'space'>, Palette> = {
  road_night: { top: '#02050e', horizon: '#18233f', ground: '#07090e', hill: '#0b1322', near: '#04060b', road: '#14161c', line: '#a9aea9', dash: '#dcc25a', stars: 170, moon: true, lamp: '#ffcf7a', sky: '#8fb0ff' },
  road_day: { top: '#4f8fdb', horizon: '#d4e8fb', ground: '#46563a', hill: '#6c8e78', near: '#3e5a42', road: '#595c62', line: '#e8e8e4', dash: '#f0d060', stars: 0, moon: false, lamp: '#fff4d0', sky: '#ffffff' },
  road_dawn: { top: '#26376a', horizon: '#f2a977', ground: '#26283a', hill: '#4a4a68', near: '#2a2a40', road: '#3a3945', line: '#d9cfc2', dash: '#ead08a', stars: 36, moon: false, lamp: '#ffd9a0', sky: '#ffd7b0' },
}

const mod = (value: number, period: number) => ((value % period) + period) % period

function sky(ctx: CanvasRenderingContext2D, w: number, yH: number, p: Palette, seed: number) {
  const g = ctx.createLinearGradient(0, 0, 0, yH)
  g.addColorStop(0, p.top); g.addColorStop(1, p.horizon)
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, yH + 1)
  for (let i = 0; i < p.stars; i++) {
    const b = hash2(i, 3, seed)
    ctx.fillStyle = `rgba(255,255,255,${0.25 + 0.65 * b})`
    ctx.fillRect(Math.floor(hash2(i, 1, seed) * w), Math.floor(hash2(i, 2, seed) * yH * 0.92), b > 0.8 ? 2 : 1, b > 0.8 ? 2 : 1)
  }
  if (p.moon) {
    const mx = w * 0.82, my = yH * 0.42, glow = ctx.createRadialGradient(mx, my, 4, mx, my, yH * 0.5)
    glow.addColorStop(0, 'rgba(210,225,255,0.5)'); glow.addColorStop(1, 'rgba(210,225,255,0)')
    ctx.fillStyle = glow; ctx.fillRect(mx - yH, my - yH, yH * 2, yH * 2)
    ctx.fillStyle = '#eef2ff'; ctx.beginPath(); ctx.arc(mx, my, yH * 0.09, 0, Math.PI * 2); ctx.fill()
  }
}

function ridge(ctx: CanvasRenderingContext2D, w: number, yH: number, amp: number, phase: number, shift: number, colour: string) {
  ctx.fillStyle = colour; ctx.beginPath(); ctx.moveTo(0, yH + 2)
  for (let x = 0; x <= w; x += 8) {
    const u = x + shift
    ctx.lineTo(x, yH - amp * (0.55 + 0.25 * Math.sin(u * 0.006 + phase) + 0.12 * Math.sin(u * 0.017 + 2 * phase) + 0.08 * Math.sin(u * 0.041 + 3 * phase)))
  }
  ctx.lineTo(w, yH + 2); ctx.closePath(); ctx.fill()
}

/** The road comes toward the front windows (or leaves through the rear one): dashes, edge lines and posts in perspective, stretched by the shutter. */
function roadAhead(ctx: CanvasRenderingContext2D, w: number, h: number, t: number, p: Palette, role: ViewRole, speed: number, night: boolean) {
  const yH = h * HORIZON, drop = h - yH, vx = w / 2 + w * 0.045 * Math.sin(0.3 * t), K = 3 * drop, half = 1.55
  const sign = role === 'rear' ? 1 : -1
  ctx.fillStyle = p.ground; ctx.fillRect(0, yH, w, drop)
  ctx.fillStyle = p.road; ctx.beginPath(); ctx.moveTo(vx, yH); ctx.lineTo(vx - drop * half, h); ctx.lineTo(vx + drop * half, h); ctx.fill()
  ctx.strokeStyle = p.line; ctx.lineWidth = Math.max(2, w / 420)
  for (const s of [-1, 1]) { ctx.beginPath(); ctx.moveTo(vx, yH); ctx.lineTo(vx + s * drop * half * 0.93, h); ctx.stroke() }
  ctx.fillStyle = p.dash
  for (let k = 0; k < ROAD_LOOP / DASH_PITCH; k++) {
    const d = mod(k * DASH_PITCH + sign * speed * t, ROAD_LOOP) + 3, far = d + 2.4 + speed * SHUTTER
    const ya = yH + K / d, yb = yH + K / far, wa = 0.13 * (ya - yH) * half, wb = 0.13 * (yb - yH) * half
    ctx.beginPath(); ctx.moveTo(vx - wb, yb); ctx.lineTo(vx + wb, yb); ctx.lineTo(vx + wa, ya); ctx.lineTo(vx - wa, ya); ctx.fill()
  }
  const posts = Array.from({ length: ROAD_LOOP / 14 }, (_, k) => mod(k * 14 + sign * speed * t, ROAD_LOOP) + 4).sort((a, b) => b - a)
  for (const d of posts) for (const s of [-1, 1]) {
    const y = yH + K / d, size = y - yH, x = vx + s * size * half * 1.12, stretch = Math.max(0, speed * SHUTTER * K / (d * d))
    ctx.fillStyle = night ? '#15171c' : '#eef0ee'; ctx.fillRect(x - Math.max(1, size * 0.03), y - size * 0.5 - stretch, Math.max(2, size * 0.06), size * 0.5 + stretch)
    ctx.fillStyle = night ? '#e04a3a' : '#d8453a'; ctx.fillRect(x - Math.max(1, size * 0.03), y - size * 0.5 - stretch, Math.max(2, size * 0.06), Math.max(2, size * 0.09))
  }
  if (night && role === 'front') {                                                       // an oncoming car every eleven seconds, in the left lane, closing at 30 m/s
    const phase = mod(t + 3, 11), d = 170 - 30 * phase
    if (d > 4) {
      const y = yH + K / d, size = y - yH, x = vx - size * half * 0.45, r = Math.max(2, size * 0.16)
      for (const dx of [-0.22, 0.22]) {
        const cx = x + dx * size * half * 0.5, beam = ctx.createRadialGradient(cx, y - size * 0.05, 0, cx, y - size * 0.05, r * 3)
        beam.addColorStop(0, 'rgba(255,252,235,0.95)'); beam.addColorStop(0.3, 'rgba(255,240,200,0.4)'); beam.addColorStop(1, 'rgba(255,240,200,0)')
        ctx.fillStyle = beam; ctx.fillRect(cx - r * 3, y - size * 0.05 - r * 3, r * 6, r * 6)
      }
    }
    const pool = ctx.createRadialGradient(vx, h, 0, vx, h, w * 0.34)
    pool.addColorStop(0, 'rgba(255,238,190,0.2)'); pool.addColorStop(1, 'rgba(255,238,190,0)')
    ctx.fillStyle = pool; ctx.fillRect(0, yH, w, drop)
  }
}

/** The roadside seen from the side: slow hills, trees and lamp poles, a guard rail whose posts streak past. `dir` is the way the scenery goes on the canvas. */
function roadside(ctx: CanvasRenderingContext2D, w: number, h: number, t: number, p: Palette, role: ViewRole, speed: number, night: boolean, seed: number) {
  const yH = h * HORIZON, dir = role === 'left' ? -1 : 1, unit = h / 512
  const far = speed * 1.2, mid = speed * 9, near = speed * 55
  ridge(ctx, w, yH, 62 * unit, 0.7, dir * far * t, p.hill)
  ridge(ctx, w, yH + 8 * unit, 34 * unit, 2.1, dir * far * 2 * t, p.near)
  const g = ctx.createLinearGradient(0, yH, 0, h)
  g.addColorStop(0, p.ground); g.addColorStop(1, night ? '#1d222d' : p.road)
  ctx.fillStyle = g; ctx.fillRect(0, yH + 6 * unit, w, h - yH)
  if (night) for (let i = 0; i < 46; i++) {                                              // a far town: warm points along the horizon, drifting slowly
    const x = mod(hash2(i, 9, seed) * (w + 240) + dir * far * 5 * t, w + 240) - 120, lit = hash2(i, 10, seed)
    ctx.fillStyle = lit > 0.6 ? 'rgba(255,214,140,0.9)' : 'rgba(180,205,255,0.7)'; ctx.fillRect(x, yH + 1 + hash2(i, 11, seed) * 12 * unit, 2 * unit + 1, 2 * unit + 1)
  }
  const span = w + 240
  for (let i = 0; i < 12; i++) {                                                          // trees: a trunk and two crowns, seen against the sky
    const x = mod(i * 96 + hash2(i, 5, seed) * 40 + dir * mid * t, span) - 120, tall = (70 + hash2(i, 6, seed) * 80) * unit, base = yH + 14 * unit
    ctx.fillStyle = p.near; ctx.fillRect(x - 3 * unit, base - tall * 0.3, 6 * unit, tall * 0.3 + 4)
    ctx.beginPath(); ctx.moveTo(x - 30 * unit, base - tall * 0.25); ctx.lineTo(x, base - tall); ctx.lineTo(x + 30 * unit, base - tall * 0.25); ctx.fill()
    ctx.beginPath(); ctx.moveTo(x - 24 * unit, base - tall * 0.5); ctx.lineTo(x, base - tall * 1.12); ctx.lineTo(x + 24 * unit, base - tall * 0.5); ctx.fill()
  }
  for (let i = 0; i < 3; i++) {                                                           // lamp poles with a pool of light
    const x = mod(i * (span / 3) + dir * mid * 1.6 * t, span) - 120, top = yH - 52 * unit, base = h * 0.78
    ctx.fillStyle = '#0d0f14'; ctx.fillRect(x - 2 * unit, top, 4 * unit, base - top); ctx.fillRect(x - 2 * unit, top, 22 * unit, 4 * unit)
    if (night) {
      const glow = ctx.createRadialGradient(x + 20 * unit, top + 5 * unit, 0, x + 20 * unit, top + 5 * unit, 90 * unit)
      glow.addColorStop(0, p.lamp + 'cc'); glow.addColorStop(1, p.lamp + '00')
      ctx.fillStyle = glow; ctx.fillRect(x - 80 * unit, top - 80 * unit, 200 * unit, 200 * unit)
    }
  }
  const rail = h * 0.78, step = 96, shutter = near * SHUTTER                               // the guard rail and its posts
  ctx.fillStyle = night ? '#3b414e' : '#9aa0a6'; ctx.fillRect(0, rail, w, 9 * unit)
  ctx.fillStyle = night ? '#6a7386' : '#d4d8dc'; ctx.fillRect(0, rail, w, 2 * unit)
  for (let i = 0; i < Math.ceil((w + 240) / step); i++) {
    const x = mod(i * step + dir * near * t, w + 240) - 120, lit = i % 4 === 0
    const streak = ctx.createLinearGradient(x, 0, x - dir * shutter, 0)
    streak.addColorStop(0, night ? 'rgba(30,34,44,0.95)' : 'rgba(110,116,122,0.95)'); streak.addColorStop(1, 'rgba(30,34,44,0)')
    ctx.fillStyle = streak; ctx.fillRect(Math.min(x, x - dir * shutter), rail - 10 * unit, Math.abs(shutter) + 1, 46 * unit)
    ctx.fillStyle = night ? '#272b35' : '#7d848b'; ctx.fillRect(x - 5 * unit, rail - 10 * unit, 10 * unit, 46 * unit)
    ctx.fillStyle = night ? '#5c6578' : '#aab0b6'; ctx.fillRect(x - 5 * unit, rail - 10 * unit, 2 * unit, 46 * unit)
    if (lit) {
      ctx.fillStyle = '#ffb347'; ctx.fillRect(x - 4 * unit, rail - 6 * unit, 8 * unit, 6 * unit)
      if (night) { const glow = ctx.createRadialGradient(x, rail - 3 * unit, 0, x, rail - 3 * unit, 30 * unit); glow.addColorStop(0, 'rgba(255,179,71,0.55)'); glow.addColorStop(1, 'rgba(255,179,71,0)'); ctx.fillStyle = glow; ctx.fillRect(x - 30 * unit, rail - 33 * unit, 60 * unit, 60 * unit) }
    }
  }
  if (night) {                                                                           // an oncoming car every seven seconds: two headlights that cross the window at twice the roadside's speed
    const phase = mod(t + 2, 7), x0 = dir > 0 ? -160 : w + 160, x = x0 + dir * near * 2.2 * phase, y = h * 0.66
    if (x > -160 && x < w + 160) for (const dx of [-26, 26]) {
      const beam = ctx.createRadialGradient(x + dx, y, 0, x + dx, y, 60 * unit)
      beam.addColorStop(0, 'rgba(255,250,230,0.95)'); beam.addColorStop(0.25, 'rgba(255,240,200,0.45)'); beam.addColorStop(1, 'rgba(255,240,200,0)')
      ctx.fillStyle = beam; ctx.fillRect(x + dx - 70 * unit, y - 70 * unit, 140 * unit, 140 * unit)
    }
  }
  ctx.fillStyle = 'rgba(0,0,0,0.38)'; ctx.fillRect(0, rail + 30 * unit, w, h)             // the verge below the rail is in the car's own shadow
}

/** Stars stream out of the way ahead (windshield) or sideways past the hull (side ports): a ship at speed. */
function space(ctx: CanvasRenderingContext2D, w: number, h: number, t: number, role: ViewRole, speed: number, seed: number) {
  ctx.fillStyle = '#02030a'; ctx.fillRect(0, 0, w, h)
  const neb = ctx.createRadialGradient(w * 0.3, h * 0.35, 0, w * 0.3, h * 0.35, w * 0.45)
  neb.addColorStop(0, 'rgba(96,70,170,0.30)'); neb.addColorStop(1, 'rgba(96,70,170,0)')
  ctx.fillStyle = neb; ctx.fillRect(0, 0, w, h)
  const rate = speed / DEFAULT_SPEED_MPS
  for (let i = 0; i < 240; i++) {
    const b = 0.35 + 0.65 * hash2(i, 3, seed)
    ctx.strokeStyle = `rgba(215,228,255,${b})`; ctx.lineWidth = 1 + b
    if (role === 'front' || role === 'rear') {
      const a = hash2(i, 1, seed) * Math.PI * 2, reach = Math.hypot(w, h) * 0.55, cx = w / 2, cy = h * 0.45
      const phase = mod(hash2(i, 2, seed) + (role === 'rear' ? -1 : 1) * t * 0.22 * rate, 1)
      const r1 = phase * phase * reach, r0 = Math.max(0, (phase - 0.045 * rate) ** 2 * reach)
      ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r0, cy + Math.sin(a) * r0); ctx.lineTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); ctx.stroke()
    } else {
      const dir = role === 'left' ? -1 : 1, v = (60 + 420 * hash2(i, 4, seed)) * rate, x = mod(hash2(i, 1, seed) * w + dir * v * t, w + 80) - 40, y = hash2(i, 2, seed) * h
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - dir * v * SHUTTER, y); ctx.stroke()
    }
  }
  const planet = ctx.createRadialGradient(w * 0.74, h * 0.7, 6, w * 0.74, h * 0.7, h * 0.34)
  planet.addColorStop(0, '#c9b087'); planet.addColorStop(0.7, '#5b4a3a'); planet.addColorStop(1, 'rgba(20,14,10,0)')
  if (role === 'front' || role === 'rear') { ctx.fillStyle = planet; ctx.beginPath(); ctx.arc(w * 0.74, h * 0.7, h * 0.34, 0, Math.PI * 2); ctx.fill() }
}

/** Paint the view for scene second `t` over the whole canvas. */
export function drawRoomView(ctx: CanvasRenderingContext2D, w: number, h: number, t: number, view: RoomView, role: ViewRole, speed = DEFAULT_SPEED_MPS, seed = 5) {
  ctx.save(); ctx.clearRect(0, 0, w, h)
  if (view === 'space') space(ctx, w, h, t, role, speed, seed)
  else {
    const p = PALETTES[view], night = view !== 'road_day'
    sky(ctx, w, h * HORIZON, p, seed)
    if (role === 'left' || role === 'right') roadside(ctx, w, h, t, p, role, speed, night, seed)
    else { ridge(ctx, w, h * HORIZON, 55 * (h / 512), 0.7, 0, p.hill); ridge(ctx, w, h * HORIZON + 10, 85 * (h / 512), 2.1, 0, p.near); roadAhead(ctx, w, h, t, p, role, speed, night) }
  }
  ctx.restore()
}
