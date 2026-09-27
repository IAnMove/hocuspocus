import { BoxGeometry, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, PlaneGeometry } from 'three'
import { defaultMediaScreen } from './mediaScreen.ts'
import type { Scene3DSlot } from './types.ts'

/** A real world-space prop; its content shares camera, transforms and occlusion. */
export function screenGeometry(slot: Scene3DSlot) {
  const screen = slot.screen ?? defaultMediaScreen(), root = new Group()
  const { width, height, style } = screen
  if (style === 'crt') return crtSet(slot, root, width, height)
  const lift = style === 'billboard' ? 1.8 : style === 'monitor' ? .4 : 0
  const center = lift + height / 2
  const box = (w: number, h: number, d: number, x: number, y: number, z: number, color: number) => {
    const mesh = new Mesh(new BoxGeometry(w, h, d), new MeshStandardMaterial({ color, roughness: .5, metalness: .3 }))
    mesh.position.set(x, y, z); root.add(mesh)
  }
  if (style !== 'frameless') {
    box(width + .18, height + .18, .18, 0, center, -.11, 0x171e2c)
    box(width + .22, .025, .035, 0, center - height / 2 - .07, .005, 0x497991)
    if (style === 'monitor') {
      box(.16, lift, .16, 0, lift / 2, -.1, 0x354357)
      box(width * .38, .08, .65, 0, .04, -.1, 0x171e2c)
    } else for (const x of [-width * .32, width * .32]) box(.14, lift, .16, x, lift / 2, -.1, 0x354357)
  }
  const face = new Mesh(new PlaneGeometry(width, height), new MeshBasicMaterial({ color: 0x10202c, toneMapped: false }))
  face.name = 'SCREEN_CONTENT'; face.position.y = center; root.add(face)
  root.position.fromArray(slot.position); root.rotation.y = slot.rotationY; root.scale.setScalar(slot.scale)
  return root
}

const CASINGS = [0x1b1b1f, 0x2a2724, 0x8c8577, 0x3a3d44, 0x121214]

/** A deep cathode-ray TV: bezel, chin with knobs and a tapered back. It
 *  stands on its base, so TVs stack by placing one on another. */
function crtSet(slot: Scene3DSlot, root: Group, width: number, height: number) {
  const bezel = Math.min(width, height) * .11, chin = height * .2, depth = width * .8
  const tone = CASINGS[[...slot.id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % CASINGS.length]
  const plastic = new MeshStandardMaterial({ color: tone, roughness: .55, metalness: .1 })
  const box = (w: number, h: number, d: number, x: number, y: number, z: number, material = plastic) => {
    const mesh = new Mesh(new BoxGeometry(w, h, d), material); mesh.position.set(x, y, z); root.add(mesh)
  }
  const frontH = height + bezel * 2 + chin
  box(width + bezel * 2, frontH, depth * .55, 0, frontH / 2, -depth * .275)
  box(width * .72, height * .78, depth * .45, 0, frontH * .55, -depth * .75)
  const knob = new MeshStandardMaterial({ color: 0x0a0a0a, roughness: .4, metalness: .5 })
  for (const x of [.28, .38]) box(width * .05, width * .05, .02, width * x, chin * .55, .01, knob)
  const face = new Mesh(new PlaneGeometry(width, height), new MeshBasicMaterial({ color: 0x0c1418, toneMapped: false }))
  face.name = 'SCREEN_CONTENT'; face.position.set(0, chin + bezel + height / 2, .012); root.add(face)
  root.position.fromArray(slot.position); root.rotation.y = slot.rotationY; root.scale.setScalar(slot.scale)
  return root
}
