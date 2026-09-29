// The "tiling" scene graphic: a dark tiling-window-manager desktop (top bar, gapped windows with thin
// borders, editor, terminal, monitor). Full frame, deterministic in `seconds`, drawn with rects and text only.
import themes from '../../../../app/shared/omarchy_themes.json' with { type: 'json' }

export type DesktopParams = Record<string, number | string>
type Theme = Record<string, string>
type Rect = { x: number; y: number; w: number; h: number }
type App = 'nvim' | 'terminal' | 'btop' | 'fetch'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const ease = (t: number) => 1 - Math.pow(1 - clamp(t, 0, 1), 3)
const MONO = 'ui-monospace, "JetBrains Mono", "DejaVu Sans Mono", monospace'
const ALL = themes.entries as unknown as Record<string, Theme>

const APPS: Record<string, App[]> = {
  dev: ['nvim', 'terminal', 'terminal', 'nvim'],
  system: ['btop', 'fetch', 'terminal', 'btop'],
  mixed: ['nvim', 'btop', 'terminal', 'fetch'],
}

const CONFIG = [
  '# ~/.config/hypr/bindings.conf', 'bind = SUPER, RETURN, exec, $terminal', 'bind = SUPER, SPACE, exec, walker',
  'bind = SUPER, W, killactive', 'bind = SUPER, 1, workspace, 1', 'bind = SUPER SHIFT, 1, movetoworkspace, 1',
  'general {', '  gaps_in = 5', '  gaps_out = 10', '  border_size = 2', '}',
]
const SHELL = (name: string) => [
  ['❯ omarchy-theme-set "' + name + '"', 'fg'], ['✓ theme applied', 'green'], ['❯ git commit -m "beautiful by default"', 'fg'],
  ['[main 3f2a1c9] beautiful by default', 'dim'], ['❯ keyboard --first', 'fg'], ['ok: every action has a shortcut', 'green'], ['❯ ', 'fg'],
] as const
const PROCS = [['hyprland', 3.2], ['alacritty', 1.4], ['nvim', 0.9], ['waybar', 0.6], ['pipewire', 0.4]] as const

export function paintTilingDesktop(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, beat: number, beats: Record<string, number>, params: DesktopParams) {
  const theme = ALL[String(params.theme)] ?? ALL['tokyo-night']
  const unit = height / 1080
  const gap = Math.round(10 * unit)
  const barH = Math.round(38 * unit)
  const font = Math.max(9, Math.round(22 * unit))
  const stagger = beats.stagger ?? 0.5
  const typing = beats.type ?? 3
  ctx.save()
  ctx.fillStyle = theme.wall
  ctx.fillRect(0, 0, width, height)
  paintBar(ctx, theme, width, barH, font, Number(params.workspace), seconds)
  const area: Rect = { x: gap, y: barH + gap, w: width - 2 * gap, h: height - barH - 2 * gap }
  const slots = layout(String(params.layout), area, gap)
  const apps = APPS[String(params.apps)] ?? APPS.mixed
  const shift = slide(String(params.switch), beat, width)
  ctx.beginPath()
  ctx.rect(0, barH, width, height - barH)
  ctx.clip()
  slots.forEach((rect, index) => {
    const opened = clamp((beat - index * stagger) / 0.35, 0, 1)
    if (opened <= 0) return
    const typed = clamp((beat - index * stagger - 0.25) / typing, 0, 1)
    const grow = 0.94 + 0.06 * ease(opened)
    const cx = rect.x + rect.w / 2 + shift
    const cy = rect.y + rect.h / 2
    const box: Rect = { x: cx - rect.w * grow / 2, y: cy - rect.h * grow / 2, w: rect.w * grow, h: rect.h * grow }
    ctx.save()
    ctx.globalAlpha = ease(opened)
    paintWindow(ctx, theme, box, index === Number(params.focus) % slots.length, apps[index % apps.length], typed, seconds, font, unit, String(theme.name))
    ctx.restore()
  })
  ctx.restore()
}

function slide(direction: string, beat: number, width: number) {
  if (direction === 'none') return 0
  return (direction === 'left' ? -1 : 1) * width * (1 - ease(beat / 0.4))
}

function layout(kind: string, area: Rect, gap: number): Rect[] {
  const half = (area.w - gap) / 2
  const tall = (area.h - gap) / 2
  if (kind === 'single') return [area]
  if (kind === 'split') return [{ ...area, w: half }, { ...area, x: area.x + half + gap, w: half }]
  if (kind === 'quad') {
    return [0, 1, 2, 3].map(i => ({ x: area.x + (i % 2) * (half + gap), y: area.y + Math.floor(i / 2) * (tall + gap), w: half, h: tall }))
  }
  const masterW = kind === 'master' ? area.w * 0.6 : area.w * 0.55
  const restX = area.x + masterW + gap
  const restW = area.w - masterW - gap
  const count = kind === 'master' ? 3 : 2
  const rowH = (area.h - gap * (count - 1)) / count
  return [{ ...area, w: masterW }, ...Array.from({ length: count }, (_, i) => ({ x: restX, y: area.y + i * (rowH + gap), w: restW, h: rowH }))]
}

function text(ctx: CanvasRenderingContext2D, value: string, x: number, y: number, color: string, size: number, bold = false) {
  ctx.font = `${bold ? 700 : 400} ${size}px ${MONO}`
  ctx.fillStyle = color
  ctx.textAlign = 'left'
  ctx.textBaseline = 'middle'
  ctx.fillText(value, x, y)
}

function paintBar(ctx: CanvasRenderingContext2D, theme: Theme, width: number, barH: number, font: number, workspace: number, seconds: number) {
  ctx.fillStyle = theme.surface
  ctx.fillRect(0, 0, width, barH)
  const cell = barH * 0.95
  for (let index = 1; index <= 5; index += 1) {
    const active = index === workspace
    if (active) { ctx.fillStyle = theme.accent; ctx.fillRect(barH * 0.3 + (index - 1) * cell, barH * 0.16, cell * 0.8, barH * 0.68) }
    text(ctx, String(index), barH * 0.3 + (index - 1) * cell + cell * 0.28, barH / 2, active ? theme.wall : theme.dim, font * 0.85, active)
  }
  const minutes = 9 * 60 + 41 + Math.floor(seconds / 60)
  const clock = `${String(Math.floor(minutes / 60) % 24).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`
  text(ctx, clock, width / 2 - font * 1.4, barH / 2, theme.fg, font * 0.9, true)
  const right = `cpu ${Math.round(9 + 4 * Math.sin(seconds * 1.7))}%   mem 41%   bat 87%`
  text(ctx, right, width - right.length * font * 0.55 - barH * 0.4, barH / 2, theme.dim, font * 0.85)
}

function paintWindow(ctx: CanvasRenderingContext2D, theme: Theme, box: Rect, focused: boolean, app: App, typed: number, seconds: number, font: number, unit: number, themeName: string) {
  const border = Math.max(1, Math.round(2 * unit))
  ctx.fillStyle = focused ? theme.accent : theme.border
  ctx.fillRect(box.x, box.y, box.w, box.h)
  ctx.fillStyle = theme.bg
  ctx.fillRect(box.x + border, box.y + border, box.w - 2 * border, box.h - 2 * border)
  ctx.save()
  ctx.beginPath()
  ctx.rect(box.x + border, box.y + border, box.w - 2 * border, box.h - 2 * border)
  ctx.clip()
  const pad = font * 0.8
  const inner: Rect = { x: box.x + border + pad, y: box.y + border + pad * 0.8, w: box.w - 2 * (border + pad), h: box.h - 2 * (border + pad * 0.8) }
  if (app === 'nvim') paintNvim(ctx, theme, inner, typed, font, seconds)
  else if (app === 'terminal') paintTerminal(ctx, theme, inner, typed, font, seconds, themeName)
  else if (app === 'btop') paintBtop(ctx, theme, inner, typed, font, seconds)
  else paintFetch(ctx, theme, inner, typed, font, themeName)
  ctx.restore()
}

function cursor(ctx: CanvasRenderingContext2D, theme: Theme, x: number, y: number, font: number, seconds: number) {
  if (Math.floor(seconds * 2) % 2 === 0) { ctx.fillStyle = theme.fg; ctx.fillRect(x, y - font * 0.55, font * 0.55, font * 1.1) }
}

function reveal(lines: readonly string[], typed: number) {
  const total = lines.reduce((sum, line) => sum + line.length + 1, 0)
  let left = Math.floor(total * clamp(typed * 1.15, 0, 1))
  return lines.map(line => { const shown = line.slice(0, Math.max(0, left)); left -= line.length + 1; return shown })
}

function paintNvim(ctx: CanvasRenderingContext2D, theme: Theme, box: Rect, typed: number, font: number, seconds: number) {
  const line = font * 1.32
  const rows = Math.max(1, Math.floor((box.h - line * 1.4) / line))
  const shown = reveal(CONFIG.slice(0, rows), typed)
  const gutter = font * 2.4
  const columns = Math.max(4, Math.floor((box.w - gutter) / (font * 0.6)))
  let last = 0
  shown.forEach((value, index) => {
    if (!value && index > 0 && !shown[index - 1]) return
    const y = box.y + line * (index + 0.5)
    text(ctx, String(index + 1).padStart(2, ' '), box.x, y, theme.dim, font)
    paintCode(ctx, theme, value.slice(0, columns), box.x + gutter, y, font)
    last = index
  })
  const y = box.y + line * (last + 0.5)
  cursor(ctx, theme, box.x + gutter + Math.min(columns, (shown[last] || '').length) * font * 0.6, y, font, seconds)
  const barY = box.y + box.h - line * 0.5
  ctx.fillStyle = theme.accent
  ctx.fillRect(box.x - font * 0.5, barY - line * 0.5, font * 5.6, line)
  text(ctx, 'NORMAL', box.x - font * 0.2, barY, theme.wall, font * 0.9, true)
  text(ctx, ' bindings.conf', box.x + font * 5.8, barY, theme.dim, font * 0.9)
}

function paintCode(ctx: CanvasRenderingContext2D, theme: Theme, value: string, x: number, y: number, font: number) {
  if (value.startsWith('#')) return text(ctx, value, x, y, theme.dim, font)
  let cursorX = x
  for (const token of value.split(/(\s+|[=,{}]+)/)) {
    if (!token) continue
    const color = /^(bind|general)$/.test(token) ? theme.blue : /^\$/.test(token) ? theme.magenta : /^\d+$/.test(token) ? theme.yellow : /^(SUPER|SHIFT|RETURN|SPACE)$/.test(token) ? theme.green : /^(exec|workspace|movetoworkspace|killactive)$/.test(token) ? theme.cyan : theme.fg
    text(ctx, token, cursorX, y, color, font)
    cursorX += token.length * font * 0.6
  }
}

function paintTerminal(ctx: CanvasRenderingContext2D, theme: Theme, box: Rect, typed: number, font: number, seconds: number, themeName: string) {
  const script = SHELL(themeName)
  const shown = reveal(script.map(([value]) => value), typed)
  const line = font * 1.32
  const columns = Math.max(4, Math.floor(box.w / (font * 0.6)))
  const rows = Math.max(1, Math.floor(box.h / line))
  const start = Math.max(0, script.length - rows)
  let last = 0
  script.slice(start).forEach(([, tone], index) => {
    const value = shown[start + index]
    if (!value) return
    text(ctx, value.slice(0, columns), box.x, box.y + line * (index + 0.5), value.startsWith('❯') ? theme.fg : theme[tone], font)
    if (value.startsWith('❯')) text(ctx, '❯', box.x, box.y + line * (index + 0.5), theme.green, font, true)
    last = index
  })
  cursor(ctx, theme, box.x + Math.min(columns, (shown[start + last] || '').length) * font * 0.6, box.y + line * (last + 0.5), font, seconds)
}

function paintBtop(ctx: CanvasRenderingContext2D, theme: Theme, box: Rect, typed: number, font: number, seconds: number) {
  const line = font * 1.32
  text(ctx, 'cpu', box.x, box.y + line * 0.5, theme.accent, font, true)
  const graphY = box.y + line
  const graphH = Math.max(line, box.h * 0.38)
  const bars = Math.max(6, Math.floor(box.w / (font * 0.7)))
  for (let index = 0; index < bars; index += 1) {
    const level = clamp(0.35 + 0.3 * Math.sin(seconds * 2.2 + index * 0.55) + 0.2 * Math.sin(seconds * 5 + index * 1.7), 0.05, 1) * clamp(typed * 3, 0, 1)
    ctx.fillStyle = level > 0.7 ? theme.red : level > 0.45 ? theme.yellow : theme.green
    ctx.fillRect(box.x + index * font * 0.7, graphY + graphH * (1 - level), font * 0.5, graphH * level)
  }
  const rowsTop = graphY + graphH + line * 0.4
  PROCS.slice(0, Math.max(0, Math.floor((box.y + box.h - rowsTop) / line))).forEach(([name, cpu], index) => {
    const y = rowsTop + line * (index + 0.5)
    if (typed < 0.3 + index * 0.1) return
    text(ctx, name.padEnd(12, ' '), box.x, y, theme.fg, font)
    text(ctx, (cpu + Math.sin(seconds * 3 + index)).toFixed(1).padStart(5, ' ') + '%', box.x + font * 8, y, theme.cyan, font)
  })
}

function paintFetch(ctx: CanvasRenderingContext2D, theme: Theme, box: Rect, typed: number, font: number, themeName: string) {
  const rows: Array<[string, string]> = [['OS', 'Omarchy'], ['WM', 'Hyprland'], ['Shell', 'bash'], ['Term', 'Alacritty'], ['Editor', 'Neovim'], ['Theme', themeName]]
  const line = font * 1.32
  text(ctx, 'omarchy@arch', box.x, box.y + line * 0.5, theme.accent, font, true)
  const shown = Math.floor(rows.length * clamp(typed * 1.3, 0, 1))
  rows.slice(0, Math.min(shown, Math.max(0, Math.floor(box.h / line) - 1))).forEach(([key, value], index) => {
    const y = box.y + line * (index + 1.5)
    text(ctx, key, box.x, y, theme.magenta, font, true)
    text(ctx, value, box.x + font * 5.4, y, theme.fg, font)
  })
}
