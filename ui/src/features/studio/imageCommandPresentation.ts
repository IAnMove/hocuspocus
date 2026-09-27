import type { ImageGenerationCommand, ImageGenerationReceipt } from '../../api/imageGenerationCommands'
import i18n from '../../i18n'

export const IMAGE_PRESENTATION_EVENT = 'hocuspocus:studio-image-presentation'
export const IMAGE_RESULT_EVENT = 'hocuspocus:studio-image-result'
export interface ImagePresentation {
  command: ImageGenerationCommand
  target?: HTMLElement
  active: boolean
  respond: (error?: string) => void
}

export function finishStudioImageCommand(intentId: string, receipt?: ImageGenerationReceipt, error?: string): void {
  window.dispatchEvent(new CustomEvent(IMAGE_RESULT_EVENT, { detail: { intentId, receipt, error } }))
}

async function mountedPanel(): Promise<HTMLElement> {
  window.dispatchEvent(new Event('hocuspocus:studio-image-open'))
  const find = () => document.querySelector<HTMLElement>('[data-studio-image-ready="true"][data-studio-image-listening="true"]')
  const current = find()
  if (current) return current
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => { observer.disconnect(); reject(new Error(i18n.t('studio:commands.panelUnavailable'))) }, 8000)
    const observer = new MutationObserver(() => {
      const panel = find()
      if (panel) { observer.disconnect(); clearTimeout(timer); resolve(panel) }
    })
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-studio-image-ready', 'data-studio-image-listening'] })
  })
}

/** Wait for a visible React commit of this exact request, before any POST. */
export async function presentStudioImageCommand(command: ImageGenerationCommand): Promise<void> {
  const root = await mountedPanel()
  await new Promise<void>((resolve, reject) => {
    const request: ImagePresentation = {
      command: structuredClone(command), target: root, active: true,
      respond: error => {
        if (!request.active) return
        request.active = false
        clearTimeout(timer)
        observer.disconnect()
        if (error) reject(new Error(error))
        else resolve()
      },
    }
    const timer = window.setTimeout(() => request.respond(i18n.t('studio:commands.panelUnavailable')), 8000)
    const observer = new MutationObserver(() => {
      if (!root.isConnected) request.respond(i18n.t('studio:commands.panelUnavailable'))
    })
    observer.observe(document.body, { childList: true, subtree: true })
    window.dispatchEvent(new CustomEvent<ImagePresentation>(IMAGE_PRESENTATION_EVENT, { detail: request }))
  })
  if (!root.isConnected || root.dataset.studioImageCommand !== command.intent_id) {
    throw new Error(i18n.t('studio:commands.contextChanged'))
  }
}
