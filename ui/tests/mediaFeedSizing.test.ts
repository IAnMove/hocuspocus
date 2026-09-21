import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import test from 'node:test'

import {
  estimatedMediaFeedItemHeight,
  isCollapsedMediaFeedMeasurement,
  mediaFeedMaxPreviewHeight,
  mediaFeedStillAspectRatio,
  MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO,
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
  assert.match(itemSource, /maxMediaHeight == null \? \{\} : \{ maxHeight:/)
})

test('stills and videos do not sit in a 16:9 letterbox', async () => {
  const itemSource = await fs.readFile(new URL('../src/components/MainContent/MediaFeedItem.tsx', import.meta.url), 'utf8')
  const bodySource = await fs.readFile(new URL('../src/components/MainContent/FeedMediaBody.tsx', import.meta.url), 'utf8')
  assert.match(itemSource, /naturalFrame \? '' : 'aspect-video'/)
  assert.match(itemSource, /naturalFrame \? \{ aspectRatio: stillAspect \}/)
  assert.match(itemSource, /<FeedMediaBody/)
  assert.match(bodySource, /file.type === 'video'/)
  assert.match(bodySource, /onLoadedMetadata/)
  assert.doesNotMatch(itemSource, /key=\{isActive \? file\.url/)
})

test('still cards reserve 16:9 until the image reports its natural size', () => {
  assert.equal(mediaFeedStillAspectRatio(), MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO)
  assert.equal(mediaFeedStillAspectRatio(0, 0), MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO)
  assert.equal(mediaFeedStillAspectRatio(1920, 1080), 1920 / 1080)
  assert.equal(mediaFeedStillAspectRatio(1080, 1920), 1080 / 1920)
})

test('collapsed still measurements stay out of the virtualizer', () => {
  assert.equal(isCollapsedMediaFeedMeasurement(48), true)
  assert.equal(isCollapsedMediaFeedMeasurement(40), true)
  assert.equal(isCollapsedMediaFeedMeasurement(Number.NaN), true)
  assert.equal(isCollapsedMediaFeedMeasurement(144), false)
  assert.equal(isCollapsedMediaFeedMeasurement(420), false)
})
