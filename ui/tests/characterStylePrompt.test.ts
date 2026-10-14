import assert from 'node:assert/strict'
import test from 'node:test'
import { characterStylePrompt, characterStyles, screenFor, type CharacterStyleKind } from '../src/lib/characterStyles.ts'

const kinds: CharacterStyleKind[] = ['character', 'pose', 'prop']

test('no style leaves a placeholder in the prompt: the server skips a job whose prompt still has {screen}', () => {
  for (const style of characterStyles) for (const kind of kinds) {
    const { prompt } = characterStylePrompt(style, kind, 'Un conquistador español de 20 años.')
    assert.doesNotMatch(prompt, /[{}]/, `${style.id} / ${kind}: ${prompt}`)
  }
})

test('the screen colour is named everywhere the style asks for it, and a green subject gets a magenta screen', () => {
  const style = characterStyles.find(item => item.id === 'graphic-novel')!
  const green = characterStylePrompt(style, 'character', 'Un conquistador español de 20 años.')
  assert.equal(green.screen, 'green')
  assert.equal(green.prompt.match(/chroma-key green/g)?.length, 2, 'the background template names the screen twice')
  assert.equal(screenFor('a green dragon'), 'magenta')
  assert.equal(characterStylePrompt(style, 'character', 'a green dragon').screen, 'magenta')
})

test('a description with replacement patterns is kept as written', () => {
  const style = characterStyles[0]
  assert.match(characterStylePrompt(style, 'character', 'costs $& and $1').prompt, /costs \$& and \$1/)
})
