import assert from 'node:assert/strict'
import test from 'node:test'
import i18n, { resources } from '../src/i18n'
import { localizeWizardWelcome, wizardWelcomeText } from '../src/features/agent/wizardWelcome'
import { normalizeRemoteWizardMessages } from '../src/features/agent/wizardConversationSync'

test('wizard greetings follow UI language for new, restored and already visible chats', async () => {
  const previous = i18n.language
  const cards = [{ id: 'existing-job' }]
  const saved = { id: 'saved-welcome', role: 'assistant', text: resources.es.wizard.welcome, createdAt: 123, cards }
  try {
    await i18n.changeLanguage('en')
    assert.equal(wizardWelcomeText(), resources.en.wizard.welcome)
    const visible = localizeWizardWelcome(saved)
    assert.equal(visible.text, resources.en.wizard.welcome)
    assert.equal(visible.language, 'en')
    assert.equal(visible.id, saved.id)
    assert.equal(visible.createdAt, saved.createdAt)
    assert.equal(visible.cards, cards)
    assert.equal(saved.text, resources.es.wizard.welcome)
    assert.equal(normalizeRemoteWizardMessages([], cards)[0].text, resources.en.wizard.welcome)
    await i18n.changeLanguage('es')
    assert.equal(wizardWelcomeText(), resources.es.wizard.welcome)
    assert.equal(localizeWizardWelcome(visible).text, resources.es.wizard.welcome)
    assert.equal(normalizeRemoteWizardMessages([], cards)[0].text, resources.es.wizard.welcome)
  } finally {
    await i18n.changeLanguage(previous)
  }
})

test('changing the greeting preserves user messages and normal assistant replies', () => {
  const user = { role: 'user', text: resources.es.wizard.welcome, language: 'es' }
  const reply = { role: 'assistant', text: 'He preparado el vídeo que pediste.', language: 'es' }
  assert.equal(localizeWizardWelcome(user), user)
  assert.equal(localizeWizardWelcome(reply), reply)
})
