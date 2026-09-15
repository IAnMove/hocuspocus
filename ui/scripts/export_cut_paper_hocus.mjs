#!/usr/bin/env node
/** Open each Tijeral shot in Video 2.5D and click HocusPocus Export MP4. */
import { chromium } from 'playwright'
import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const outDir = process.env.HOCUS_EXPORT_DIR || join(root, '..', 'outputs', 'tijeral-clips')
const base = process.env.HOCUS_UI || 'http://127.0.0.1:4210'
const lang = process.env.HOCUS_LANG === 'en' ? 'en' : 'es'
const shotDir = lang === 'en' ? join(root, 'public/examples/cut-paper/shots/en') : join(root, 'public/examples/cut-paper/shots')
const suffix = lang === 'en' ? '-en' : ''
const shots = [
  [`01-plaza${suffix}`, join(shotDir, '01-plaza.maestro-scene.json')],
  [`02-talk${suffix}`, join(shotDir, '02-talk.maestro-scene.json')],
  [`03-sticker${suffix}`, join(shotDir, '03-sticker.maestro-scene.json')],
]

await mkdir(outDir, { recursive: true })
const browser = await chromium.launch({
  headless: true,
  args: ['--use-gl=angle', '--enable-webgl', '--ignore-gpu-blocklist'],
})
const context = await browser.newContext({ acceptDownloads: true, viewport: { width: 1600, height: 1000 } })
await context.addInitScript(() => {
  window.localStorage.setItem('hocuspocus-ui-language', 'en')
  window.localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
})
const page = await context.newPage()
page.on('console', msg => {
  if (msg.type() === 'error') console.error('PAGE', msg.text())
})
await page.emulateMedia({ reducedMotion: 'reduce' })
page.setDefaultTimeout(120_000)

async function dismissChrome() {
  for (const name of [/skip/i, /enter the studio/i, /entrar al estudio/i]) {
    const button = page.getByRole('button', { name })
    if (await button.count()) await button.first().click({ timeout: 2500, force: true }).catch(() => {})
  }
  await page.locator('.hp-intro-root').waitFor({ state: 'hidden', timeout: 15000 }).catch(() => {})
  await page.evaluate(() => {
    document.querySelectorAll('.hp-intro-root').forEach(node => node.remove())
    document.querySelectorAll('div.fixed.inset-0').forEach(node => {
      const text = node.textContent || ''
      if (/What's new|Enter the studio|HocusPocus is starting/.test(text) && node instanceof HTMLElement) {
        node.style.display = 'none'
        node.remove()
      }
    })
  })
}

try {
  await page.goto(base, { waitUntil: 'domcontentloaded' })
  await dismissChrome()
  await page.waitForTimeout(600)
  await dismissChrome()
  await page.getByRole('button', { name: /Studios|Estudios/i }).click({ timeout: 20000, force: true })
  await page.getByRole('tab', { name: /Video 2\.5D|2\.5D/i }).click({ timeout: 20000, force: true })
  await page.getByRole('button', { name: /Export MP4|Exportar MP4/i }).waitFor({ timeout: 30000 })
  console.log('animator open')

  for (const [name, file] of shots) {
    console.log('import', name)
    const jsonInput = page.locator('input[accept="application/json,.json"]').last()
    await jsonInput.setInputFiles(file)
    await page.waitForTimeout(1500)
    await page.waitForFunction(() => {
      const images = [...document.querySelectorAll('img')]
      const ours = images.filter(img => /cut-paper/.test(img.src))
      return ours.length > 0 && ours.every(img => img.complete && img.naturalWidth > 8)
    }, { timeout: 30000 }).catch(() => console.warn('images not all loaded', name))
    await page.screenshot({ path: join(outDir, `hocus-${name}.png`) })
    const dest = join(outDir, `${name}.mp4`)
    const pending = page.waitForResponse(
      res => res.url().includes('/api/v1/scenes/recordings') && res.request().method() === 'POST',
      { timeout: 300000 },
    )
    await page.getByRole('button', { name: /Export MP4|Exportar MP4/i }).click()
    const res = await pending
    if (!res.ok()) throw new Error(`${name} export HTTP ${res.status()}: ${await res.text()}`)
    const body = await res.json()
    const url = body.url || (body.name ? `/api/v1/file/${encodeURIComponent(body.name)}` : '')
    if (!url) throw new Error(`${name} export returned no file: ${JSON.stringify(body)}`)
    const fileRes = await page.request.get(url.startsWith('http') ? url : new URL(url, base).toString())
    if (!fileRes.ok()) throw new Error(`${name} download HTTP ${fileRes.status()}`)
    await writeFile(dest, Buffer.from(await fileRes.body()))
    console.log('exported', name, dest, body.name || '')
  }
  console.log('done')
} catch (error) {
  await page.screenshot({ path: join(outDir, 'export-debug.png'), fullPage: true }).catch(() => {})
  throw error
} finally {
  await browser.close().catch(() => {})
}
