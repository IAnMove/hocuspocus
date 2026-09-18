import { AdditiveBlending, BufferAttribute, BufferGeometry, Color, CylinderGeometry, Group, Mesh, MeshBasicMaterial, PlaneGeometry, Points, SphereGeometry } from 'three'
import { energyMaterial, softSparkMaterial, type EnergySurface } from './energyShaders'
import { fxRandom } from './types'
import type { WorldSfxKind } from './world'
import { buildPackedEffect } from './worldPack'

function surface(kind: EnergySurface, color: string, width: number, height = width, billboard = false) {
  return new Mesh(new PlaneGeometry(width, height), energyMaterial(kind, color, billboard))
}
function sparks(color: string, mode: string, radius = .7, count = 72) {
  const data = new Float32Array(count * 3)
  for (let i = 0; i < count; i++) {
    if (mode === 'burst') {
      const theta = fxRandom(19, i) * Math.PI * 2
      const phi = Math.acos(2 * fxRandom(3, i) - 1)
      const r = radius * (.25 + fxRandom(7, i) * .9)
      data.set([Math.sin(phi) * Math.cos(theta) * r, Math.cos(phi) * r, Math.sin(phi) * Math.sin(theta) * r], i * 3)
    } else {
      const a = fxRandom(19, i) * Math.PI * 2, r = radius * (.7 + fxRandom(3, i) * .3)
      data.set([Math.cos(a) * r, 0, Math.sin(a) * r], i * 3)
    }
  }
  const geometry = new BufferGeometry()
  geometry.setAttribute('position', new BufferAttribute(data, 3))
  geometry.setAttribute('base', new BufferAttribute(data.slice(), 3))
  const points = new Points(geometry, softSparkMaterial(color))
  points.userData.kind = mode
  return points
}
function mist(color: string) {
  const root = new Group()
  for (let i = 0; i < 5; i++) {
    const cloud = surface('mist', color, 2.6, 1.4, true)
    cloud.position.set((i - 2) * .42, i % 2 * .2, (i % 3 - 1) * .4)
    cloud.userData.seedOffset = i * 7
    root.add(cloud)
  }
  return root
}
function portal(color: string, gate = false) {
  const root = new Group()
  root.add(surface('portal', color, 1.75, 2.05))
  if (gate) {
    const outer = surface('circle', color, 2.15)
    outer.position.z = -.05
    root.add(outer)
  }
  const rim = sparks(color, 'rim')
  rim.rotation.x = Math.PI / 2
  root.add(rim)
  return root
}
function circle(color: string, shock = false) {
  const root = new Group(), plane = surface(shock ? 'shock' : 'circle', color, shock ? 6 : 2.8)
  plane.rotation.x = -Math.PI / 2
  plane.position.y = .018
  root.add(plane, sparks(color, shock ? 'shockdust' : 'rise'))
  return root
}
function beam(color: string, laser: boolean) {
  const root = new Group(), shaft = new Group()
  shaft.userData.kind = 'beam'
  // Crossed transparent ribbons retain a bright core from every viewing angle.
  for (let i = 0; i < 3; i++) {
    const ribbon = surface('beam', color, laser ? .065 : .25, 1)
    ribbon.rotation.y = i * Math.PI / 3
    shaft.add(ribbon)
  }
  root.add(shaft)
  return root
}
function boltSegment(color: string) {
  const segment = new Group()
  for (const [radius, power] of [[.009, 4], [.027, .55]]) {
    const material = new MeshBasicMaterial({ color: new Color(color).multiplyScalar(power), transparent: true,
      depthWrite: false, blending: AdditiveBlending })
    material.userData.energyBaseColor = material.color.clone()
    segment.add(new Mesh(new CylinderGeometry(radius, radius, 1, 5), material))
  }
  return segment
}
function lightning(color: string) {
  const root = new Group()
  for (let i = 0; i < 24; i++) {
    const segment = boltSegment(color)
    segment.userData.kind = 'bolt'
    root.add(segment)
  }
  for (let i = 0; i < 8; i++) {
    const segment = boltSegment(color)
    segment.userData.kind = 'branch'
    root.add(segment)
  }
  return root
}
function orb(color: string) {
  const root = new Group()
  root.add(surface('orb', color, 1.35, 1.35, true), sparks(color, 'orb', .25, 44))
  return root
}
function aura(color: string) {
  const root = new Group()
  root.add(surface('aura', color, 1.45, 2.1, true), sparks(color, 'rise', .45, 96))
  return root
}
function explosion(color: string) {
  const root = new Group()
  for (let i = 0; i < 3; i++) {
    const core = surface('fireball', color, 1.7 + i * .18, 2.05 + i * .12, true)
    core.userData.kind = 'fireball'
    core.userData.seedOffset = i * 13
    core.position.set((i - 1) * .08, i * .05, (i - 1) * .06)
    root.add(core)
  }
  const inner = surface('flash', color, 1.05, 1.05, true)
  inner.userData.kind = 'flash'
  const tongues = surface('aura', color, 1.7, 2.4, true)
  tongues.userData.kind = 'fireball'
  tongues.position.y = .25
  const ring = surface('blastRing', color, 7.2)
  ring.rotation.x = -Math.PI / 2
  ring.position.y = .03
  const debris = sparks(color, 'burst', .28, 280)
  debris.material = softSparkMaterial(color, .07)
  const cinders = sparks('#ffcc77', 'burst', .18, 120)
  cinders.material = softSparkMaterial('#ffcc77', .045)
  const plume = mist('#3a2c26')
  plume.userData.kind = 'plume'
  plume.position.y = .2
  root.add(inner, tongues, ring, debris, cinders, plume)
  return root
}
function missiles(color: string) {
  const root = new Group()
  for (let i = 0; i < 3; i++) {
    const bolt = surface('orb', color, .65, .65, true)
    bolt.userData.kind = 'missile'
    root.add(bolt)
  }
  const impact = new Mesh(new SphereGeometry(.12, 16, 12), new MeshBasicMaterial({
    color: new Color(color).multiplyScalar(3), transparent: true, opacity: 0,
    depthWrite: false, blending: AdditiveBlending,
  }))
  impact.userData.kind = 'impact'
  root.add(impact)
  return root
}
export function buildEnergyEffect(kind: WorldSfxKind, color: string) {
  switch (kind) {
    case 'portal': return portal(color)
    case 'summoning_gate': return portal(color, true)
    case 'magic_circle': return circle(color)
    case 'shockwave': return circle(color, true)
    case 'lightning': return lightning(color)
    case 'energy_beam': return beam(color, false)
    case 'laser': return beam(color, true)
    case 'energy_orb': return orb(color)
    case 'anime_aura': return aura(color)
    case 'arcane_missiles': return missiles(color)
    case 'smoke': return mist(color)
    case 'sparks': { const root = new Group(); root.add(sparks(color, 'rise', .45, 144)); return root }
    case 'explosion': return explosion(color)
    default: return buildPackedEffect(kind, color) ?? new Group()
  }
}
