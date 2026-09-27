import { BoxGeometry, CanvasTexture, CylinderGeometry, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, PointLight, SRGBColorSpace, type Object3D } from 'three'

/** An open-front room with a physical desk, keyboard and animated code screen. */
export function workshopGroup() {
  const root = new Group(); root.name = 'workshop'
  const wood = new MeshStandardMaterial({ color: 0x774b2b, roughness: .78 })
  const metal = new MeshStandardMaterial({ color: 0x142332, roughness: .45, metalness: .4 })
  const wall = new MeshStandardMaterial({ color: 0x49392c, roughness: .92 })
  const box = (x: number, y: number, z: number, w: number, h: number, d: number, material: MeshStandardMaterial | MeshBasicMaterial = wood) => {
    const mesh = new Mesh(new BoxGeometry(w, h, d), material); mesh.position.set(x, y, z); root.add(mesh); return mesh
  }
  box(0, -.07, 0, 10, .12, 10, wall)
  box(0, 2, -4.85, 9.5, 4, .14, wall)
  box(-4.7, 2.2, 0, .14, 4.4, 10, wall); box(4.7, 2.2, 0, .14, 4.4, 10, wall)
  for (const x of [-2.7, .2]) box(x, 2, -4.49, .09, 1.75, .09, metal)
  for (const y of [1.16, 2.84]) box(-1.25, y, -4.49, 3, .09, .09, metal)
  box(-1.25, 2, -4.45, .07, 1.7, .08, metal)
  box(-1.25, 2, -4.45, 2.95, .07, .08, metal)
  for (const y of [.45, 1.1, 1.8]) {
    box(2.7, y, -3.9, 2.3, .09, .6)
    for (let i = 0; i < 9; i++) {
      const cover = new MeshStandardMaterial({ color: [0x46686c, 0x956344, 0xa89974][i % 3], roughness: .8 })
      box(1.75 + i * .22, y + .22, -3.88, .13, .38 + (i % 2) * .08, .35, cover)
    }
  }
  box(0, .82, -.6, 2.6, .11, 1.45)
  for (const x of [-1.1, 1.1]) for (const z of [-1.12, -.05]) box(x, .4, z, .09, .8, .09, metal)
  box(.9, .4, -.58, .38, .8, .55, metal)
  const led = new MeshBasicMaterial({ color: 0x73ecf0 })
  for (let i = 0; i < 4; i++) box(.9, .38 + i * .09, -.295, .24, .016, .015, led)
  box(0, .92, -.92, .42, .06, .3, metal); box(0, 1.06, -1, .06, .28, .06, metal)
  box(0, 1.36, -1, 1.28, .72, .1, metal)
  const canvas = document.createElement('canvas'); canvas.width = 1024; canvas.height = 576
  const texture = new CanvasTexture(canvas); texture.colorSpace = SRGBColorSpace
  const screen = box(0, 1.36, -.94, 1.18, .62, .015, metal)
  screen.material = new MeshBasicMaterial({ map: texture }); screen.name = 'workshop-screen'
  screen.userData.codeCanvas = canvas; screen.userData.codeTexture = texture
  box(0, .9, -.1, .73, .04, .25, metal)
  const key = new MeshStandardMaterial({ color: 0xa4ada9, roughness: .7 })
  for (let row = 0; row < 4; row++) for (let col = 0; col < 12; col++) box((col - 5.5) * .052, .926, -.19 + row * .055, .042, .016, .038, key)
  box(.56, .916, -.06, .12, .07, .18, metal)
  const mug = new Mesh(new CylinderGeometry(.085, .065, .17, 16), new MeshStandardMaterial({ color: 0xdba754 }))
  mug.position.set(-.9, .96, -.15); root.add(mug)
  const amber = new PointLight(0xffb05a, 16, 12); amber.position.set(-2.5, 2.4, 1); root.add(amber)
  const monitorLight = new PointLight(0x63dcff, 5, 4); monitorLight.position.set(0, 1.4, -.65); root.add(monitorLight)
  return root
}

export function paintWorkshop(root: Object3D | null, seconds: number, state = 'code') {
  const screen = root?.getObjectByName('workshop-screen')
  if (!screen) return
  const canvas = screen.userData.codeCanvas as HTMLCanvasElement
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.fillStyle = '#07151d'; ctx.fillRect(0, 0, 1024, 576)
  ctx.fillStyle = '#243a46'; ctx.fillRect(0, 0, 1024, 64)
  ctx.font = '24px monospace'; ctx.fillStyle = '#e5c99c'; ctx.fillText('gandalf@shire  ~/the-last-branch', 30, 41)
  const lines = state === 'error' ? ['> BUILD FAILED', '', '2 errors detected', 'contract.test: FAIL', '', '$ inspect --context', '> magic needs correction'] : state === 'success' ? ['> BUILD PASSED', '', '42 tests passed', '0 failed', '', '$ git push origin the-last-branch', '> servers online'] : ['const magic = await create();', 'if (build.failed) {', '  await fix(withCoffee);', '}', '$ git add hope', '$ git commit -m "one more try"', '> compiling the impossible...'];
  const count = Math.floor(seconds * 21) % 250 + 14
  let remaining = count
  lines.forEach((line, i) => {
    ctx.fillStyle = state === 'error' ? '#ff7882' : state === 'success' ? '#a3f7bc' : i < 4 ? '#72daef' : '#edc987'
    ctx.fillText(line.slice(0, Math.max(0, remaining)), 38, 110 + i * 54)
    remaining -= line.length
  })
  ;(screen.userData.codeTexture as CanvasTexture).needsUpdate = true
}
