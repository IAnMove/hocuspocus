import { EXPRESSIONS, VISEMES, type Expression, type Viseme } from './src/features/scene3d/speech/types.ts'
import {
  EXPRESSION_EYES,
  FACE_PLANE_REST_PROMPT,
  VISEME_ALIASES,
  VISEME_MOUTHS,
  expressionPrompt,
  fillFacePrompt,
  parseFacePackStillName,
  visemePrompt,
} from './src/features/scene3d/speech/facePackPrompts.ts'
import { composeFacePack } from './src/features/scene3d/speech/facePackAssemble.ts'

const skinInput = document.querySelector('#skin') as HTMLInputElement
const restBox = document.querySelector('#rest-prompt') as HTMLTextAreaElement
const promptList = document.querySelector('#prompt-list') as HTMLDivElement
const slotsEl = document.querySelector('#slots') as HTMLDivElement
const status = document.querySelector('#status') as HTMLParagraphElement
const preview = document.querySelector('#preview') as HTMLCanvasElement
const downloadBtn = document.querySelector('#download') as HTMLButtonElement
const files = document.querySelector('#files') as HTMLInputElement
const stills = new Map<string, HTMLImageElement>()

function skin() {
  return skinInput.value.trim() || 'cream skin'
}

function renderPrompts() {
  restBox.value = fillFacePrompt(FACE_PLANE_REST_PROMPT, skin())
  promptList.replaceChildren()
  for (const viseme of VISEMES) {
    if (viseme === 'rest') continue
    const alias = VISEME_ALIASES[viseme]
    const block = document.createElement('div')
    const area = document.createElement('textarea')
    area.id = `p-${viseme}`
    area.readOnly = true
    area.value = alias ? `Alias of ${alias}. Optional. ${visemePrompt(viseme, skin())}` : visemePrompt(viseme, skin())
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.textContent = `Copiar ${viseme}`
    btn.dataset.copy = area.id
    const label = document.createElement('label')
    label.textContent = `Visema ${viseme} — ${VISEME_MOUTHS[viseme as Exclude<Viseme, 'rest'>].slice(22)}`
    block.append(label, area, btn)
    promptList.append(block)
  }
  for (const expression of EXPRESSIONS) {
    if (expression === 'neutral') continue
    const block = document.createElement('div')
    const area = document.createElement('textarea')
    area.id = `p-${expression}`
    area.readOnly = true
    area.value = expressionPrompt(expression, skin())
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.textContent = `Copiar ${expression}`
    btn.dataset.copy = area.id
    const label = document.createElement('label')
    label.textContent = `Expresión ${expression} — ${EXPRESSION_EYES[expression as Exclude<Expression, 'neutral'>].slice(40)}`
    block.append(label, area, btn)
    promptList.append(block)
  }
}

function drawSlot(key: string, img?: HTMLImageElement) {
  let slot = document.querySelector(`[data-slot="${key}"]`) as HTMLDivElement | null
  if (!slot) {
    slot = document.createElement('div')
    slot.className = 'slot'
    slot.dataset.slot = key
    slotsEl.append(slot)
  }
  slot.replaceChildren()
  const title = document.createElement('strong')
  title.textContent = key
  slot.append(title)
  if (img) {
    const previewImg = document.createElement('img')
    previewImg.src = img.src
    previewImg.alt = key
    slot.append(previewImg)
  }
}

function ensureSlots() {
  drawSlot('rest', stills.get('rest'))
  for (const viseme of VISEMES) {
    if (viseme === 'rest') continue
    drawSlot(viseme, stills.get(viseme))
  }
  for (const expression of EXPRESSIONS) {
    if (expression === 'neutral') continue
    drawSlot(expression, stills.get(expression))
  }
}

function build() {
  const rest = stills.get('rest')
  if (!rest) {
    status.textContent = 'Falta rest.png'
    return
  }
  const visemes: Partial<Record<Viseme, HTMLImageElement>> = {}
  const expressions: Partial<Record<Expression, HTMLImageElement>> = {}
  for (const viseme of VISEMES) {
    if (viseme !== 'rest' && stills.get(viseme)) visemes[viseme] = stills.get(viseme)
  }
  for (const expression of EXPRESSIONS) {
    if (expression !== 'neutral' && stills.get(expression)) expressions[expression] = stills.get(expression)
  }
  const canvas = composeFacePack({ rest, visemes, expressions })
  const ctx = preview.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, preview.width, preview.height)
  ctx.drawImage(canvas, 0, 0, preview.width, preview.height)
  downloadBtn.disabled = false
  status.textContent = '9×6 listo. Color anclado al reposo.'
}

function loadFile(file: File) {
  const parsed = parseFacePackStillName(file.name)
  if (!parsed) {
    status.textContent = `Nombre no reconocido: ${file.name}`
    return
  }
  const img = new Image()
  img.onload = () => {
    stills.set(parsed.kind === 'rest' ? 'rest' : parsed.id, img)
    ensureSlots()
    status.textContent = `Cargado ${parsed.kind === 'rest' ? 'rest' : parsed.id}`
  }
  img.src = URL.createObjectURL(file)
}

renderPrompts()
ensureSlots()
skinInput.addEventListener('input', renderPrompts)
document.addEventListener('click', event => {
  const btn = (event.target as HTMLElement).closest('button[data-copy]') as HTMLButtonElement | null
  if (!btn?.dataset.copy) return
  const area = document.getElementById(btn.dataset.copy) as HTMLTextAreaElement | null
  if (area) void navigator.clipboard.writeText(area.value)
})
files.addEventListener('change', () => {
  for (const file of files.files ?? []) loadFile(file)
})
document.querySelector('#build')!.addEventListener('click', build)
downloadBtn.addEventListener('click', () => {
  preview.toBlob(blob => {
    if (!blob) return
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'pack.png'
    a.click()
  })
})
