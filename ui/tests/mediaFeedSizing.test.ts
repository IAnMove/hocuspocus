import assert from 'node:assert/strict'
import test from 'node:test'

import {
  estimatedMediaFeedItemHeight,
  isCollapsedMediaFeedMeasurement,
  mediaFeedMaxPreviewHeight,
  mediaFeedStillAspectRatio,
  MEDIA_FEED_PLACEHOLDER_ASPECT_RATIO,
} from '../src/components/MainContent/mediaFeedSizing'

test('wide media previews leave room for the complete card inside the feed viewport', () => {
  assert.equal(mediaFeedMaxPreviewHeight(900), 764)
  assert.equal(estimatedMediaFeedItemHeight(2560, 900), 868)
})

test('ordinary media previews preserve their 16:9 height when it fits', () => {
  assert.equal(mediaFeedMaxPreviewHeight(900), 764)
  assert.equal(estimatedMediaFeedItemHeight(800, 900), 554)
})

test('very short viewports retain a usable media preview', () => {
  assert.equal(mediaFeedMaxPreviewHeight(150), 96)
  assert.equal(estimatedMediaFeedItemHeight(800, 150), 200)
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
  assert.equal(isCollapsedMediaFeedMeasurement(200), false)
  assert.equal(isCollapsedMediaFeedMeasurement(420), false)
})
