import { expect, test } from '@playwright/test'
import { closeApp, gotoApp } from '../helpers/gotoApp'

for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
  test(`Help loads on demand and supports keyboard navigation at ${viewport.width}px`, async ({ page }) => {
    const session = await gotoApp(page)
    await page.getByRole('button', { name: 'Close Ask to the Wizard' }).click()
    await page.setViewportSize(viewport)
    const opener = page.getByRole('button', { name: 'Open the HocusPocus tutorial' })
    await expect(page.getByRole('dialog', { name: 'How to use HocusPocus' })).toHaveCount(0)
    await opener.focus()
    await page.keyboard.press('Enter')

    const dialog = page.getByRole('dialog', { name: 'How to use HocusPocus' })
    await expect(dialog).toBeVisible()
    const language = dialog.getByRole('combobox', { name: 'Tutorial language' })
    await expect(language).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(dialog.getByRole('link', { name: 'Example outputs' })).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(language).toBeFocused()

    for (const image of await dialog.getByRole('img').all()) {
      await expect(image).toHaveJSProperty('complete', true)
      await expect(image).not.toHaveJSProperty('naturalWidth', 0)
    }
    const panel = await dialog.locator(':scope > div').boundingBox()
    expect(panel).not.toBeNull()
    expect(panel!.x).toBeGreaterThanOrEqual(0)
    expect(panel!.x + panel!.width).toBeLessThanOrEqual(viewport.width)
    expect(panel!.y + panel!.height).toBeLessThanOrEqual(viewport.height)

    await dialog.getByRole('link', { name: 'Example outputs' }).click()
    await expect(dialog.getByRole('heading', { name: 'Example outputs from this machine' })).toBeInViewport()
    await language.selectOption('es')
    const spanishDialog = page.getByRole('dialog', { name: 'Cómo usar HocusPocus' })
    await expect(spanishDialog).toBeVisible()
    await expect(page.getByRole('button', { name: 'Abrir el tutorial de HocusPocus' })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(spanishDialog).toHaveCount(0)
    const spanishOpener = page.getByRole('button', { name: 'Abrir el tutorial de HocusPocus' })
    await expect(spanishOpener).toBeFocused()

    await page.keyboard.press('Enter')
    await expect(spanishDialog).toBeVisible()
    await spanishDialog.getByRole('button', { name: 'Cerrar ayuda' }).click()
    await expect(spanishDialog).toHaveCount(0)
    await expect(spanishOpener).toBeFocused()
    await closeApp(page, session)
  })
}
