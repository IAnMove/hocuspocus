import { createVideoJsDocument, normalizeVideoJsScene } from './document.ts'
import type { VideoJsDocument } from './types.ts'

// Scene code below is data sent to the sandbox. Avoid template-literal
// placeholders inside it: they would be evaluated by the app, not the scene.

const TITLE = `return {
  render({ ctx, t, width, height, kit, frame }) {
    const { theme } = kit
    kit.draw.background(ctx, [theme.background, '#140f2e', theme.surface], { angle: 120 })
    kit.draw.grid(ctx, { spacing: height * 0.08, alpha: 0.05, offsetY: t * 12 })
    kit.draw.glow(ctx, width * 0.72, height * 0.35 + kit.wave(t, 0.12) * 40, height * 0.7, theme.primary, 0.45)
    kit.draw.glow(ctx, width * 0.2, height * 0.85, height * 0.5, theme.secondary, 0.25)
    const area = kit.layout.safe(0.09)
    const tag = kit.tween(t, 0.1, 0.6)
    kit.draw.roundRect(ctx, area.x, area.cy - height * 0.2, height * 0.26, height * 0.055, height * 0.03, { fill: kit.color.alpha(theme.primary, 0.25), alpha: tag })
    kit.draw.text(ctx, 'EXPERIMENTAL', area.x + height * 0.13, area.cy - height * 0.163, { size: height * 0.024, weight: 700, align: 'center', color: theme.text, letterSpacing: 4, alpha: tag })
    const title = kit.tween(t, 0.3, 0.9, 'outExpo')
    kit.draw.text(ctx, 'Video JS', area.x, area.cy + height * 0.02 + (1 - title) * 50, { size: height * 0.16, weight: 900, family: theme.display, alpha: title, shadow: { blur: 40, y: 12 } })
    const sub = kit.tween(t, 0.8, 0.8)
    kit.draw.text(ctx, 'Videos written as code, directed with words', area.x, area.cy + height * 0.12, { size: height * 0.042, color: theme.muted, alpha: sub, maxWidth: area.w * 0.7 })
    kit.draw.line(ctx, area.x, area.cy + height * 0.19, area.x + width * 0.22, area.cy + height * 0.19, { color: theme.accent, width: height * 0.006, progress: kit.tween(t, 1.1, 0.9, 'inOutCubic') })
    kit.draw.vignette(ctx, 0.5)
    kit.draw.grain(ctx, { amount: 0.05, seed: frame })
  },
}`

const HOW = `return {
  render({ ctx, t, width, height, kit }) {
    const { theme } = kit
    kit.draw.background(ctx, [theme.surface, theme.background], { angle: 70 })
    const area = kit.layout.safe(0.08)
    const head = kit.tween(t, 0.1, 0.7, 'outExpo')
    kit.draw.text(ctx, 'How it works', area.x, area.y + height * 0.1, { size: height * 0.075, weight: 800, family: theme.display, alpha: head })
    const steps = [['1', 'Describe', 'Ask the LLM for a video'], ['2', 'Review', 'Scenes render live as code'], ['3', 'Adjust', 'Refine one scene or all'], ['4', 'Export', 'Deterministic MP4']]
    const columns = width > height ? 4 : 2
    const cells = kit.layout.grid({ x: area.x, y: area.y + height * 0.24, w: area.w, h: columns === 4 ? height * 0.4 : area.h * 0.5 }, columns, Math.ceil(steps.length / columns), height * 0.03)
    steps.forEach((step, index) => {
      const cell = cells[index]
      const enter = kit.stagger(t, index, { start: 0.5, each: 0.18, duration: 0.7, ease: 'outBack' })
      const lift = (1 - enter) * height * 0.06
      kit.draw.roundRect(ctx, cell.x, cell.y + lift, cell.w, cell.h, height * 0.025, { fill: kit.color.alpha(theme.text, 0.06), stroke: kit.color.alpha(theme.text, 0.12), lineWidth: 2, alpha: enter })
      kit.draw.circle(ctx, cell.x + cell.w * 0.18, cell.y + lift + cell.h * 0.22, height * 0.035, { fill: [theme.primary, theme.secondary, theme.accent, theme.primary][index], alpha: enter })
      kit.draw.text(ctx, step[0], cell.x + cell.w * 0.18, cell.y + lift + cell.h * 0.22 + height * 0.013, { size: height * 0.035, weight: 800, align: 'center', alpha: enter })
      kit.draw.text(ctx, step[1], cell.x + cell.w * 0.1, cell.y + lift + cell.h * 0.52, { size: height * 0.045, weight: 700, family: theme.display, alpha: enter })
      kit.draw.text(ctx, step[2], cell.x + cell.w * 0.1, cell.y + lift + cell.h * 0.66, { size: height * 0.027, color: theme.muted, maxWidth: cell.w * 0.8, alpha: enter })
    })
  },
}`

const DATA = `return {
  render({ ctx, t, width, height, kit }) {
    const { theme } = kit
    kit.draw.background(ctx, theme.background)
    kit.draw.glow(ctx, width * 0.15, height * 0.2, height * 0.6, theme.secondary, 0.2)
    const area = kit.layout.safe(0.08)
    const count = kit.tween(t, 0.3, 1.8, 'outExpo')
    kit.draw.text(ctx, kit.text.number(100 * count, { suffix: '%' }), area.x, area.y + height * 0.2, { size: height * 0.14, weight: 900, family: theme.display, color: theme.secondary })
    kit.draw.text(ctx, 'of every frame is reproducible', area.x, area.y + height * 0.28, { size: height * 0.035, color: theme.muted, alpha: kit.tween(t, 0.6, 0.6) })
    const chart = width > height
      ? { x: area.x + area.w * 0.45, y: area.y + height * 0.05, w: area.w * 0.55, h: area.h * 0.9 }
      : { x: area.x, y: area.y + area.h * 0.4, w: area.w, h: area.h * 0.55 }
    kit.draw.barChart(ctx, [{ label: 'Intro', value: 3 }, { label: 'Points', value: 7 }, { label: 'Data', value: 5 }, { label: 'Outro', value: 4 }], chart, { t, start: 0.8, each: 0.15 })
  },
}`

const ORBIT = `return {
  setup({ THREE, scene, kit }) {
    kit.three.studioLights(scene, { intensity: 1.1 })
    const group = new THREE.Group()
    const core = new THREE.Mesh(new THREE.IcosahedronGeometry(1.1, 1), new THREE.MeshStandardMaterial({ color: kit.theme.primary, metalness: 0.6, roughness: 0.2, flatShading: true }))
    group.add(core)
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2, 0.04, 16, 160), new THREE.MeshStandardMaterial({ color: kit.theme.secondary, emissive: kit.theme.secondary, emissiveIntensity: 0.6 }))
    ring.rotation.x = Math.PI / 2.4
    group.add(ring)
    const rand = kit.random('orbit')
    const dots = []
    for (let i = 0; i < 40; i += 1) {
      const dot = new THREE.Mesh(new THREE.SphereGeometry(0.05 + rand() * 0.05, 12, 12), new THREE.MeshStandardMaterial({ color: kit.theme.accent, emissive: kit.theme.accent, emissiveIntensity: 0.8 }))
      dots.push({ mesh: dot, radius: 2.6 + rand() * 1.4, phase: rand(), speed: 0.05 + rand() * 0.08, lift: rand() * 2 - 1 })
      group.add(dot)
    }
    scene.add(group)
    scene.fog = new THREE.Fog(kit.theme.background, 6, 14)
    return { core, ring, dots }
  },
  render({ t, camera, state, kit }) {
    state.core.rotation.set(t * 0.3, t * 0.45, 0)
    state.ring.rotation.z = t * 0.2
    for (const dot of state.dots) {
      const angle = (dot.phase + t * dot.speed) * kit.TAU
      dot.mesh.position.set(Math.cos(angle) * dot.radius, dot.lift + Math.sin(angle * 2) * 0.2, Math.sin(angle) * dot.radius)
    }
    kit.three.orbit(camera, t, { radius: 7 - kit.tween(t, 0, 5, 'inOutSine') * 1.5, height: 1.4, speed: 0.04 })
  },
  overlay({ ctx, t, width, height, kit }) {
    const area = kit.layout.safe(0.07)
    const enter = kit.tween(t, 0.6, 0.8, 'outExpo')
    kit.draw.text(ctx, '3D scenes with three.js', area.x, area.bottom - height * 0.06, { size: height * 0.06, weight: 800, family: kit.theme.display, alpha: enter, shadow: { blur: 30, y: 6 } })
    kit.draw.text(ctx, '2D overlays stay crisp on top', area.x, area.bottom, { size: height * 0.03, color: kit.theme.muted, alpha: enter })
  },
}`

const OUTRO = `return {
  render({ ctx, t, p, width, height, kit, frame }) {
    const { theme } = kit
    kit.draw.background(ctx, [theme.primary, '#2a1b6e', theme.background], { angle: 160 })
    const pulse = 0.5 + kit.wave(t, 0.5) * 0.5
    kit.draw.glow(ctx, width / 2, height / 2, height * (0.5 + pulse * 0.1), theme.accent, 0.35)
    const enter = kit.tween(t, 0.2, 0.9, 'outBack')
    const size = kit.text.fit(ctx, 'Now describe yours', width * 0.84, height * 0.11, { weight: 900 })
    kit.draw.text(ctx, 'Now describe yours', width / 2, height / 2 + (1 - enter) * 40, { size, weight: 900, family: theme.display, align: 'center', alpha: kit.math.clamp(enter), shadow: { blur: 40, y: 10 } })
    kit.draw.progressBar(ctx, width * 0.3, height * 0.62, width * 0.4, height * 0.012, p)
    kit.draw.grain(ctx, { amount: 0.05, seed: frame })
  },
}`

export function videoJsExampleDocument(): VideoJsDocument {
  const scenes = [
    { id: 'demo-title', title: 'Title', kind: '2d', duration: 4, transition: 'none', code: TITLE },
    { id: 'demo-how', title: 'How it works', kind: '2d', duration: 5, transition: 'slide-left', code: HOW },
    { id: 'demo-data', title: 'Data', kind: '2d', duration: 4.5, transition: 'fade', code: DATA },
    { id: 'demo-3d', title: '3D showcase', kind: '3d', duration: 5, transition: 'zoom', code: ORBIT },
    { id: 'demo-outro', title: 'Call to action', kind: '2d', duration: 3.5, transition: 'wipe', code: OUTRO },
  ].map((scene, index) => normalizeVideoJsScene({ ...scene, transitionDuration: 0.6 }, index))
  return createVideoJsDocument({ title: 'Video JS demo', scenes, prompt: 'Built-in demo presentation' })
}
