import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import { characterVoiceFor, parseCharacterVoicesByLanguage, type CharacterVoice, type CharacterVoicesByLanguage, type CustomCharacterVoice } from '../src/lib/characterVoice'
import { createCharacterKit, resolvedCharacterTts } from '../src/lib/characterKit'
import { speechAnalysisLanguage, spokenLanguage } from '../src/lib/speechLanguage'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const preset: CharacterVoice = { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'ryan' }
const spanish: CustomCharacterVoice = { provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference', name: 'Kevin ES',
  referenceAudio: '/api/v1/file/kevin-es.wav?workspace=series', transcript: 'Vale, vale, vale.', language: 'spanish' }

test('series labels, locales and codes resolve to one spoken language and one analysis code', () => {
  for (const label of ['Español', 'Español de España', 'es-ES', 'castellano', 'spanish', 'es']) assert.equal(spokenLanguage(label), 'spanish', label)
  for (const label of ['English', 'English (US)', 'en_US', 'inglés']) assert.equal(spokenLanguage(label), 'english', label)
  assert.equal(spokenLanguage('Klingon'), undefined)
  assert.equal(speechAnalysisLanguage('Español de España'), 'es')
  assert.equal(speechAnalysisLanguage('English'), 'en')
  assert.equal(speechAnalysisLanguage('en_GB'), 'en-gb')
  assert.equal(speechAnalysisLanguage('Klingon'), '', 'an unknown label falls back to automatic, never to an invalid code')
})

test('a character speaks each language with its own voice and every other language with its default voice', () => {
  const kit = { ...createCharacterKit('Kevin'), voice: preset, voicesByLanguage: { spanish } }
  assert.deepEqual(characterVoiceFor(kit, 'Español de España'), spanish)
  assert.deepEqual(characterVoiceFor(kit, 'es'), spanish)
  assert.deepEqual(characterVoiceFor(kit, 'English'), preset)
  assert.deepEqual(characterVoiceFor(kit, undefined), preset)
  assert.equal(resolvedCharacterTts(kit, undefined, 'Español').voiceName, 'Kevin ES')
  assert.equal(resolvedCharacterTts(kit).voiceId, 'ryan')
})

test('language voices reject unknown languages and recordings in another language', () => {
  assert.deepEqual(parseCharacterVoicesByLanguage({ spanish, english: preset }), { spanish, english: preset })
  assert.equal(parseCharacterVoicesByLanguage({}), undefined)
  assert.throws(() => parseCharacterVoicesByLanguage({ klingon: preset }))
  assert.throws(() => parseCharacterVoicesByLanguage({ english: spanish }))
  assert.deepEqual(parseCharacterVoicesByLanguage({ english: { ...spanish, language: 'auto' } })?.english, { ...spanish, language: 'auto' })
})

test('adding a language starts a recording in that language; removing it returns to the default voice', async t => {
  const { render, fireEvent, cleanup, within } = await import('@testing-library/react')
  const { CharacterLanguageVoices } = await import('../src/features/characters/CharacterLanguageVoices')
  t.after(cleanup)
  let current: CharacterVoicesByLanguage | undefined
  function Editor() {
    const [value, setValue] = useState<CharacterVoicesByLanguage>()
    return <CharacterLanguageVoices workspace="series" value={value} onChange={next => { current = next; setValue(next) }}
      savedKits={[{ ...createCharacterKit('Other'), id: 'other', voicesByLanguage: { spanish } }]} />
  }
  const view = render(<Editor />)
  fireEvent.change(view.getByTestId('add-language-voice'), { target: { value: 'spanish' } })
  fireEvent.click(view.getByTestId('add-language-voice-confirm'))
  assert.equal(current?.spanish?.model, 'qwen3_tts_base')
  assert.equal((current?.spanish as CustomCharacterVoice).language, 'spanish')
  const block = within(view.getByTestId('language-voice-spanish'))
  fireEvent.change(block.getByTestId('character-voice'), { target: { value: 'saved:other:spanish' } })
  assert.deepEqual(current?.spanish, spanish, 'a language voice saved on another character can be reused')
  fireEvent.change(block.getByTestId('character-voice'), { target: { value: 'ryan' } })
  assert.equal(current?.spanish?.voiceId, 'ryan')
  fireEvent.click(block.getByRole('button', { name: 'Remove' }))
  assert.equal(current, undefined)
  assert.equal(view.queryByTestId('language-voice-spanish'), null)
})
