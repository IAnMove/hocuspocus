import assert from 'node:assert/strict'
import test from 'node:test'
import { duplicateClipState, frameOffset, moveClip, patchClipExtra } from '../src/features/video-editor/comicEdits.ts'
import { columnCount, layoutComic, type ComicLayoutClip, type ComicPage } from '../src/features/video-editor/comicView.ts'

function clip(id: string, duration: number, width = 1080, height = 1920, focusX?: number, focusY?: number): ComicLayoutClip {
  return { id, duration, width, height, focusX, focusY }
}

function panelsOf(pages: ComicPage[]) {
  return pages.flatMap(page => page.tiers.flatMap(tier => tier.panels))
}

function assertTiersFill(pages: ComicPage[]) {
  const tiers = pages.flatMap(page => page.tiers.map(tier => ({ columns: page.columns, sum: tier.panels.reduce((total, panel) => total + panel.span, 0) })))
  tiers.slice(0, -1).forEach(tier => assert.equal(tier.sum, tier.columns))
  assert.ok(tiers.at(-1)!.sum <= tiers.at(-1)!.columns)
  assert.ok(tiers.every(tier => tier.sum > 0))
}

test('tiers fill, a long clip spans two columns, and the longest clip is a splash', () => {
  const pages = layoutComic([clip('a', 2), clip('b', 1), clip('c', 1), clip('d', 1), clip('e', 5)])
  assert.equal(pages.length, 1)
  assert.equal(pages[0].columns, 3)
  assertTiersFill(pages)
  const panels = panelsOf(pages)
  assert.deepEqual(panels.map(panel => panel.id), ['a', 'b', 'c', 'd', 'e'])
  assert.equal(panels[0].span, 2)
  assert.equal(panels[0].splash, false)
  const splash = panels.find(panel => panel.splash)
  assert.equal(splash?.id, 'e')
  assert.equal(splash?.span, 3)
  assert.equal(pages[0].tiers.at(-1)?.panels.length, 1)
})

test('an even median does not mark a merely longer clip as wide', () => {
  const pages = layoutComic([clip('a', 2), clip('b', 1), clip('c', 1), clip('d', 4), clip('e', 1), clip('f', 10)])
  const panels = panelsOf(pages)
  assert.equal(panels.find(panel => panel.id === 'a')?.span, 1)
  assert.equal(panels.find(panel => panel.id === 'd')?.span, 2)
  assert.equal(panels.find(panel => panel.splash)?.id, 'f')
})

test('a splash waits for the next tier and the row it left is filled', () => {
  const pages = layoutComic([clip('a', 1), clip('b', 1), clip('c', 9)])
  const [first, second] = pages[0].tiers
  assert.equal(first.panels.reduce((total, panel) => total + panel.span, 0), 3)
  assert.deepEqual(second.panels.map(panel => panel.id), ['c'])
  assert.equal(second.panels[0].span, 3)
})

test('the layout is deterministic and cover-crops with focus', () => {
  const input = [clip('a', 1, 1080, 1920, 120, -4), clip('b', 3, 1920, 1080, undefined, 80)]
  assert.deepEqual(layoutComic(input), layoutComic(input))
  const panels = panelsOf(layoutComic(input))
  assert.equal(panels[0].focusX, 100)
  assert.equal(panels[0].focusY, 0)
  assert.equal(panels[1].focusX, 50)
  assert.equal(panels[1].focusY, 80)
})

test('one, seven and a hundred vertical clips', () => {
  const one = layoutComic([clip('only', 4)])
  assert.equal(one.length, 1)
  assert.equal(one[0].tiers.length, 1)
  assert.equal(one[0].tiers[0].panels[0].span, 3)
  assert.equal(one[0].tiers[0].panels[0].splash, true)

  const seven = layoutComic(Array.from({ length: 7 }, (_, index) => clip(`c${index}`, 2)))
  assert.equal(seven.length, 1)
  assert.equal(seven[0].tiers.length, 3)
  assert.equal(seven[0].tiers[0].panels[0].id, 'c0')
  assert.equal(seven[0].tiers[0].panels[0].splash, true)
  assert.equal(panelsOf(seven).length, 7)
  assertTiersFill(seven)

  const hundred = layoutComic(Array.from({ length: 100 }, (_, index) => clip(`c${index}`, 1)))
  assert.equal(hundred.length, 12)
  assert.equal(hundred[0].columns, 3)
  assert.equal(hundred.at(-1)?.tiers.length, 1)
  assert.equal(panelsOf(hundred).length, 100)
  assert.deepEqual(panelsOf(hundred).map(panel => panel.id), Array.from({ length: 100 }, (_, index) => `c${index}`))
  assertTiersFill(hundred)
})

test('horizontal frames use two columns and a zero duration is not wide', () => {
  const horizontal = layoutComic([clip('a', 1, 1920, 1080), clip('b', 1, 1920, 1080), clip('c', 1, 1920, 1080), clip('d', 1, 1920, 1080)])
  assert.equal(columnCount([clip('s', 1, 100, 100)]), 3)
  assert.equal(horizontal[0].columns, 2)
  assert.equal(horizontal[0].tiers[0].panels[0].span, 2)
  const flat = layoutComic([clip('a', 0), clip('b', 0), clip('c', 0), clip('d', 0)])
  const spans = panelsOf(flat).map(panel => panel.span)
  assert.deepEqual(spans, [3, 1, 1, 1])
})

test('moveClip matches a timeline drop before or after another clip', () => {
  const clips = [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }]
  assert.deepEqual(moveClip(clips, 'a', 3).map(item => item.id), ['b', 'c', 'a', 'd'])
  assert.deepEqual(moveClip(clips, 'd', 0).map(item => item.id), ['d', 'a', 'b', 'c'])
  assert.deepEqual(moveClip(clips, 'b', 2).map(item => item.id), ['a', 'b', 'c', 'd'])
  assert.deepEqual(moveClip(clips, 'missing', 1), clips)
})

test('patch and duplicate keep lyric and comic on the montage extras', () => {
  const extra = patchClipExtra({ takes: [{ id: 't1' }], lyric: '  old  ' }, { lyric: '  new line  ', comic: { text: 'bubble', frame: -2 } })
  assert.equal(extra?.lyric, 'new line')
  assert.equal(extra?.comic?.text, 'bubble')
  assert.equal(extra?.comic?.frame, 0)
  assert.equal(extra?.takes?.length, 1)
  assert.equal(patchClipExtra(extra, { lyric: '   ' })?.lyric, undefined)
  assert.equal(patchClipExtra({ lyric: 'x' }, { lyric: 'x'.repeat(600) })?.lyric?.length, 500)
  assert.equal(patchClipExtra({ comic: { text: 'caption', frame: 1 } }, { comic: { text: null, frame: null } }), undefined)

  const copied = duplicateClipState({ id: 'c1', name: 'shot', source: 'a.mp4' }, { lyric: 'hi', comic: { text: 'caption' }, takes: [{ id: 't1' }] }, 'c2')
  assert.equal(copied.clip.id, 'c2')
  assert.equal(copied.clip.name, 'shot (copy)')
  assert.deepEqual(copied.extra, { lyric: 'hi', comic: { text: 'caption' } })
  assert.equal(duplicateClipState({ id: 'c1', name: 'shot (copy)' }, { takes: [{ id: 't1' }] }, 'c3').extra, undefined)
  assert.equal(frameOffset(1.5, 4), 2.5)
  assert.equal(frameOffset(3, 1), 0)
})
