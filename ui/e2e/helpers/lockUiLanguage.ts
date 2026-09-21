import type { Page } from '@playwright/test'
import { LANGUAGE_STORAGE_KEY } from '../../src/i18n/storageKey'
import { latestWhatsNewPr, WELCOME_SEEN_KEY } from '../../src/whatsNew'

/** Pin the real UI language key. `i18nextLng` is ignored by detectUiLanguage. */
export async function lockUiLanguage(page: Page, language: 'en' | 'es' = 'en'): Promise<void> {
  await page.addInitScript(({ key, language: value, welcomeKey, welcomePr }) => {
    window.localStorage.setItem(key, value)
    window.localStorage.setItem('hocuspocus_welcome_seen_v1', '1')
    window.localStorage.setItem(welcomeKey, welcomePr)
  }, { key: LANGUAGE_STORAGE_KEY, language, welcomeKey: WELCOME_SEEN_KEY, welcomePr: String(latestWhatsNewPr()) })
}
