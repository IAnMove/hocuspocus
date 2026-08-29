import assert from 'node:assert/strict'
import test from 'node:test'
import { galleryListQuery, jobFitsGalleryFilter } from '../src/lib/galleryListQuery.ts'
import type { GenerationJob } from '../src/types'

test('gallery list query asks the server for 3D and scene files by type', () => {
  assert.equal(galleryListQuery('model3d').mediaType, 'model3d')
  assert.equal(galleryListQuery('scenes').mediaType, 'scene')
  assert.equal(galleryListQuery('images').mediaType, 'image')
  assert.equal(galleryListQuery('videos').mediaType, 'video')
  assert.equal(galleryListQuery('trailers').resultKind, 'trailer')
  assert.equal(galleryListQuery('all').mediaType, undefined)
  assert.equal(galleryListQuery('avatars').editsOnly, true)
  assert.equal(galleryListQuery('avatars').useServerList, true)
  assert.equal(galleryListQuery('images').editsOnly, false)
})

test('video queue tiles stay off Images, 3D and Scenes', () => {
  const videoJob = { generationDetails: { generation_mode: 'video' } } as GenerationJob
  assert.equal(jobFitsGalleryFilter(videoJob, 'all'), true)
  assert.equal(jobFitsGalleryFilter(videoJob, 'videos'), true)
  assert.equal(jobFitsGalleryFilter(videoJob, 'images'), false)
  assert.equal(jobFitsGalleryFilter(videoJob, 'model3d'), false)
  assert.equal(jobFitsGalleryFilter(videoJob, 'scenes'), false)
  assert.equal(jobFitsGalleryFilter(videoJob, 'trailers'), true)
  assert.equal(jobFitsGalleryFilter(videoJob, 'avatars'), false)
  const editJob = { generationDetails: { generation_mode: 'video', edit_sub_mode: 'retake' } } as GenerationJob
  assert.equal(jobFitsGalleryFilter(editJob, 'avatars'), true)
  const avatarJob = { generationDetails: { generation_mode: 'avatar' } } as GenerationJob
  assert.equal(jobFitsGalleryFilter(avatarJob, 'avatars'), true)
})
