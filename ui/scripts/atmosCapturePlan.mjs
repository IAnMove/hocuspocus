import os from 'node:os'
import path from 'node:path'

export const CATEGORY_LABEL = {
  cinema: 'Cinema',
  action: 'Action',
  product: 'Product',
  music: 'Music video',
  space: 'Space',
  drive: 'Driving',
  'dark-fantasy': 'Dark Fantasy',
  psx: 'PSX',
  creative: 'Creative',
  perspective: 'Perspectives',
  animated: 'Living backgrounds',
  pixel: 'Pixel worlds',
}

const SOFTWARE_RENDERER = /swiftshader|llvmpipe|software/i
const HARDWARE_RENDERER = /nvidia|geforce|radeon|\bamd\b/i

export function categoryLabel(category) {
  const label = CATEGORY_LABEL[category]
  if (!label) throw new Error(`No library label for category ${category || 'unknown'}.`)
  return label
}

export function assertSoftwareRenderer(name) {
  const text = String(name || '')
  if (HARDWARE_RENDERER.test(text)) throw new Error(`Refusing a hardware renderer: ${text}`)
  if (!SOFTWARE_RENDERER.test(text)) throw new Error(`Renderer is not software WebGL: ${text || 'unknown'}`)
  return text
}

export function assertOutsideRepo(outDir, repoRoot) {
  const target = path.resolve(outDir)
  const root = path.resolve(repoRoot)
  const prefix = root.endsWith(path.sep) ? root : root + path.sep
  if (target === root || target.startsWith(prefix)) throw new Error('Capture output must stay outside the repository.')
  return target
}

export function defaultCaptureDir() {
  return process.env.ATMOS_CAPTURE_DIR || path.join(os.tmpdir(), 'atmos-capture')
}

const LOOK_FLAG = { '--palette': 'palette', '--time': 'time', '--subject': 'subject' }

function blankLook() {
  return { palette: '', time: '', subject: '' }
}

function captureOptions(help, ids, exportClip, out, port, look) {
  return { help, ids, exportClip, out, port, palette: look.palette, time: look.time, subject: look.subject }
}

function takeLook(argv, index, look) {
  const key = LOOK_FLAG[argv[index]]
  if (!key) return false
  look[key] = readOption(argv, index, argv[index])
  return true
}

export function parseCaptureArgs(argv, env = process.env) {
  const ids = []
  const look = blankLook()
  let exportClip = false
  let out = env.ATMOS_CAPTURE_DIR || ''
  let port = Number(env.HOCUSPOCUS_E2E_PORT || 4199)
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index]
    if (argument === '--help' || argument === '-h') return captureOptions(true, ids, exportClip, out, port, look)
    if (argument === '--export') { exportClip = true; continue }
    if (argument === '--out' || argument === '--port') {
      const value = readOption(argv, index, argument)
      index += 1
      if (argument === '--out') out = value
      else port = Number(value)
      continue
    }
    if (takeLook(argv, index, look)) { index += 1; continue }
    if (argument.startsWith('--')) throw new Error(`Unknown option ${argument}.`)
    ids.push(argument)
  }
  if (!ids.length) throw new Error('Pass at least one template id.')
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Port must be an integer from 1 to 65535.')
  return captureOptions(false, ids, exportClip, out, port, look)
}

function readOption(argv, index, name) {
  const value = argv[index + 1]
  if (!value || value.startsWith('--')) throw new Error(`${name} needs a value.`)
  return value
}
