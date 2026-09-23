import type { Scene3DDocument } from '../types'
import { crtSlot, PIXEL_TV_CLIP } from './pixelTemplates'

/** Every screen plays the chosen slot's recording; sizes, styles and tube
 *  colours stay as they were. */
export function applyScreenToAllTvs(document: Scene3DDocument, sourceId: string): Scene3DDocument {
  const source = document.slots.find(slot => slot.id === sourceId)?.screen
  if (!source) return document
  return {
    ...document,
    slots: document.slots.map(slot => slot.id === sourceId || slot.media !== 'screen' || !slot.screen ? slot : {
      ...slot, screen: { ...slot.screen, sourceUrl: source.sourceUrl, sourceRef: source.sourceRef, media: source.media, poseSequence: undefined },
    }),
  }
}

/** A new CRT beside the others, playing what the first TV plays. */
export function addTv(document: Scene3DDocument): Scene3DDocument {
  const screens = document.slots.filter(slot => slot.media === 'screen')
  const taken = new Set(document.slots.map(slot => slot.id))
  let n = screens.length + 1
  while (taken.has(`tv-${n}`)) n++
  const first = screens.find(slot => slot.screen?.sourceUrl)?.screen
  const x = screens.length ? Math.max(...screens.map(slot => slot.position[0])) + 1.4 : 0
  const slot = crtSlot(`tv-${n}`, [x, 0, -1], 0, 1.1, 0, first?.sourceUrl ?? PIXEL_TV_CLIP)
  if (first && slot.screen) slot.screen = { ...slot.screen, media: first.media, sourceRef: first.sourceRef }
  return { ...document, slots: [...document.slots, slot] }
}
