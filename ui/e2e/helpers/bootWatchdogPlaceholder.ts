/**
 * Seed `#root` so the 10s watchdog in `index.html` stays inert while the
 * production bundle is still parsing. Playwright's `addInitScript` runs
 * after the document is created but before the body is parsed, so
 * `getElementById('root')` is null if we seed synchronously.
 *
 * The function body must stay valid JS: Playwright serializes it into
 * the page via `Function.prototype.toString()`.
 */
export function installBootWatchdogPlaceholder() {
  const seed = () => {
    const root = document.getElementById('root')
    if (root && root.childElementCount === 0) {
      root.appendChild(document.createElement('span'))
    }
  }

  if (document.getElementById('root') || document.readyState !== 'loading') {
    seed()
    return
  }

  const observer = new MutationObserver(() => {
    if (!document.getElementById('root')) return
    observer.disconnect()
    seed()
  })
  observer.observe(document.documentElement, { childList: true, subtree: true })
  document.addEventListener('DOMContentLoaded', () => {
    observer.disconnect()
    seed()
  }, { once: true })
}
