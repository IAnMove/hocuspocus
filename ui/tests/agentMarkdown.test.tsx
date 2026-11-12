// The Wizard bubble renders a small Markdown subset. `_` emphasis used to match inside identifiers, so
// every reply that names a snake_case id outside backticks (models, params, files) came out as
// `qwen<em>image</em>21`; and a long unbroken token pushed the bubble wider than the panel.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, React })
const { AgentMarkdown } = await import('../src/features/agent/AgentMarkdown')

const html = (text: string) => renderToStaticMarkup(<AgentMarkdown text={text} />)
const plain = (text: string) => html(text).replace(/<[^>]+>/g, '')

test('provider error JSON keeps authorized_error / http_code', () => {
  const text = 'OpenAI-compatible request failed: {"type":"authorized_error","message":"x","http_code":"401"}'
  assert.ok(plain(text).includes('authorized_error') && plain(text).includes('http_code'), html(text))
  assert.doesNotMatch(html(text), /<em>|<strong>/)
})

test('snake_case ids outside backticks are left alone', () => {
  const text = 'Use qwen_image_21 with MMAudio_prompt and my_var_name_2, not flux2_klein_9b or snake_case_.'
  assert.equal(plain(text), text)
  assert.doesNotMatch(html(text), /<em>|<strong>/)
})

test('underscore emphasis still works at word boundaries', () => {
  assert.match(html('This is _italic_ text'), /<em>italic<\/em>/)
  assert.match(html('This is __bold__ text'), /<strong>bold<\/strong>/)
  assert.match(html('(_italic_) and "__bold__"'), /<em>italic<\/em>.*<strong>bold<\/strong>/)
  assert.match(html('_italic_ at the start, and at the end _too_'), /<em>italic<\/em>.*<em>too<\/em>/)
  assert.match(html('**bold** and *italic* and `code_with_underscores`'), /<strong>bold<\/strong> and <em>italic<\/em> and <code>code_with_underscores<\/code>/)
})

test('a long unbroken token may wrap inside the Wizard bubble', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')
  assert.match(css, /\.hp-agent-markdown\s*\{[^}]*overflow-wrap:\s*anywhere/)
})
