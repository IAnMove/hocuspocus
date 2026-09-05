import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

const GRAPH = {
  nodes: [
    { id: 'ui.story', layer: 'ui', label: 'Story Lab', detail: 'Story panel', evidence: [{ file: 'ui/src/features/stories/StoryLabPanel.tsx', line: 12 }] },
    { id: 'api.director', layer: 'api', label: 'Director API', detail: 'Director route', evidence: [{ file: 'ui/src/api/director.ts', line: 22 }] },
  ],
  edges: [{ source: 'ui.story', target: 'api.director', kind: 'http', label: 'POST', weight: 1, evidence: [{ file: 'ui/src/api/director.ts', line: 22 }] }],
  meta: {
    schema_version: 1,
    scope: 'Story Lab → Director',
    source_commit: '0123456789abcdef0123456789abcdef01234567',
    dirty: false,
    source_hash: 'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    generated_by: 'e2e fixture',
    limitations: ['Fixture graph only'],
    warnings: [],
  },
}

test('opens the developer architecture viewer against a simulated static graph', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('hocuspocus-developer-mode-v1', '1')
  })
  await page.route('**/dev/architecture/story-director-audio.json', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(GRAPH),
  }))
  const session = await gotoApp(page)
  await page.getByRole('button', { name: 'Media' }).click()
  await page.getByRole('tab', { name: 'Internal dev audit' }).click()
  await expect(page.getByRole('tab', { name: 'Architecture' })).toBeVisible()
  await page.getByRole('tab', { name: 'Architecture' }).click()
  await expect(page.getByText('Architecture map')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Story Lab (ui)' })).toBeVisible()
  await expect(page.getByText('Fixture graph only')).toBeVisible()
  await page.screenshot({ path: 'test-results/architecture-viewer.png', fullPage: true })
  await closeApp(page, session)
})

test('renders the generated architecture artifact with a readable graph viewport', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('hocuspocus-developer-mode-v1', '1')
  })
  const session = await gotoApp(page)
  await page.getByRole('button', { name: 'Media' }).click()
  await page.getByRole('tab', { name: 'Internal dev audit' }).click()
  await page.getByRole('tab', { name: 'Architecture' }).click()
  await expect(page.getByText('Architecture map')).toBeVisible()
  const graph = page.getByRole('img', { name: /Architecture graph/ })
  await expect(graph).toBeVisible()
  const graphMetrics = await graph.evaluate(element => {
    const parent = element.parentElement
    return {
      height: element.getBoundingClientRect().height,
      scrollWidth: parent?.scrollWidth || 0,
      clientWidth: parent?.clientWidth || 0,
      interactiveItems: element.querySelectorAll('[role="button"]').length,
    }
  })
  expect(graphMetrics.height).toBeGreaterThan(200)
  expect(graphMetrics.interactiveItems).toBeGreaterThan(20)
  expect(graphMetrics.scrollWidth).toBeGreaterThan(graphMetrics.clientWidth)
  await page.screenshot({ path: 'test-results/architecture-viewer-generated.png', fullPage: true })
  await closeApp(page, session)
})
