import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'

import {
  estimatedMediaFeedItemHeight,
  mediaFeedMaxPreviewHeight,
} from '../src/components/MainContent/mediaFeedSizing'

test('wide media previews leave room for the complete card inside the feed viewport', () => {
  assert.equal(mediaFeedMaxPreviewHeight(900), 788)
  assert.equal(estimatedMediaFeedItemHeight(2560, 900), 836)
})

test('ordinary media previews preserve their 16:9 height when it fits', () => {
  assert.equal(mediaFeedMaxPreviewHeight(900), 788)
  assert.equal(estimatedMediaFeedItemHeight(800, 900), 498)
})

test('very short viewports retain a usable media preview', () => {
  assert.equal(mediaFeedMaxPreviewHeight(150), 96)
  assert.equal(estimatedMediaFeedItemHeight(800, 150), 144)
})

test('the feed applies the same viewport cap to rendered media and virtualization', async () => {
  const [feedSource, itemSource] = await Promise.all([
    fs.readFile(new URL('../src/components/MainContent/MainContent.tsx', import.meta.url), 'utf8'),
    fs.readFile(new URL('../src/components/MainContent/MediaFeedItem.tsx', import.meta.url), 'utf8'),
  ])

  assert.match(feedSource, /estimatedMediaFeedItemHeight\(containerWidth, containerHeight\)/)
  assert.match(feedSource, /maxMediaHeight=\{maxMediaHeight\}/)
  assert.match(feedSource, /Math\.abs\(newHeight - prevHeight\) > 2/)
  assert.match(itemSource, /style=\{maxMediaHeight == null \? undefined : \{ maxHeight:/)
})
