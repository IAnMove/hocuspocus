import {
  BackSide,
  BoxGeometry,
  CanvasTexture,
  CircleGeometry,
  Color,
  CylinderGeometry,
  Fog,
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  PointLight,
  SphereGeometry,
  SRGBColorSpace,
  TorusGeometry,
  type Object3D,
  type Scene,
} from 'three'
import type { Scene3DDressing } from './types.ts'

export const ACTION_DRESSINGS = ['open-sea', 'lunar', 'rooftop', 'hangar', 'desert', 'train', 'space-lane', 'jungle', 'snow', 'casino'] as const
export type ActionDressing = typeof ACTION_DRESSINGS[number]

export function isActionDressing(kind: Scene3DDressing | undefined): kind is ActionDressing {
  return kind === 'open-sea' || kind === 'lunar' || kind === 'rooftop' || kind === 'hangar'
    || kind === 'desert' || kind === 'train' || kind === 'space-lane'
    || kind === 'jungle' || kind === 'snow' || kind === 'casino'
}

const SKY: Record<ActionDressing, number> = {
  'open-sea': 0x79c4e8,
  lunar: 0x05060c,
  rooftop: 0x152038,
  hangar: 0x141820,
  desert: 0xe0b575,
  train: 0x2a3648,
  'space-lane': 0x03040a,
  jungle: 0x1a2e18,
  snow: 0xb8c8d8,
  casino: 0x120810,
}

function mat(color: number, extra?: { roughness?: number; metalness?: number; emissive?: number; opacity?: number }) {
  return new MeshStandardMaterial({
    color,
    roughness: extra?.roughness ?? 0.72,
    metalness: extra?.metalness ?? 0.18,
    emissive: extra?.emissive ?? 0,
    emissiveIntensity: extra?.emissive ? 0.55 : 0,
    transparent: extra?.opacity != null,
    opacity: extra?.opacity ?? 1,
  })
}

function glow(color: number) {
  return new MeshBasicMaterial({ color, toneMapped: false })
}

function addBox(
  root: Group,
  x: number, y: number, z: number,
  w: number, h: number, d: number,
  material: MeshStandardMaterial | MeshBasicMaterial,
) {
  const mesh = new Mesh(new BoxGeometry(w, h, d), material)
  mesh.position.set(x, y, z)
  root.add(mesh)
  return mesh
}

function canvas(width: number, height: number, paint: (ctx: CanvasRenderingContext2D) => void) {
  if (typeof document === 'undefined') return null
  const el = document.createElement('canvas')
  el.width = width
  el.height = height
  const ctx = el.getContext('2d')
  if (!ctx) return null
  paint(ctx)
  const texture = new CanvasTexture(el)
  texture.colorSpace = SRGBColorSpace
  return texture
}

function starDome(bg: string) {
  const texture = canvas(1024, 512, ctx => {
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, 1024, 512)
    for (let i = 0; i < 900; i++) {
      const y = (i * 41) % 512
      if (y > 300) continue
      ctx.fillStyle = `rgba(255,255,255,${0.35 + (i % 8) * 0.08})`
      ctx.fillRect((i * 73) % 1024, y, i % 11 === 0 ? 2 : 1, i % 11 === 0 ? 2 : 1)
    }
  })
  const mesh = new Mesh(
    new SphereGeometry(56, 32, 16, 0, Math.PI * 2, 0, Math.PI * 0.4),
    texture
      ? new MeshBasicMaterial({ map: texture, side: BackSide, depthWrite: false })
      : new MeshBasicMaterial({ color: 0x05060c, side: BackSide, depthWrite: false }),
  )
  mesh.name = 'star-dome'
  mesh.renderOrder = -2
  return mesh
}

export function actionGroup(kind: ActionDressing): Group {
  if (kind === 'open-sea') return seaGroup()
  if (kind === 'lunar') return lunarGroup()
  if (kind === 'rooftop') return rooftopGroup()
  if (kind === 'hangar') return hangarGroup()
  if (kind === 'desert') return desertGroup()
  if (kind === 'train') return trainGroup()
  if (kind === 'space-lane') return spaceLaneGroup()
  if (kind === 'jungle') return jungleGroup()
  if (kind === 'snow') return snowGroup()
  return casinoGroup()
}

export function applyActionAtmosphere(scene: Scene, kind: Scene3DDressing | undefined) {
  const floor = scene.getObjectByName('world-floor')
  if (floor) {
    floor.visible = !isActionDressing(kind)
    floor.position.y = isActionDressing(kind) ? -80 : 0
  }
  if (!isActionDressing(kind)) {
    scene.background = new Color(0x10141c)
    scene.fog = null
    return
  }
  scene.background = new Color(SKY[kind])
  if (kind === 'open-sea') scene.fog = new Fog(SKY[kind], 18, 90)
  else if (kind === 'desert') scene.fog = new Fog(SKY[kind], 16, 70)
  else if (kind === 'rooftop') scene.fog = new Fog(SKY[kind], 18, 80)
  else if (kind === 'train') scene.fog = new Fog(SKY[kind], 12, 48)
  else if (kind === 'jungle') scene.fog = new Fog(SKY[kind], 8, 28)
  else if (kind === 'snow') scene.fog = new Fog(SKY[kind], 12, 40)
  else if (kind === 'casino') scene.fog = new Fog(SKY[kind], 10, 32)
  else scene.fog = null
}

function seaGroup() {
  const root = new Group(); root.name = 'open-sea'
  const sky = new Mesh(
    new SphereGeometry(70, 24, 12, 0, Math.PI * 2, 0, Math.PI * 0.42),
    new MeshBasicMaterial({ color: 0x7ec7ea, side: BackSide, depthWrite: false }),
  )
  sky.renderOrder = -3
  root.add(sky)
  const ocean = new Mesh(new CircleGeometry(120, 48), mat(0x167ea8, { roughness: 0.28, metalness: 0.55 }))
  ocean.rotation.x = -Math.PI / 2
  ocean.position.y = -0.72
  root.add(ocean)
  const water = new Mesh(new PlaneGeometry(70, 70, 40, 40), mat(0x1a88b4, { roughness: 0.12, metalness: 0.62, opacity: 0.9 }))
  water.rotation.x = -Math.PI / 2
  water.position.y = -0.48
  water.name = 'sea-water'
  root.add(water)
  const foam = glow(0xd7eef8)
  for (let i = 0; i < 8; i++) {
    const strip = new Mesh(new BoxGeometry(6 + (i % 3), 0.02, 0.18), foam)
    strip.position.set(-18 + i * 5.2, -0.42, -2 + (i % 2) * 3)
    strip.name = 'sea-foam'
    root.add(strip)
  }
  const hull = mat(0x3a2a22, { roughness: 0.8 })
  const deck = mat(0x8a6a48, { roughness: 0.86 })
  const white = mat(0xe8e2d4, { roughness: 0.55 })
  const metal = mat(0x2a3340, { roughness: 0.4, metalness: 0.65 })
  addBox(root, 0, -0.28, 0, 4.4, 0.55, 12.4, hull)
  addBox(root, 0, -0.18, -6.4, 2.4, 0.42, 1.6, hull)
  addBox(root, 0, 0.02, 0, 4.2, 0.08, 12, deck)
  addBox(root, 0, 0.72, 2.4, 2.6, 1.3, 3.2, white)
  addBox(root, 0, 1.45, 2.2, 2.2, 0.18, 2.6, metal)
  addBox(root, 0, 0.95, 0.72, 2.1, 0.45, 0.08, mat(0x163048, { roughness: 0.12, metalness: 0.7, emissive: 0x1a4060 }))
  for (const z of [-5.4, -2, 1, 4.4]) {
    for (const x of [-2.05, 2.05]) addBox(root, x, 0.42, z, 0.05, 0.75, 0.05, metal)
  }
  for (const x of [-2.05, 2.05]) addBox(root, x, 0.78, 0, 0.04, 0.04, 11.4, metal)
  addBox(root, 0, 3.1, -1.6, 0.12, 6.2, 0.12, metal)
  addBox(root, 0, 4.6, -1.6, 0.04, 0.04, 3.8, metal)
  addBox(root, 0.02, 3.4, -2.4, 0.04, 3.4, 2.2, mat(0xf3ead4, { roughness: 0.9, opacity: 0.85 }))
  const pier = mat(0x6b4a2a, { roughness: 0.88 })
  addBox(root, 7.4, 0.04, 0, 8.4, 0.12, 4.2, pier)
  for (const z of [-1.8, 1.8]) {
    for (const x of [4.2, 7.4, 10.6]) addBox(root, x, -0.7, z, 0.22, 1.5, 0.22, pier)
  }
  addBox(root, 11.4, 0.55, 0, 0.12, 1.1, 4.2, metal)
  const rock = mat(0x2f4a38, { roughness: 0.95 })
  addBox(root, -22, 0.4, -28, 8, 2.2, 4, rock)
  addBox(root, 18, 0.8, -32, 6, 3.4, 3.2, rock)
  const sun = new PointLight(0xffe2a8, 22, 40, 2); sun.position.set(-8, 12, 6); root.add(sun)
  const fill = new PointLight(0x7ecbff, 10, 28, 2); fill.position.set(6, 5, 4); root.add(fill)
  return root
}

function lunarGroup() {
  const root = new Group(); root.name = 'lunar'
  root.add(starDome('#05060c'))
  const ground = new Mesh(new CircleGeometry(42, 48), mat(0x8a8680, { roughness: 0.96 }))
  ground.rotation.x = -Math.PI / 2
  root.add(ground)
  const rock = mat(0x6d6964, { roughness: 0.98 })
  for (const [x, y, z, r] of [
    [-4.2, 0.12, -3.1, 1.1], [5.1, 0.18, -2.4, 1.4], [2.2, 0.08, 4.6, 0.8],
    [-6.4, 0.22, 2.8, 1.6], [8.2, 0.3, 1.2, 2.1], [-1.2, 0.06, -6.4, 0.7],
    [0.8, 0.1, 6.8, 0.9], [-9, 0.4, -5, 2.4],
  ] as const) {
    const mesh = new Mesh(new IcosahedronGeometry(r, 0), rock)
    mesh.position.set(x, y, z)
    mesh.scale.y = 0.35
    root.add(mesh)
  }
  const habitat = mat(0xcfd4d8, { roughness: 0.45, metalness: 0.55 })
  addBox(root, 2.4, 0.7, -1.8, 2.6, 1.4, 2.2, habitat)
  const tank = new Mesh(new CylinderGeometry(0.55, 0.55, 1.8, 16), habitat)
  tank.rotation.z = Math.PI / 2
  tank.position.set(4.2, 0.55, -1.8)
  root.add(tank)
  addBox(root, 2.4, 1.55, -1.8, 1.1, 0.35, 1.1, mat(0xc9a15b, { roughness: 0.4, metalness: 0.6 }))
  addBox(root, -1.6, 1.1, 1.4, 0.05, 2.2, 0.05, habitat)
  addBox(root, -1.15, 1.85, 1.4, 0.85, 0.5, 0.02, glow(0x3d7dff))
  const earth = new Mesh(new SphereGeometry(2.4, 24, 16), new MeshBasicMaterial({ color: 0x3a7bd5 }))
  earth.position.set(7.4, 6.8, -11)
  earth.name = 'lunar-earth'
  root.add(earth)
  const land = new Mesh(new SphereGeometry(2.42, 16, 12), new MeshBasicMaterial({ color: 0x3d8a4a, transparent: true, opacity: 0.35 }))
  land.position.copy(earth.position)
  land.name = 'lunar-land'
  root.add(land)
  const sun = new PointLight(0xfff1d0, 28, 50, 2); sun.position.set(12, 16, 8); root.add(sun)
  return root
}

function rooftopGroup() {
  const root = new Group(); root.name = 'rooftop'
  const tar = mat(0x2a3038, { roughness: 0.9 })
  const parapet = mat(0x6d7380, { roughness: 0.7, metalness: 0.2 })
  addBox(root, 0, -0.08, 0, 22, 0.16, 16, tar)
  addBox(root, 0, 0.45, -7.9, 22, 0.9, 0.28, parapet)
  addBox(root, 0, 0.45, 7.9, 22, 0.9, 0.28, parapet)
  addBox(root, -10.9, 0.45, 0, 0.28, 0.9, 16, parapet)
  addBox(root, 10.9, 0.45, 0, 0.28, 0.9, 16, parapet)
  const ac = mat(0x4a5560, { roughness: 0.55, metalness: 0.4 })
  for (const x of [-6.4, -3.2, 5.8]) addBox(root, x, 0.55, -5.2, 1.6, 1.1, 1.4, ac)
  const helipad = canvas(512, 512, ctx => {
    ctx.fillStyle = '#2c333c'
    ctx.fillRect(0, 0, 512, 512)
    ctx.strokeStyle = '#f2d36b'
    ctx.lineWidth = 18
    ctx.beginPath()
    ctx.arc(256, 256, 200, 0, Math.PI * 2)
    ctx.stroke()
    ctx.fillStyle = '#f2d36b'
    ctx.font = 'bold 180px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText('H', 256, 320)
  })
  const pad = new Mesh(new CircleGeometry(3.2, 48), helipad ? new MeshBasicMaterial({ map: helipad }) : glow(0xf2d36b))
  pad.rotation.x = -Math.PI / 2
  pad.position.set(0, 0.02, 0.6)
  root.add(pad)
  const ring = new Mesh(new TorusGeometry(3.25, 0.04, 8, 48), glow(0xf2d36b))
  ring.rotation.x = Math.PI / 2
  ring.position.set(0, 0.04, 0.6)
  ring.name = 'helipad-ring'
  root.add(ring)
  const steel = mat(0x3a4450, { roughness: 0.45, metalness: 0.55 })
  addBox(root, 0, 0.02, 16, 3.2, 0.14, 16, steel)
  addBox(root, -1.55, 0.55, 16, 0.1, 1.05, 16, parapet)
  addBox(root, 1.55, 0.55, 16, 0.1, 1.05, 16, parapet)
  const glass = mat(0x1a2438, { roughness: 0.28, metalness: 0.55, emissive: 0x142033 })
  const brick = mat(0x3a3340, { roughness: 0.88 })
  for (const [x, y, z, w, h, d] of [
    [-16, -8, -18, 4, 22, 4], [18, -10, -16, 5, 28, 4.5], [-12, -6, 14, 3.2, 16, 3],
    [14, -7, 12, 3.6, 18, 3.4], [0, -12, -22, 6, 26, 5], [-22, -9, 4, 4, 20, 4],
  ] as const) {
    addBox(root, x, y + h / 2, z, w, h, d, Math.abs(x) > 14 ? glass : brick)
  }
  const warm = new PointLight(0xffc882, 16, 22, 2); warm.position.set(-4, 3, 2); root.add(warm)
  const cool = new PointLight(0x88c4ff, 12, 20, 2); cool.position.set(5, 4, -3); root.add(cool)
  return root
}

function hangarGroup() {
  const root = new Group(); root.name = 'hangar'
  const conc = mat(0x3a3f46, { roughness: 0.86 })
  const marks = glow(0xd9c36a)
  const wall = mat(0x4a3d32, { roughness: 0.9 })
  const steel = mat(0x2a323c, { roughness: 0.4, metalness: 0.7 })
  const crate = mat(0x6b4a2a, { roughness: 0.8 })
  addBox(root, 0, -0.08, 0, 28, 0.16, 22, conc)
  addBox(root, 0, 0.01, 0, 0.18, 0.01, 18, marks)
  addBox(root, -6, 0.01, 0, 0.08, 0.01, 18, marks)
  addBox(root, 6, 0.01, 0, 0.08, 0.01, 18, marks)
  addBox(root, 0, 4.2, -10.6, 28, 8.4, 0.4, wall)
  addBox(root, -13.8, 4.2, 0, 0.4, 8.4, 22, wall)
  addBox(root, 13.8, 4.2, 0, 0.4, 8.4, 22, wall)
  for (let x = -12; x <= 12; x += 4) {
    addBox(root, x, 4.4, -10.3, 0.22, 8.6, 0.22, steel)
    addBox(root, x, 8.6, 0, 0.22, 0.22, 21, steel)
  }
  addBox(root, 0, 3.4, 10.8, 16, 6.8, 0.18, steel)
  const doorWin = glow(0x6ad4ff)
  for (let i = 0; i < 4; i++) addBox(root, -4.5 + i * 3, 4.6, 10.92, 2.2, 0.9, 0.04, doorWin)
  addBox(root, -8.2, 0.55, -4, 1.8, 1.1, 1.4, crate)
  addBox(root, -8.2, 1.5, -4, 1.4, 0.8, 1.1, crate)
  addBox(root, 7.6, 0.7, 3.2, 2.2, 1.4, 1.8, crate)
  const amber = new PointLight(0xffb05a, 28, 28, 2); amber.position.set(-6, 6, 2); root.add(amber)
  const cyan = new PointLight(0x63dcff, 22, 26, 2); cyan.position.set(6, 5.5, -4); cyan.name = 'hangar-scan'; root.add(cyan)
  const fill = new PointLight(0xffe6c8, 16, 24, 2); fill.position.set(0, 7, 4); root.add(fill)
  return root
}

function desertGroup() {
  const root = new Group(); root.name = 'desert'
  const ground = new Mesh(new CircleGeometry(40, 40), mat(0xc9a06a, { roughness: 0.95 }))
  ground.rotation.x = -Math.PI / 2
  root.add(ground)
  const dune = mat(0xb98b52, { roughness: 0.98 })
  for (const [x, y, z, r] of [
    [-12, 0.8, -10, 5], [14, 1.2, -8, 6.2], [-8, 0.6, 12, 4.2], [10, 0.9, 14, 5.4],
    [0, 0.4, -16, 3.6], [-18, 1.4, 4, 7], [20, 1.1, 2, 5.8],
  ] as const) {
    const mesh = new Mesh(new IcosahedronGeometry(r, 0), dune)
    mesh.position.set(x, y, z)
    mesh.scale.y = 0.42
    root.add(mesh)
  }
  const canyon = mat(0x8a5a38, { roughness: 0.92 })
  addBox(root, 0, 3.4, -5.2, 44, 6.8, 1.6, canyon)
  addBox(root, 0, 3.7, 5.4, 44, 7.2, 1.6, canyon)
  const rock = mat(0x6a4a32, { roughness: 0.9 })
  for (const [x, z, r] of [[-3, 4, 0.8], [3.4, -5, 1.1], [1.2, 6, 0.6]] as const) {
    const mesh = new Mesh(new IcosahedronGeometry(r, 0), rock)
    mesh.position.set(x, r * 0.4, z)
    root.add(mesh)
  }
  const sun = new PointLight(0xffd09a, 32, 60, 2); sun.position.set(-10, 18, 8); root.add(sun)
  return root
}

function trainGroup() {
  const root = new Group(); root.name = 'train'
  const gravel = mat(0x3a342e, { roughness: 0.95 })
  const steel = mat(0x2a2e34, { roughness: 0.35, metalness: 0.75 })
  const wood = mat(0x6a4a2a, { roughness: 0.88 })
  const car = mat(0x1f3a58, { roughness: 0.5, metalness: 0.35 })
  const roof = mat(0x1a1e24, { roughness: 0.7 })
  const rust = mat(0x6a2a1a, { roughness: 0.55, metalness: 0.3 })
  addBox(root, 0, -2.55, 0, 80, 0.2, 8, gravel)
  addBox(root, 0, -2.38, -0.72, 80, 0.08, 0.12, steel)
  addBox(root, 0, -2.38, 0.72, 80, 0.08, 0.12, steel)
  for (let x = -36; x <= 36; x += 1.6) addBox(root, x, -2.42, 0, 0.18, 0.08, 1.9, wood)
  for (let i = 0; i < 5; i++) {
    const x = -16 + i * 8.2
    addBox(root, x, -1.15, 0, 7.6, 2.2, 2.6, i % 2 ? rust : car)
    addBox(root, x, 0.02, 0, 7.6, 0.12, 2.7, roof)
    for (const z of [-1.32, 1.32]) {
      for (let w = 0; w < 4; w++) addBox(root, x - 2.4 + w * 1.6, -0.7, z, 1.1, 0.7, 0.05, glow(0x7ecbff))
    }
  }
  const trees = new Group(); trees.name = 'train-landscape'
  const pine = mat(0x1f4a2e, { roughness: 0.9 })
  const trunk = mat(0x4a2e18, { roughness: 0.85 })
  for (let i = 0; i < 12; i++) {
    const z = i % 2 ? -6.5 : 6.5
    const x = -30 + i * 6
    addBox(trees, x, -1.4, z, 0.22, 1.6, 0.22, trunk)
    const cone = new Mesh(new CylinderGeometry(0.05, 1.1, 2.4, 8), pine)
    cone.position.set(x, 0.4, z)
    trees.add(cone)
  }
  root.add(trees)
  const sky = new PointLight(0xc8d8ff, 10, 30, 2); sky.position.set(0, 8, 4); root.add(sky)
  return root
}

function spaceLaneGroup() {
  const root = new Group(); root.name = 'space-lane'
  root.add(starDome('#03040a'))
  const rock = mat(0x2a2030, { roughness: 0.95, emissive: 0x140818 })
  const spots = [
    [-6.2, 1.4, -4.4, 1.1], [7.6, 0.8, -2.6, 1.5], [2.2, 2.4, 5.1, 0.8],
    [-4.1, -1.2, 4.6, 0.9], [9.2, 2.8, 3.6, 1.3], [-8.4, 3.2, 1.2, 0.7],
    [0.4, -2.1, -6.8, 1.6], [4.8, 4.2, -7.2, 0.6],
  ] as const
  spots.forEach(([x, y, z, r], i) => {
    const mesh = new Mesh(new IcosahedronGeometry(r, 0), rock)
    mesh.position.set(x, y, z)
    mesh.name = `asteroid-${i}`
    root.add(mesh)
  })
  const station = mat(0x8a93a0, { roughness: 0.4, metalness: 0.7 })
  addBox(root, 0, 2.4, -18, 10, 1.2, 3.4, station)
  const ring = new Mesh(new TorusGeometry(4.6, 0.18, 8, 48), glow(0x58e5ff))
  ring.position.set(0, 2.4, -18)
  ring.rotation.x = Math.PI / 2
  ring.name = 'station-ring'
  root.add(ring)
  addBox(root, 0, 4.4, -18, 0.4, 3.2, 0.4, station)
  const core = new PointLight(0x58e5ff, 24, 40, 2); core.position.set(0, 2.4, -16); root.add(core)
  const sun = new PointLight(0xffe6c8, 20, 50, 2); sun.position.set(-16, 10, 8); root.add(sun)
  return root
}

function jungleGroup() {
  const root = new Group(); root.name = 'jungle'
  const ground = new Mesh(new CircleGeometry(28, 40), mat(0x2a4a22, { roughness: 0.96 }))
  ground.rotation.x = -Math.PI / 2
  root.add(ground)
  const trunk = mat(0x4a2e18, { roughness: 0.88 })
  const leaf = mat(0x1f5a28, { roughness: 0.9 })
  for (let i = 0; i < 14; i++) {
    const a = i * 0.45
    const x = Math.cos(a) * (6 + (i % 4) * 1.8)
    const z = Math.sin(a) * (7 + (i % 3) * 1.4)
    addBox(root, x, 1.2, z, 0.28, 2.4, 0.28, trunk)
    const cone = new Mesh(new CylinderGeometry(0.08, 1.6, 3.2, 8), leaf)
    cone.position.set(x, 3.2, z)
    cone.name = 'jungle-leaf'
    root.add(cone)
  }
  const ruin = mat(0x6a5a48, { roughness: 0.86 })
  addBox(root, -3.2, 0.7, -4.4, 2.4, 1.4, 1.1, ruin)
  addBox(root, 4.1, 0.45, 3.2, 1.8, 0.9, 1.4, ruin)
  const fill = new PointLight(0x7dff9a, 10, 22, 2); fill.position.set(0, 5, 2); root.add(fill)
  return root
}

function snowGroup() {
  const root = new Group(); root.name = 'snow'
  const ground = new Mesh(new CircleGeometry(32, 40), mat(0xe8eef4, { roughness: 0.92 }))
  ground.rotation.x = -Math.PI / 2
  root.add(ground)
  const pine = mat(0x1f4a38, { roughness: 0.9 })
  const trunk = mat(0x4a2e18, { roughness: 0.85 })
  for (let i = 0; i < 10; i++) {
    const x = -12 + i * 2.6
    const z = i % 2 ? -7.4 : 8.2
    addBox(root, x, 0.8, z, 0.2, 1.6, 0.2, trunk)
    const cone = new Mesh(new CylinderGeometry(0.05, 1.3, 2.8, 8), pine)
    cone.position.set(x, 2.4, z)
    root.add(cone)
  }
  const lodge = mat(0x6a3a22, { roughness: 0.78 })
  addBox(root, 3.4, 1.1, -2.2, 4.2, 2.2, 3.2, lodge)
  addBox(root, 3.4, 2.5, -2.2, 4.6, 0.18, 3.6, mat(0xdde6ee, { roughness: 0.7 }))
  const drift = mat(0xf4f8fc, { roughness: 0.95 })
  for (let i = 0; i < 6; i++) {
    const mesh = new Mesh(new IcosahedronGeometry(0.9 + (i % 3) * 0.3, 0), drift)
    mesh.position.set(-6 + i * 2.4, 0.25, 2.4 - (i % 2))
    mesh.scale.y = 0.35
    mesh.name = 'snow-drift'
    root.add(mesh)
  }
  const sun = new PointLight(0xe8f4ff, 22, 40, 2); sun.position.set(-8, 10, 6); root.add(sun)
  return root
}

function casinoGroup() {
  const root = new Group(); root.name = 'casino'
  const floor = mat(0x1a1210, { roughness: 0.55, metalness: 0.35 })
  addBox(root, 0, -0.06, 0, 24, 0.12, 18, floor)
  const gold = glow(0xf2d36b)
  for (let i = -6; i <= 6; i++) addBox(root, i * 1.6, 0.01, 0, 0.06, 0.01, 16, gold)
  const column = mat(0xc9a15b, { roughness: 0.35, metalness: 0.65 })
  for (const x of [-7.4, 7.4]) for (const z of [-5.2, 1.2, 6.4]) {
    addBox(root, x, 2.2, z, 0.55, 4.4, 0.55, column)
  }
  const felt = mat(0x145a32, { roughness: 0.8 })
  addBox(root, 0, 0.55, 0, 3.4, 0.12, 1.6, felt)
  addBox(root, -3.8, 0.55, 2.4, 2.6, 0.12, 1.4, felt)
  addBox(root, 3.8, 0.55, 2.4, 2.6, 0.12, 1.4, felt)
  const wall = mat(0x3a1020, { roughness: 0.7 })
  addBox(root, 0, 2.6, -8.6, 22, 5.2, 0.3, wall)
  const lamp = new PointLight(0xffc16a, 18, 16, 2)
  lamp.position.set(0, 3.6, 0)
  lamp.name = 'casino-glow'
  root.add(lamp)
  const fill = new PointLight(0xff6a9a, 10, 18, 2); fill.position.set(-4, 3.2, 3); root.add(fill)
  return root
}

export function paintActionSet(root: Object3D | null, seconds: number) {
  if (!root) return
  const water = root.getObjectByName('sea-water') as Mesh | undefined
  if (water?.geometry) {
    const pos = water.geometry.getAttribute('position')
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i)
      const y = pos.getY(i)
      pos.setZ(i, Math.sin(x * 0.22 + seconds * 1.5) * 0.16 + Math.sin(y * 0.16 + seconds * 1.05) * 0.11)
    }
    pos.needsUpdate = true
    water.geometry.computeVertexNormals()
  }
  root.traverse(child => {
    if (child.name === 'sea-foam') child.position.x = ((child.position.x + 30 + seconds * 0.35) % 60) - 30
    if (child.name === 'lunar-earth' || child.name === 'lunar-land') child.rotation.y = seconds * 0.08
    if (child.name === 'helipad-ring') child.rotation.z = seconds * 0.4
    if (child.name === 'hangar-scan') child.position.x = Math.sin(seconds * 0.7) * 6
    if (child.name === 'train-landscape') child.position.x = -((seconds * 9) % 36)
    if (child.name.startsWith('asteroid-')) {
      child.rotation.y = seconds * (0.15 + child.position.x * 0.01)
      child.rotation.x = seconds * 0.08
    }
    if (child.name === 'station-ring') child.rotation.z = seconds * 0.25
    if (child.name === 'jungle-leaf') child.rotation.z = Math.sin(seconds * 0.8 + child.position.x) * 0.06
    if (child.name === 'snow-drift') child.position.x += Math.sin(seconds * 0.4 + child.position.z) * 0.002
    if (child.name === 'casino-glow') child.position.y = 3.4 + Math.sin(seconds * 2.2) * 0.15
  })
}
