import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ImageGenerationCommand, ImageGenerationReceipt } from '../../api/imageGenerationCommands'
import {
  pendingImageGenerationCommands, submitImageGenerationCommand, subscribeImageGenerationCommands,
} from '../../api/imageGenerationCommands'
import i18n, { useUiTranslation } from '../../i18n'

import { IMAGE_PRESENTATION_EVENT, IMAGE_RESULT_EVENT, type ImagePresentation } from './imageCommandPresentation'

function parameters(command: ImageGenerationCommand): Record<string, unknown> {
  return command.version === 2 ? command.input.params : { ...command.input }
}

function RequestSummary({ command }: { command: ImageGenerationCommand }) {
  const { t } = useUiTranslation('studio')
  const params = parameters(command)
  return <div className="space-y-1 min-w-0">
    <div className="text-xs break-words">{String(params.model_type)} · {String(params.resolution)} · {command.input.workspace}</div>
    <p className="text-xs whitespace-pre-wrap break-words max-h-24 overflow-auto">{String(params.prompt)}</p>
    <div className="text-xs text-text-muted">{t('commands.resources', {
      references: Array.isArray(params.image_refs) ? params.image_refs.length : 0,
      loras: Array.isArray(params.activated_loras) ? params.activated_loras.length : 0,
    })}</div>
  </div>
}

interface Props {
  workspace: string
  model: string
  visible: boolean
  onRecovered: (receipt: ImageGenerationReceipt) => Promise<void>
}

export function StudioImageCommandPanel({ workspace, model, visible, onRecovered }: Props) {
  const { t } = useUiTranslation('studio')
  const [shown, setShown] = useState<ImageGenerationCommand | null>(null)
  const [pending, setPending] = useState<ImageGenerationCommand[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [receipt, setReceipt] = useState<ImageGenerationReceipt | null>(null)
  const current = useRef({ workspace, model, visible })
  const root = useRef<HTMLDivElement>(null)
  const waiting = useRef<ImagePresentation | null>(null)
  useLayoutEffect(() => { current.current = { workspace, model, visible } }, [workspace, model, visible])

  useEffect(() => {
    const refresh = () => {
      try { setPending(pendingImageGenerationCommands(workspace)) }
      catch { setError(i18n.t('studio:commands.pendingInvalid')) }
    }
    refresh()
    return subscribeImageGenerationCommands(refresh)
  }, [workspace])

  useLayoutEffect(() => {
    const element = root.current
    const receive = (event: Event) => {
      const request = (event as CustomEvent<ImagePresentation>).detail
      if (request.target && request.target !== root.current) return
      const view = current.current
      if (!view.visible || request.command.input.workspace !== view.workspace
          || waiting.current?.active) {
        request.respond(i18n.t('studio:commands.contextChanged'))
        return
      }
      waiting.current = request
      setShown(request.command)
      setBusy(true)
      setReceipt(null)
      setError('')
    }
    window.addEventListener(IMAGE_PRESENTATION_EVENT, receive)
    if (element) element.dataset.studioImageListening = 'true'
    return () => {
      window.removeEventListener(IMAGE_PRESENTATION_EVENT, receive)
      if (element) element.dataset.studioImageListening = 'false'
      const request = waiting.current
      // Suspense temporarily disconnects layout effects while retaining the
      // DOM. Keep the same request until reveal reconnects its ACK effect.
      // An actual navigation/unmount removes the element and cancels it.
      queueMicrotask(() => {
        if (!element?.isConnected) request?.respond(i18n.t('studio:commands.panelUnavailable'))
      })
    }
  }, [])

  useEffect(() => {
    const complete = (event: Event) => {
      const result = (event as CustomEvent<{ intentId: string; receipt?: ImageGenerationReceipt; error?: string }>).detail
      if (result.intentId !== shown?.intent_id) return
      setBusy(false)
      setReceipt(result.receipt || null)
      setError(result.error || '')
    }
    window.addEventListener(IMAGE_RESULT_EVENT, complete)
    return () => window.removeEventListener(IMAGE_RESULT_EVENT, complete)
  }, [shown])

  useLayoutEffect(() => {
    const request = waiting.current
    if (!request?.active || request.command !== shown || !root.current) return
    root.current.dataset.studioImageCommand = request.command.intent_id
    root.current.scrollIntoView?.({ block: 'nearest' })
    // Let the rendered values reach the screen before admitting compute.
    let second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        const view = current.current
        const valid = root.current?.isConnected && view.visible && view.workspace === request.command.input.workspace

        request.respond(valid ? undefined : i18n.t('studio:commands.contextChanged'))
        waiting.current = null
      })
    })
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second) }
  }, [shown])

  const recover = async (command: ImageGenerationCommand) => {
    setBusy(true)
    setError('')
    setShown(command)
    try {
      // Retrying the saved intention can safely complete an admitted dispatch.
      // It never builds a new request from the currently edited form.
      const admitted = await submitImageGenerationCommand(command)
      setReceipt(admitted)
      await onRecovered(admitted)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally { setBusy(false) }
  }

  return <div ref={root} data-studio-image-ready={visible ? 'true' : 'false'} className="px-3 space-y-2">
    {shown && <section role="status" className="border border-border rounded-lg p-2 space-y-1 bg-bg-tertiary">
      <strong className="text-xs">{receipt ? t('commands.admitted', { id: receipt.result.job_id }) : t('commands.prepared')}</strong>
      <RequestSummary command={shown} />
    </section>}
    {pending.filter(command => !busy || command.intent_id !== shown?.intent_id).map(command => <section key={command.intent_id} className="border border-border rounded-lg p-2 space-y-2">
      <strong className="text-xs">{t('commands.pending')}</strong>
      <RequestSummary command={command} />
      <button type="button" disabled={busy} onClick={() => void recover(command)}
        className="text-xs border border-border rounded px-2 py-1 disabled:opacity-50">{t('commands.recover')}</button>
    </section>)}
    {error && <p role="alert" className="text-xs text-indicator-error break-words">{error}</p>}
  </div>
}
