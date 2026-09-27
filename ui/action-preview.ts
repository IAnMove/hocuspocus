import {
  ACTION_TEMPLATE_IDS,
  actionCard,
  applyActionTemplate,
} from './src/features/scene3d/actionTemplates.ts'
import { syncDressing } from './src/features/scene3d/dressing.ts'
import {
  applyLight,
  createWorld,
  paintWorld,
  placeSlot,
  placeholderMesh,
  pruneSlots,
  renderWorld,
  resizeWorld,
} from './src/features/scene3d/gpu.ts'

const host = document.querySelector('#view') as HTMLDivElement
const caption = document.querySelector('#caption') as HTMLParagraphElement
const strip = document.querySelector('#strip') as HTMLDivElement
const params = new URLSearchParams(location.search)
const startId = ACTION_TEMPLATE_IDS.includes(params.get('shot') as typeof ACTION_TEMPLATE_IDS[number])
  ? params.get('shot') as typeof ACTION_TEMPLATE_IDS[number]
  : ACTION_TEMPLATE_IDS[0]

let current = applyActionTemplate(startId)!
const world = createWorld(host, current.light, current.camera.fov)
resizeWorld(world, host)
mount(current)

for (const id of ACTION_TEMPLATE_IDS) {
  const card = actionCard(id, 'en')
  const button = document.createElement('button')
  button.type = 'button'
  button.textContent = card?.title ?? id
  button.dataset.shot = id
  button.setAttribute('aria-pressed', id === current.templateId ? 'true' : 'false')
  button.addEventListener('click', () => select(id))
  strip.append(button)
}

function mount(doc: typeof current) {
  pruneSlots(world, doc.slots)
  syncDressing(world, doc.dressing)
  world.floor.visible = false
  applyLight(world.dir, doc.light)
  for (const slot of doc.slots) placeSlot(world, slot, placeholderMesh(slot), [], 1, true)
}

function select(id: typeof ACTION_TEMPLATE_IDS[number]) {
  current = applyActionTemplate(id)!
  mount(current)
  caption.textContent = `${actionCard(id, 'en')?.title} · ${current.dressing} · ${current.duration}s`
  for (const button of strip.querySelectorAll('button')) {
    button.setAttribute('aria-pressed', button.dataset.shot === id ? 'true' : 'false')
  }
}

select(startId)
const started = performance.now()
const tick = (now: number) => {
  const seconds = ((now - started) / 1000) % current.duration
  paintWorld(world, current, seconds)
  renderWorld(world)
  requestAnimationFrame(tick)
}
requestAnimationFrame(tick)
window.addEventListener('resize', () => resizeWorld(world, host))
