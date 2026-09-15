import { applyActionTemplate } from './src/features/scene3d/actionTemplates.ts'
import { syncDressing } from './src/features/scene3d/dressing.ts'
import {
  applyLight,
  createWorld,
  fitGltf,
  paintWorld,
  placeSlot,
  placeholderMesh,
  pruneSlots,
  renderWorld,
  resizeWorld,
} from './src/features/scene3d/gpu.ts'
import { FACE_PACK_IDS, FACE_PACKS, talkingMascot, type FacePackId } from './src/features/scene3d/speech/facePackExamples.ts'
import { expressionAt, mouthAt } from './src/features/scene3d/speech/track.ts'
import { VISEMES } from './src/features/scene3d/speech/types.ts'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

const SHOTS = ['hangar-talk', 'sea-talk', 'voxel-talk', 'felt-talk', 'pumpkin-talk', 'cat-talk'] as const
const LABELS: Record<typeof SHOTS[number], string> = {
  'hangar-talk': 'Hangar · CRT + skull',
  'sea-talk': 'Sea · CRT + skull',
  'voxel-talk': 'Roof · cube + voxel skull',
  'felt-talk': 'Hangar · felt + clay',
  'pumpkin-talk': 'Roof · pumpkin + oni',
  'cat-talk': 'Hangar · cat + alien',
}

function remix(base: 'hangar-talk' | 'voxel-talk', left: FacePackId, right: FacePackId) {
  const doc = applyActionTemplate(base)!
  const [lead, reply] = doc.slots
  return {
    ...doc,
    slots: [
      talkingMascot(lead.id, lead.slot, lead.position, left, { rotationY: lead.rotationY, scale: lead.scale, motion: lead.motion }),
      talkingMascot(reply.id, reply.slot, reply.position, right, { rotationY: reply.rotationY, scale: reply.scale, motion: reply.motion }),
    ],
  }
}

function shotDocument(id: typeof SHOTS[number]) {
  if (id === 'felt-talk') return remix('hangar-talk', 'felt', 'clay')
  if (id === 'pumpkin-talk') return remix('voxel-talk', 'pumpkin', 'oni')
  if (id === 'cat-talk') return remix('hangar-talk', 'cat', 'alien')
  return applyActionTemplate(id)!
}
const host = document.querySelector('#view') as HTMLDivElement
const caption = document.querySelector('#caption') as HTMLParagraphElement
const status = document.querySelector('#status') as HTMLParagraphElement
const strip = document.querySelector('#strip') as HTMLDivElement
const atlas = document.querySelector('#atlas') as HTMLDivElement
const voice = document.querySelector('#voice') as HTMLAudioElement
const params = new URLSearchParams(location.search)
const startId = SHOTS.includes(params.get('shot') as typeof SHOTS[number]) ? params.get('shot') as typeof SHOTS[number] : 'hangar-talk'
const freezeParam = params.get('t')
const freeze = freezeParam === null || freezeParam === '' ? Number.NaN : Number(freezeParam)

let current = shotDocument(startId)
let playing = false
let started = 0
const driven: { seconds: number | null } = { seconds: null }
const clock = {
  setSceneSeconds(value: number | null) { driven.seconds = value },
  sceneReady: false,
  viseme() {
    const slot = current.slots[0]
    return slot.speech ? VISEMES[mouthAt(slot.speech, sceneSeconds()).b] : 'rest'
  },
}
Object.assign(window, { facePack: clock })

function sceneSeconds(now = performance.now()) {
  if (driven.seconds != null) return driven.seconds
  if (Number.isFinite(freeze)) return Math.max(0, Math.min(current.duration - 0.01, freeze))
  return playing ? ((now - started) / 1000) % current.duration : 0
}
const world = createWorld(host, current.light, current.camera.fov)
const loader = new GLTFLoader()
resizeWorld(world, host)

for (const id of SHOTS) {
  const button = document.createElement('button')
  button.type = 'button'
  button.textContent = LABELS[id]
  button.dataset.shot = id
  button.setAttribute('aria-pressed', id === startId ? 'true' : 'false')
  button.addEventListener('click', () => select(id))
  strip.append(button)
}

for (const id of FACE_PACK_IDS) {
  const figure = document.createElement('figure')
  const img = document.createElement('img')
  img.src = FACE_PACKS[id].url
  img.alt = `${id} visemes and expressions`
  const cap = document.createElement('figcaption')
  cap.textContent = `${id} · 9 visemes × 6 expressions`
  figure.append(img, cap)
  atlas.append(figure)
}

function mount(doc: typeof current) {
  pruneSlots(world, doc.slots)
  syncDressing(world, doc.dressing)
  world.floor.visible = false
  applyLight(world.dir, doc.light)
  playing = false
  clock.sceneReady = false
  let pending = 0
  for (const slot of doc.slots) {
    placeSlot(world, slot, placeholderMesh(slot), [], 1, false)
    if (!slot.sourceUrl) continue
    pending++
    loader.load(slot.sourceUrl, gltf => {
      if (current.slots.find(item => item.id === slot.id)?.sourceUrl !== slot.sourceUrl) {
        gltf.scene.removeFromParent()
        return
      }
      const baseScale = fitGltf(gltf.scene, slot)
      placeSlot(world, slot, gltf.scene, gltf.animations, baseScale, true)
      pending--
      if (pending === 0) {
        clock.sceneReady = true
        if (!Number.isFinite(freeze) && driven.seconds == null) {
          playing = true
          started = performance.now()
          voice.currentTime = 0
          void voice.play().catch(() => undefined)
        }
      }
    })
  }
}

function select(id: typeof SHOTS[number]) {
  current = shotDocument(id)
  mount(current)
  caption.textContent = `${LABELS[id]} · ${current.dressing} · ${current.duration}s · synthetic vowels`
  for (const button of strip.querySelectorAll<HTMLButtonElement>('button')) {
    button.setAttribute('aria-pressed', button.dataset.shot === id ? 'true' : 'false')
  }
  voice.currentTime = 0
}

select(startId)
const tick = (now: number) => {
  const seconds = sceneSeconds(now)
  paintWorld(world, current, seconds)
  renderWorld(world)
  const labels = current.slots.map(slot => {
    if (!slot.speech) return slot.id
    const mouth = VISEMES[mouthAt(slot.speech, seconds).b]
    return `${slot.id}: ${expressionAt(slot.speech, seconds)}/${mouth}`
  })
  status.textContent = `${seconds.toFixed(2)}s · ${labels.join(' · ')}`
  requestAnimationFrame(tick)
}
requestAnimationFrame(tick)
window.addEventListener('resize', () => resizeWorld(world, host))
document.addEventListener('click', () => { void voice.play().catch(() => undefined) }, { once: true })
