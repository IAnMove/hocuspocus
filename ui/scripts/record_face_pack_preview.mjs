#!/usr/bin/env node
import { chromium } from 'playwright'
import { mkdir, rm, writeFile } from 'fs/promises'
import { join } from 'path'
import { spawnSync } from 'child_process'

const HOST = process.env.FACE_PACK_PREVIEW || 'http://127.0.0.1:4199'
const OUT = process.env.FACE_PACK_OUT || '/tmp/hocus-action-sets-20260911/outputs/face-pack-preview'
const PUB = '/tmp/hocus-action-sets-20260911/ui/public/examples/face-pack'
const WAV = join(PUB, 'neutral-vowels.wav')
const FPS = 12
const DURATION = 8
const SHOTS = process.env.FACE_PACK_SHOTS
  ? process.env.FACE_PACK_SHOTS.split(',')
  : ['felt-talk', 'pumpkin-talk', 'cat-talk']

const ffmpeg = (...args) => {
  const result = spawnSync('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', ...args], { stdio: 'inherit' })
  if (result.status !== 0) throw new Error(`ffmpeg ${args.join(' ')}`)
}

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=gl'] })
for (const shot of SHOTS) {
  const frames = join(OUT, `frames-${shot}`)
  await rm(frames, { recursive: true, force: true })
  await mkdir(frames, { recursive: true })
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`${HOST}/face-pack-preview.html?shot=${shot}&video=1`, { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForFunction(() => window.facePack?.sceneReady === true, null, { timeout: 15000 })
  await page.waitForTimeout(800)
  await page.evaluate(() => window.facePack.setSceneSeconds(0.55))
  await page.waitForFunction(() => window.facePack.viseme() === 'A', null, { timeout: 5000 })
  const seen = new Set()
  for (let i = 0; i < FPS * DURATION; i++) {
    const seconds = i / FPS
    await page.evaluate(value => window.facePack.setSceneSeconds(value), seconds)
    await page.waitForTimeout(20)
    seen.add(await page.evaluate(() => window.facePack.viseme()))
    const png = await page.locator('#view canvas').screenshot()
    await writeFile(join(frames, `f-${String(i).padStart(4, '0')}.png`), png)
  }
  await page.close()
  if (errors.length) throw new Error(`${shot}: ${errors.join('; ')}`)
  if (seen.size < 3) throw new Error(`${shot}: visemes did not change (${[...seen]})`)
  const mp4 = join(PUB, `${shot}.mp4`)
  ffmpeg('-framerate', String(FPS), '-i', join(frames, 'f-%04d.png'), '-i', WAV,
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '96k', '-t', String(DURATION),
    '-movflags', '+faststart', mp4)
  console.log(shot, 'visemes', [...seen].join(','), mp4)
}
await browser.close()
