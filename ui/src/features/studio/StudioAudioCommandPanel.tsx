import { controlLabel } from '../../i18n/controlLabel'
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { GenerationReceiptLike } from '../../api/generationCommandClient'
import i18n, { useUiTranslation } from '../../i18n'

export interface AudioCommand {
  intent_id: string
  input: { workspace: string; params: Record<string, unknown> }
}

export interface AudioPresentation<C> {
  command: C
  active: boolean
  respond: (error?: string) => void
}

export interface AudioPanelProps<R> {
  workspace: string
  model: string
  visible: boolean
  onRecovered: (receipt: R) => Promise<void>
}

export interface AudioPanelConfiguration<C, R> {
  subMode: 'speech' | 'music' | 'sfx'
  pendingCommands: (workspace: string) => C[]
  subscribeCommands: (callback: () => void) => () => void
  submitCommand: (command: C) => Promise<R>
}

/** Shared visible ACK and exact-command recovery for native audio operations. */
export function StudioAudioCommandPanel<C extends AudioCommand, R extends GenerationReceiptLike>({
  workspace, model, visible, onRecovered, configuration, renderSummary,
}: AudioPanelProps<R> & { configuration: AudioPanelConfiguration<C, R>; renderSummary: (command: C) => ReactNode }) {
  const { t } = useUiTranslation('studio')
  const { subMode, pendingCommands, subscribeCommands, submitCommand } = configuration
  const presentationEvent = `hocuspocus:studio-${subMode}-presentation`
  const resultEvent = `hocuspocus:studio-${subMode}-result`
  const readyAttribute = `data-studio-${subMode}-ready`
  const listeningAttribute = `data-studio-${subMode}-listening`
  const commandAttribute = `data-studio-${subMode}-command`
  const messagePrefix = `${subMode}Commands` as const
  const [shown, setShown] = useState<C | null>(null)
  const [pending, setPending] = useState<C[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [receipt, setReceipt] = useState<R | null>(null)
  const current = useRef({ workspace, model, visible })
  const root = useRef<HTMLDivElement>(null)
  const waiting = useRef<AudioPresentation<C> | null>(null)
  useLayoutEffect(() => { current.current = { workspace, model, visible } }, [workspace, model, visible])

  useEffect(() => {
    const refresh = () => {
      try { setPending(pendingCommands(workspace)) }
      catch { setError(i18n.t(`studio:${messagePrefix}.pendingInvalid`)) }
    }
    refresh()
    return subscribeCommands(refresh)
  }, [workspace, pendingCommands, subscribeCommands, messagePrefix])

  useLayoutEffect(() => {
    const elementAtSetup = root.current
    const receive = (event: Event) => {
      const request = (event as CustomEvent<AudioPresentation<C>>).detail
      const view = current.current
      if (!view.visible || request.command.input.workspace !== view.workspace
          || String(request.command.input.params.model_type) !== view.model || waiting.current?.active) {
        request.respond(i18n.t(`studio:${messagePrefix}.contextChanged`))
        return
      }
      waiting.current = request
      setShown(request.command)
      setBusy(true)
      setReceipt(null)
      setError('')
    }
    window.addEventListener(presentationEvent, receive)
    if (elementAtSetup) elementAtSetup.setAttribute(listeningAttribute, 'true')
    // React StrictMode can simulate an effect cleanup while retaining the DOM
    // node. Defer rejection until after that probe; real navigation removes
    // the node and still receives a deterministic pre-POST failure.
    return () => {
      if (elementAtSetup) elementAtSetup.setAttribute(listeningAttribute, 'false')
      const request = waiting.current
      queueMicrotask(() => {
        if (request?.active && (!elementAtSetup || !elementAtSetup.isConnected)) {
          request.respond(i18n.t(`studio:${messagePrefix}.panelUnavailable`))
        }
      })
      window.removeEventListener(presentationEvent, receive)
    }
  }, [presentationEvent, listeningAttribute, messagePrefix])

  useEffect(() => {
    const complete = (event: Event) => {
      const result = (event as CustomEvent<{ intentId: string; receipt?: R; error?: string }>).detail
      if (result.intentId !== shown?.intent_id) return
      setBusy(false)
      setReceipt(result.receipt || null)
      setError(result.error || '')
    }
    window.addEventListener(resultEvent, complete)
    return () => window.removeEventListener(resultEvent, complete)
  }, [shown, resultEvent])

  useLayoutEffect(() => {
    const request = waiting.current
    if (!request?.active || request.command !== shown || !root.current) return
    root.current.setAttribute(commandAttribute, request.command.intent_id)
    root.current.scrollIntoView?.({ block: 'nearest' })
    let second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        const view = current.current
        const valid = root.current?.isConnected && view.visible
          && view.workspace === request.command.input.workspace
          && view.model === String(request.command.input.params.model_type)
        request.respond(valid ? undefined : i18n.t(`studio:${messagePrefix}.contextChanged`))
        waiting.current = null
      })
    })
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second) }
  }, [shown, commandAttribute, messagePrefix])

  const recover = async (command: C) => {
    setBusy(true)
    setError('')
    setShown(command)
    try {
      const admitted = await submitCommand(command)
      setReceipt(admitted)
      await onRecovered(admitted)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally { setBusy(false) }
  }

  return <div ref={root} {...{ [readyAttribute]: visible ? 'true' : 'false' }} className="px-3 space-y-2">
    {shown && <section role="status" className="border border-border rounded-lg p-2 space-y-1 bg-bg-tertiary">
      <strong className="text-xs">{receipt ? t(`${messagePrefix}.admitted`, { id: receipt.result.job_id }) : t(`${messagePrefix}.prepared`)}</strong>
      {renderSummary(shown)}
    </section>}
    {pending.filter(command => !busy || command.intent_id !== shown?.intent_id).map(command => <section key={command.intent_id} className="border border-border rounded-lg p-2 space-y-2">
      <strong className="text-xs">{t(`${messagePrefix}.pending`)}</strong>
      {renderSummary(command)}
      <button type="button" disabled={busy} title={busy ? controlLabel('disabled.actionInProgress') : undefined} onClick={() => void recover(command)}
        className="text-xs border border-border rounded px-2 py-1 disabled:opacity-50">{t(`${messagePrefix}.recover`)}</button>
    </section>)}
    {error && <p role="alert" className="text-xs text-indicator-error break-words">{error}</p>}
  </div>
}
