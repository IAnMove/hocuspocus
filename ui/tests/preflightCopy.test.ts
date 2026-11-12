import assert from 'node:assert/strict'
import test from 'node:test'
import { preflightText } from '../src/components/preflightCopy'
import { setUiLanguage } from '../src/i18n'

const cuda = {
  id: 'cuda',
  level: 'error' as const,
  message: "No CUDA GPU detected. HocusPocus Lab's generation pipeline requires an NVIDIA GPU; generation will not work on this machine.",
}

test('preflight banner keys the CUDA check in the UI language', async () => {
  await setUiLanguage('en')
  assert.equal(preflightText(cuda), cuda.message)
  await setUiLanguage('es')
  assert.match(preflightText(cuda), /No se detectó una GPU CUDA/)
  assert.equal(
    preflightText({ id: 'disk', level: 'warn', message: '12 GB free on the output drive. Model downloads and long runs can exhaust this — keep an eye on free space.' }),
    'Quedan 12 GB libres en el disco de salida. Las descargas de modelos y los trabajos largos pueden agotarlo: vigila el espacio libre.',
  )
  assert.equal(preflightText({ id: 'other', level: 'warn', message: 'Server said this.' }), 'Server said this.')
  await setUiLanguage('en')
})
