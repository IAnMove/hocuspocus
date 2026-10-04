import { readFileSync } from 'node:fs'
import { runSeriesShot, type SeriesShotPayload } from './seriesShot.ts'

if (process.argv.some(arg => arg.endsWith('series-shot.ts'))) {
  const payload = JSON.parse(readFileSync(0, 'utf8')) as SeriesShotPayload
  process.stdout.write(`${JSON.stringify(runSeriesShot(payload))}\n`)
}
