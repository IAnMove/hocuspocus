// What a review render leaves next to each MP4: a contact sheet, and one review.json for the whole run.
import { execFileSync } from 'node:child_process'
import fs from 'node:fs/promises'
import path from 'node:path'

export const SHEET_COLUMNS = 3
export const SHEET_ROWS = 2

/** Frames in the middle of equal slices of the shot, so a card's entrance and exit both show. */
export function sheetTimes(duration, count = SHEET_COLUMNS * SHEET_ROWS) {
  return Array.from({ length: count }, (_, index) => Number((duration * (index + 0.5) / count).toFixed(3)))
}

/** A 3x2 contact sheet of the rendered MP4, 426 pixels a frame, painted by ffmpeg from the real export. */
export function contactSheet(video, sheet, duration) {
  const count = SHEET_COLUMNS * SHEET_ROWS
  const first = sheetTimes(duration, count)[0]
  execFileSync('ffmpeg', [
    '-y', '-v', 'error', '-ss', String(first), '-i', video,
    '-vf', `fps=${count}/${duration},scale=426:-2,tile=${SHEET_COLUMNS}x${SHEET_ROWS}`,
    '-frames:v', '1', sheet,
  ])
}

/** One row per card in review.json: its files, its duration, the assets and controls it was rendered with. */
export function indexRow({ id, scene, duration, assets, controls, variant }) {
  return {
    id,
    templateId: scene.narrative?.templateId ?? id,
    status: 'rendered-not-approved',
    file: `${id}.mp4`,
    sheet: `${id}.sheet.png`,
    poster: `${id}.png`,
    metadata: `${id}.json`,
    duration,
    variant,
    controls: controls ?? {},
    assets: assets.map(asset => ({ slot: asset.slot, type: asset.type, file: asset.file, ...(asset.sha256 ? { sha256: asset.sha256 } : {}) })),
  }
}

export async function writeReviewIndex(directory, { assetsFile, source, rows, failures }) {
  const index = {
    status: 'rendered-not-approved',
    note: 'A render is evidence for review, never an approval: the integrator or the owner sets reviewStatus.',
    assets: assetsFile ?? 'demo art (coral, inline)',
    source,
    cards: rows,
    failures,
  }
  const file = path.join(directory, 'review.json')
  await fs.writeFile(file, JSON.stringify(index, null, 2), { flag: 'wx' })
  return file
}
