import assert from 'node:assert/strict'
import test from 'node:test'
import { defaultProjectLanguages, detectUiLanguage } from '../src/i18n/language'
import { createStoryProject } from '../src/features/stories/model'

test('new stories start in the UI language, not a hard-coded Spanish default', () => {
  const expected = detectUiLanguage() === 'es'
    ? { content: 'Español', spoken: 'Español de España' }
    : { content: 'English', spoken: 'English' }
  assert.deepEqual(defaultProjectLanguages(), expected)
  const story = createStoryProject()
  assert.equal(story.language, expected.content)
  assert.equal(story.spokenLanguage, expected.spoken)
})
