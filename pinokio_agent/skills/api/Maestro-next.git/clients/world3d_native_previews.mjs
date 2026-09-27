// Inspect imported shot documents through the installed HocusPocus editor.
// Produces native stills and public scene-save requests; does not render video.
import fs from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
const arg = name => process.argv[process.argv.indexOf(name) + 1]
for (const name of ['--cdp', '--app-url', '--plan', '--output-dir']) if (!process.argv.includes(name)) throw Error(`Missing ${name}`)
const plan = JSON.parse(await fs.readFile(arg('--plan'), 'utf8'))
const out = arg('--output-dir'); await fs.mkdir(out, { recursive: true })
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : 'playwright')
const browser = await chromium.connectOverCDP(arg('--cdp'))
const page = browser.contexts()[0].pages().find(p => p.url().startsWith(arg('--app-url')))
if (!page) throw Error('Open the app in this browser before running previews')
await page.bringToFront()
await page.setViewportSize({ width: 1440, height: 1000 })
async function openStudio() {
  await page.goto(arg('--app-url'), { waitUntil: 'domcontentloaded', timeout: 120000 })
  await page.getByRole('button', { name: /^(Estudios|Studios)$/ }).waitFor({ state: 'visible', timeout: 120000 })
  await page.locator('.hp-intro-root').waitFor({ state: 'hidden', timeout: 120000 })
  const enter = page.getByRole('button', { name: /^(Enter the studio|Entrar al estudio)$/ })
  if (await enter.isVisible().catch(() => false)) await enter.click()
  await page.getByRole('button', { name: /^(Estudios|Studios)$/ }).click()
  await page.getByRole('tab', { name: /^(Vídeo 3D|Video 3D)$/ }).click()
  await page.waitForFunction(() => !!window.__world3dStage)
}
await openStudio()
for (const shot of plan.shots) {
  const stem = String(shot.number).padStart(2, '0'), doc = shot.document
  if (doc.texts?.length || doc.clipNumber) throw Error('This still client requires a document without text overlays')
  const savedPath = path.join(out, `${stem}-save-request.json`)
  const cached = await fs.readFile(savedPath, 'utf8').then(JSON.parse).catch(() => null)
  if (cached?.workspace === plan.workspace && cached?.name === shot.title &&
      JSON.stringify(cached.document) === JSON.stringify(doc) &&
      await fs.stat(path.join(out, `${stem}.png`)).then(s => s.size > 0).catch(() => false)) {
    console.log(JSON.stringify({ number: shot.number, status: 'verified-preview-exists' }))
    continue
  }
  const file = path.resolve(out, stem + '.world3d.json')
  await fs.writeFile(file, JSON.stringify(doc, null, 2))
  let preview
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      if (attempt) await openStudio()
      await page.getByTestId('world3d-load-shot').setInputFiles(file)
      await page.getByTestId('scene3d-preview-picture').scrollIntoViewIfNeeded()
      await page.waitForFunction(d => window.__world3dStage?.ready(d.slots), doc, { timeout: 90000 })
      preview = await page.evaluate(async d => {
        const h = window.__world3dStage; h.beginExport(d); h.setExportSize(d.width, d.height)
        try {
          const t = Math.min(d.duration / 2, 2); await h.prepareFrame?.(t, d)
          const source = h.paint(t, d); if (!source) throw Error('No native stage canvas')
          const canvas = document.createElement('canvas'); canvas.width = d.width; canvas.height = d.height
          canvas.getContext('2d').drawImage(source, 0, 0); return canvas.toDataURL('image/png')
        } finally { h.endExport() }
      }, doc)
      break
    } catch (error) {
      if (attempt === 2 || !/timeout/i.test(String(error))) throw error
      console.log(JSON.stringify({ number: shot.number, status: 'retry-native-media-load', attempt: attempt + 1 }))
    }
  }
  await fs.writeFile(path.join(out, `${stem}.png`), Buffer.from(preview.split(',')[1], 'base64'))
  await fs.writeFile(path.join(out, `${stem}-save-request.json`), JSON.stringify({ workspace: plan.workspace, name: shot.title, document: doc, preview }))
  console.log(JSON.stringify({ number: shot.number, title: shot.title, status: 'native-preview' }))
}
await browser.close()
