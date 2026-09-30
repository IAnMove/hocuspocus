import { spawn } from 'node:child_process'
import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'
import { installApiRoutes } from '../e2e/helpers/apiRoutes.ts'
import { bootWatchdogPlaceholderPath } from '../e2e/helpers/bootWatchdogPlaceholderPath.ts'
import { lockUiLanguage } from '../e2e/helpers/lockUiLanguage.ts'
import { world3dExportPlan, world3dExportSize } from '../src/features/scene3d/exportMp4.ts'
import { isCoreTemplate } from '../src/features/scene3d/templateCatalog.ts'
import { SCENE3D_TEMPLATES, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import {
  assertOutsideRepo,
  assertSoftwareRenderer,
  categoryLabel,
  defaultCaptureDir,
  parseCaptureArgs,
} from './atmosCapturePlan.mjs'

const uiRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(uiRoot, '..')
const SOFTWARE_ARGS = ['--disable-gpu', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']

function usage() {
  return `Usage: npm run atmos:capture -- <template-id> [more ids] [--export] [--out DIR] [--port N]

Builds the UI and opens Video 3D on 127.0.0.1 with software WebGL.
Writes a 1920x1080 PNG per template. --export also writes a 6s MP4.
Output stays outside the repository (ATMOS_CAPTURE_DIR or the system temp dir).
`
}

function knownTemplate(id) {
  const found = SCENE3D_TEMPLATES.some(item => item.id === id)
  if (!found) throw new Error(`Unknown template ${id}.`)
  return { id, category: TEMPLATE_CATEGORIES[id], core: isCoreTemplate(id) }
}

function spawnLogged(command, args) {
  return spawn(command, args, { cwd: uiRoot, stdio: 'inherit' })
}

function onceExit(child) {
  return new Promise((resolve, reject) => {
    child.once('error', reject)
    child.once('exit', code => resolve(code ?? 1))
  })
}

function stopTree(child) {
  if (!child?.pid) return
  try { process.kill(-child.pid, 'SIGTERM') } catch { /* the preview already exited */ }
}

async function buildUi() {
  const code = await onceExit(spawnLogged('npm', ['run', 'build']))
  if (code !== 0) throw new Error(`UI build exited ${code}.`)
}

async function waitForPreview(url) {
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch { /* preview is still starting */ }
    await new Promise(resolve => setTimeout(resolve, 400))
  }
  throw new Error(`Preview did not answer ${url}.`)
}

async function startPreview(port) {
  const child = spawn('npx', ['vite', 'preview', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
    cwd: uiRoot, stdio: 'inherit', detached: true,
  })
  const url = `http://127.0.0.1:${port}`
  try { await waitForPreview(url) } catch (error) { stopTree(child); throw error }
  return { child, url }
}

async function readRenderer(page) {
  return page.evaluate(() => {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl2') || canvas.getContext('webgl')
    const info = gl && gl.getExtension('WEBGL_debug_renderer_info')
    return info && gl ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : ''
  })
}

async function bootStudio(page) {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await installApiRoutes(page)
  await lockUiLanguage(page, 'en')
  await page.addInitScript({ path: bootWatchdogPlaceholderPath })
  await page.goto('/')
  const skip = page.getByRole('button', { name: 'Skip' })
  try { await skip.click({ timeout: 8_000 }) } catch { /* intro already dismissed */ }
  await page.getByRole('button', { name: 'Studios' }).click()
  await page.getByRole('tab', { name: 'Video 3D', exact: true }).click()
  await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
  await page.getByRole('button', { name: 'Expand editor', exact: true }).click()
  await page.getByTestId('scene3d-workspace').waitFor()
}

async function openTemplate(page, template) {
  await page.getByTestId('world3d-open-library').click()
  const library = page.getByTestId('world3d-shot-library')
  const mode = template.core ? 'Templates' : 'Examples and variants'
  await library.getByRole('button', { name: mode, exact: true }).click()
  const shotType = library.getByRole('group', { name: 'Shot type', exact: true })
  await shotType.getByRole('button', { name: categoryLabel(template.category), exact: true }).click()
  await library.getByRole('searchbox', { name: 'Search templates' }).fill(template.id)
  await library.getByTestId(`world3d-template-${template.id}`).click()
  await library.getByTestId('world3d-use-shot').click()
  await library.waitFor({ state: 'detached' })
}

async function shootTemplate(page, template, outDir) {
  await openTemplate(page, template)
  await page.waitForTimeout(3_000)
  const expand = page.getByRole('button', { name: 'Expand video', exact: true })
  if (await expand.isVisible()) await expand.click()
  await page.waitForTimeout(5_000)
  const file = path.join(outDir, `${template.id}.png`)
  await page.screenshot({ path: file })
  const exit = page.getByRole('button', { name: 'Exit fullscreen', exact: true })
  if (await exit.isVisible()) await exit.click()
  return file
}

async function publishFile(temporary, destination) {
  const staged = `${destination}.partial`
  try {
    await fs.copyFile(temporary, staged)
    await fs.rename(staged, destination)
  } catch (error) {
    await fs.rm(staged, { force: true })
    throw error
  }
  await fs.rm(temporary, { force: true })
}

async function muxFrames(dir, destination, fps, duration) {
  const temporary = path.join(dir, 'clip.partial.mp4')
  const code = await onceExit(spawn('ffmpeg', [
    '-v', 'error', '-y', '-framerate', String(fps), '-start_number', '1',
    '-i', path.join(dir, 'frame_%06d.png'),
    '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-threads', '1', '-t', duration.toFixed(3), '-movflags', '+faststart', temporary,
  ], { stdio: 'inherit' }))
  if (code !== 0) throw new Error(`ffmpeg exited ${code}.`)
  await publishFile(temporary, destination)
}

async function exportTemplate(context, origin, template, outDir) {
  const studio = context.pages()[0]
  const raw = await studio.evaluate(() => JSON.stringify(window.__world3dDocument || null))
  const document = raw ? JSON.parse(raw) : null
  if (!document || document.templateId !== template.id) throw new Error(`Studio document is not ${template.id}.`)
  const duration = Math.min(6, Number(document.duration) || 6)
  const size = world3dExportSize(document.width, document.height)
  const plan = world3dExportPlan(duration, document.fps || 24)
  const render = await context.newPage()
  const frames = await fs.mkdtemp(path.join(os.tmpdir(), 'atmos-frames-'))
  try {
    await render.goto(`${origin}/world3d-render.html`, { waitUntil: 'domcontentloaded' })
    await render.waitForFunction(() => window.__world3dExport, null, { timeout: 60_000 })
    await render.evaluate(({ scene, size: next }) => window.__world3dExport.load(scene, next), { scene: document, size })
    for (let index = 0; index < plan.times.length; index += 1) {
      const url = await render.evaluate(seconds => window.__world3dExport.frame(seconds), plan.times[index])
      const payload = String(url).split(',')[1]
      if (!payload) throw new Error(`Frame ${index + 1} was not a PNG.`)
      await fs.writeFile(path.join(frames, `frame_${String(index + 1).padStart(6, '0')}.png`), Buffer.from(payload, 'base64'))
      if (index === 0 || (index + 1) % plan.fps === 0) console.log(`${template.id} frame ${index + 1}/${plan.times.length}`)
    }
    await render.evaluate(() => window.__world3dExport.dispose())
    const file = path.join(outDir, `${template.id}.mp4`)
    await muxFrames(frames, file, plan.fps, duration)
    return file
  } finally {
    await render.close()
    await fs.rm(frames, { recursive: true, force: true })
  }
}

async function captureAll(options) {
  const templates = options.ids.map(knownTemplate)
  const outDir = assertOutsideRepo(options.out || defaultCaptureDir(), repoRoot)
  await fs.mkdir(outDir, { recursive: true })
  await buildUi()
  const preview = await startPreview(options.port)
  let browser
  try {
    browser = await chromium.launch({ headless: true, args: SOFTWARE_ARGS })
    const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, locale: 'en-US', baseURL: preview.url })
    const page = await context.newPage()
    await bootStudio(page)
    const renderer = assertSoftwareRenderer(await readRenderer(page))
    console.log(`software renderer: ${renderer}`)
    for (const template of templates) {
      const started = Date.now()
      const png = await shootTemplate(page, template, outDir)
      console.log(`${template.id} png ${png} ${Date.now() - started}ms`)
      if (!options.exportClip) continue
      const startedExport = Date.now()
      const mp4 = await exportTemplate(context, preview.url, template, outDir)
      console.log(`${template.id} mp4 ${mp4} ${Date.now() - startedExport}ms`)
    }
  } finally {
    await browser?.close()
    stopTree(preview.child)
  }
}

async function main() {
  const options = parseCaptureArgs(process.argv.slice(2))
  if (options.help) { console.log(usage()); return }
  await captureAll(options)
}

const calledDirectly = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (calledDirectly) {
  main().catch(error => {
    console.error(error instanceof Error ? error.message : error)
    process.exitCode = 1
  })
}
