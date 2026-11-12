import assert from 'node:assert/strict'
import test from 'node:test'
import { setUiLanguage } from '../src/i18n/index.ts'
import { templateDisplay } from '../src/features/sceneTemplates/templateDisplay.ts'

const establishing = {
  id: 'cinema-establishing',
  title: 'Plano de establecimiento',
  description: 'Figura pequeña en su entorno; la cámara se abre y se desliza con polvo en el aire. Con mood lonely la cámara mira desde arriba, sube y llueve.',
}

test('scene template card titles follow the active language', { concurrency: false }, async () => {
  try {
    await setUiLanguage('en')
    const english = templateDisplay(establishing)
    assert.equal(english.title, 'Establishing shot')
    assert.notEqual(english.title, 'Plano de establecimiento')
    assert.notEqual(english.description, establishing.description)
    await setUiLanguage('es')
    const spanish = templateDisplay(establishing)
    assert.equal(spanish.title, 'Plano de establecimiento')
    assert.equal(spanish.description, establishing.description)
  } finally {
    await setUiLanguage('en')
  }
})
