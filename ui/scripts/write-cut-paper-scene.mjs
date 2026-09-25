import { mkdirSync, writeFileSync } from 'node:fs'
import { compileCutPaperPilotScene, compileCutPaperShot } from '../src/features/cutPaper/pilot.ts'
import { serializeSceneFile } from '../src/lib/sceneFile.ts'

const root = new URL('../public/examples/cut-paper/', import.meta.url)
mkdirSync(new URL('shots/', root), { recursive: true })
mkdirSync(new URL('shots/en/', root), { recursive: true })
for (const locale of ['es', 'en']) {
  const full = compileCutPaperPilotScene(locale)
  if (locale === 'es') writeFileSync(new URL('tijeral-la-fuente.maestro-scene.json', root), serializeSceneFile(full))
  else writeFileSync(new URL('shots/en/tijeral-la-fuente.maestro-scene.json', root), serializeSceneFile(full))
  for (const shot of ['plaza', 'talk', 'sticker']) {
    const scene = compileCutPaperShot(shot, locale)
    const name = shot === 'plaza' ? '01-plaza' : shot === 'talk' ? '02-talk' : '03-sticker'
    writeFileSync(new URL(`${locale === 'en' ? 'shots/en/' : 'shots/'}${name}.maestro-scene.json`, root), serializeSceneFile(scene))
    console.log(locale, name, scene.duration, scene.audioTracks?.[0]?.filename)
  }
}
