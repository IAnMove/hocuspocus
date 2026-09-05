import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { JSDOM } from 'jsdom'

function dom() {
  const value = new JSDOM(`<!doctype html><body>
    <div data-wizard-anchor="prompt"><textarea></textarea></div>
    <div data-wizard-anchor="model"><button>Model</button></div>
    <button data-wizard-anchor="generate">Generate</button>
  </body>`, { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: value.window,
    document: value.window.document,
    HTMLElement: value.window.HTMLElement,
    HTMLInputElement: value.window.HTMLInputElement,
    HTMLTextAreaElement: value.window.HTMLTextAreaElement,
    HTMLSelectElement: value.window.HTMLSelectElement,
    HTMLButtonElement: value.window.HTMLButtonElement,
  })
  value.window.HTMLElement.prototype.scrollIntoView = () => undefined
  value.window.matchMedia = () => ({ matches: false })
  return value
}

const plan = {
  anchors: ['prompt', 'model', 'generate'],
  speed: 'normal',
  replay: 'atomic',
}

test('visible replay follows semantic anchors after the value is committed', { concurrency: false }, async () => {
  dom()
  const { replayWizardPresentation } = await import('../src/features/agent/wizardPresentation.ts')
  const prompt = document.querySelector('textarea')
  prompt.value = 'valor ya comprometido en el store'
  const observed = []
  const status = await replayWizardPresentation(plan, {
    wait: async milliseconds => {
      observed.push({
        milliseconds,
        anchor: document.querySelector('[data-wizard-magic]')?.getAttribute('data-wizard-anchor'),
        replay: document.querySelector('[data-wizard-magic]')?.getAttribute('data-wizard-replay'),
      })
    },
  })
  assert.equal(status, 'replayed')
  assert.deepEqual(observed.map(item => item.anchor).filter((item, index) => index % 2 === 0), ['prompt', 'model', 'generate'])
  assert.equal(observed[0].replay, 'fill')
  assert.equal(prompt.value, 'valor ya comprometido en el store')
  assert.equal(document.activeElement?.tagName, 'TEXTAREA')
  assert.equal(document.querySelector('[data-wizard-magic]'), null)
})

test('visible replay yields immediately when the user is editing or starts interacting', { concurrency: false }, async () => {
  dom()
  const { replayWizardPresentation } = await import('../src/features/agent/wizardPresentation.ts')
  document.querySelector('textarea').focus()
  assert.equal(await replayWizardPresentation(plan), 'yielded')

  document.activeElement.blur()
  let waits = 0
  const status = await replayWizardPresentation(plan, {
    wait: async () => {
      waits += 1
      window.dispatchEvent(new window.Event('input', { bubbles: true }))
    },
  })
  assert.equal(status, 'yielded')
  assert.equal(waits, 1)
  assert.equal(document.querySelector('[data-wizard-magic]'), null)
})

test('missing anchors and reduced motion never invalidate the committed command', { concurrency: false }, async () => {
  dom()
  const { replayWizardPresentation } = await import('../src/features/agent/wizardPresentation.ts')
  assert.equal(await replayWizardPresentation({ ...plan, anchors: ['not-mounted'] }), 'skipped')
  let waited = false
  assert.equal(await replayWizardPresentation(plan, {
    reducedMotion: true,
    wait: async () => { waited = true },
  }), 'replayed')
  assert.equal(waited, false)
})

test('Studio video prototype exposes stable anchors and an accessible motion escape hatch', async () => {
  const [prompt, model, mode, generate, css] = await Promise.all([
    readFile(new URL('../src/components/Sidebar/PromptInput.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/Sidebar/ModelSelector.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/Sidebar/GenerationModeSelector.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/Sidebar/GenerateButton.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/index.css', import.meta.url), 'utf8'),
  ])
  assert.match(prompt, /data-wizard-anchor="prompt"/)
  assert.match(prompt, /data-wizard-commit="atomic"/)
  assert.match(model, /data-wizard-anchor="model"/)
  assert.match(mode, /data-wizard-anchor="mode"/)
  assert.equal((generate.match(/data-wizard-anchor="generate"/g) || []).length, 2)
  assert.match(css, /@keyframes hp-wizard-field-fill/)
  assert.match(css, /prefers-reduced-motion:[ ]*reduce[\s\S]*data-wizard-anchor/)
  assert.match(css, /hp-navigation-primary\[data-navigation-expanded='true'\][\s\S]*translateY\(1px\)/)
  assert.match(css, /hp-navigation-children::before[\s\S]*--hp-navigation-notch-left/)
})
