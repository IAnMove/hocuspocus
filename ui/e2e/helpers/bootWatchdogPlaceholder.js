// Playwright addInitScript({ path }) evaluates this as a classic script
// in the page. Keep it valid JS with no imports, exports, or TS syntax:
// addInitScript(function) is serialized via Function#toString, and the
// test runner's __name helper is not defined in the browser.
//
// This runs after the document is created but before the HTML is parsed,
// so `#root` and even `document.documentElement` can still be null.
(() => {
  const seed = () => {
    const root = document.getElementById('root')
    if (root && root.childElementCount === 0) {
      root.appendChild(document.createElement('span'))
    }
  }

  if (document.getElementById('root')) {
    seed()
    return
  }

  const observer = new MutationObserver(() => {
    if (!document.getElementById('root')) return
    observer.disconnect()
    seed()
  })
  document.addEventListener('DOMContentLoaded', () => {
    observer.disconnect()
    seed()
  }, { once: true })
  observer.observe(document, { childList: true, subtree: true })
})()
