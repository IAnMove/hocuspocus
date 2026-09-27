import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

test('clicking Approve directly from edited notes persists both in order', async ({ page }) => {
  const session = await gotoApp(page)
  const saved = {
    pipeline_id: 'review-click', status: 'completed', pipeline_type: 'short_film',
    created_at: '2026-09-12T12:00:00Z', image_model: '', video_model: '', output_files: [],
    clips: [{ index: 0, status: 'completed', video_filename: 'review.mp4',
      video_prompt: 'Literal prompt', tag: '', review_notes: '',
      video_attempts: [{ id: 'review-take', filename: 'review.mp4' }] }],
  }
  const writes: Array<Array<{ type: string; notes?: string; tag?: string }>> = []
  let release!: () => void
  const firstSave = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/director/pipelines**', async route => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/review')) {
      const body = route.request().postDataJSON()
      expect(body.workspace).toBe('default')
      writes.push(body.commands)
      if (writes.length === 1) await firstSave
      for (const command of body.commands) {
        if (command.type === 'note_clip') saved.clips[0].review_notes = command.notes
        if (command.type === 'tag_clip') saved.clips[0].tag = command.tag
      }
      await route.fulfill({ json: saved })
    } else if (pathname.endsWith('/review-click')) {
      await route.fulfill({ json: saved })
    } else if (pathname.endsWith('/pipelines')) {
      await route.fulfill({ json: { total: 1, pipelines: [{ id: saved.pipeline_id,
        ...saved, clip_count: 1, scene_description: 'Review click regression' }] } })
    } else await route.fallback()
  })
  await page.route('**/api/v1/outputs/review.mp4*', route => route.fulfill({ status: 204 }))
  try {
    await page.getByRole('button', { name: 'Production', exact: true }).click()
    await page.getByRole('tab', { name: 'Productions', exact: true }).click()
    await page.locator('summary').filter({ hasText: 'Production review' }).click()
    const review = page.getByRole('region', { name: 'Production review', exact: true })
    await review.getByRole('textbox', { name: 'Notes', exact: true }).fill('Keep this take')
    // Native pointer events: blur starts the first save before the click lands.
    await review.getByRole('button', { name: 'Approve', exact: true }).click()
    await expect.poll(() => writes.length).toBe(1)
    release()
    await expect.poll(() => writes.length).toBe(2)
    await expect.poll(() => saved.clips[0].tag).toBe('good')
    expect(saved.clips[0].review_notes).toBe('Keep this take')
    expect(writes[0]).toContainEqual(expect.objectContaining({ type: 'note_clip', notes: 'Keep this take' }))
    expect(writes[1]).toContainEqual(expect.objectContaining({ type: 'tag_clip', tag: 'good' }))
  } finally { release() }
  await closeApp(page, session)
})
