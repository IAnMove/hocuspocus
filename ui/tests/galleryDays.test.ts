import assert from 'node:assert/strict'
import test from 'node:test'
import { daySections, galleryDayLabel } from '../src/components/MainContent/galleryDays.ts'
import { anchorAt, buildGalleryLayout, neighborIndex, SECTION_HEADER_HEIGHT } from '../src/components/MainContent/mediaGalleryLayout.ts'

const words = { today: 'Hoy', yesterday: 'Ayer' }
const now = new Date(2026, 8, 23, 18, 0)
const at = (day: number, hour = 12) => new Date(2026, 8, day, hour).getTime() / 1000

test('day labels read today, yesterday, then a localized date', () => {
  assert.equal(galleryDayLabel(new Date(2026, 8, 23, 1), now, 'es', words), 'Hoy')
  assert.equal(galleryDayLabel(new Date(2026, 8, 22, 23), now, 'es', words), 'Ayer')
  assert.equal(galleryDayLabel(new Date(2026, 8, 16), now, 'es', words), 'Miércoles, 16 de septiembre')
  assert.equal(galleryDayLabel(new Date(2026, 8, 16), now, 'en', { today: 'Today', yesterday: 'Yesterday' }), 'Wednesday, September 16')
  assert.match(galleryDayLabel(new Date(2025, 0, 2), now, 'es', words), /2025/)
})

test('sections start where the calendar day changes, in list order', () => {
  const newest = [at(23, 15), at(23, 9), at(22), at(16, 20), at(16, 8)].map(created_at => ({ created_at }))
  assert.deepEqual(daySections(newest, 'es', words, now).map(section => [section.start, section.label]),
    [[0, 'Hoy'], [2, 'Ayer'], [3, 'Miércoles, 16 de septiembre']])
  assert.deepEqual(daySections([...newest].reverse(), 'es', words, now).map(section => section.start), [0, 2, 3])
  assert.equal(daySections([{ created_at: at(10), completed_at: at(23) }], 'es', words, now)[0].label, 'Hoy')
  assert.deepEqual(daySections([], 'es', words, now), [])
})

test('headings restart grid rows and are skipped by anchors and arrows', () => {
  const items = Array.from({ length: 9 }, (_, index) => ({ name: `i${index}`, type: 'image' as const, width: 100, height: 100 }))
  const sections = [{ start: 0, label: 'Hoy' }, { start: 4, label: 'Ayer' }]
  const layout = buildGalleryLayout('grid', items, 1236, 700, { sections })
  const kinds = layout.blocks.map(block => block.header ?? block.cells.map(cell => cell.index).join(','))
  assert.deepEqual(kinds, ['Hoy', '0,1,2,3', 'Ayer', '4,5,6,7,8'])
  assert.equal(layout.blocks[0].height, SECTION_HEADER_HEIGHT)
  assert.deepEqual(anchorAt(layout, items, 0), { name: 'i0', within: 0 })
  assert.equal(neighborIndex(layout, 1, 'down'), 5, 'down skips the heading into the next day')
  assert.equal(neighborIndex(layout, 5, 'up'), 1)
  assert.notEqual(layout.shape, buildGalleryLayout('grid', items, 1236, 700).shape)
  const mosaic = buildGalleryLayout('masonry', items, 1236, 700, { sections })
  assert.deepEqual(mosaic.blocks.filter(block => block.header).map(block => block.header), ['Hoy', 'Ayer'])
  assert.equal(mosaic.blocks[mosaic.blockOf[4]].cells[0].index, 4, 'each day starts its own row')
})
