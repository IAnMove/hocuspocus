import { controlReason } from '../../i18n/controlLabel'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type {
  ToolsUpscaleGenerationCommand,
  ToolsUpscaleGenerationReceipt,
} from '../../api/toolsGenerationCommands'
import {
  pendingToolsUpscaleGenerationCommands,
  submitToolsUpscaleGenerationCommand,
  subscribeToolsUpscaleGenerationCommands,
} from '../../api/toolsGenerationCommands'
import i18n, { useUiTranslation } from '../../i18n'
import {
  TOOLS_PRESENTATION_EVENT,
  TOOLS_RESULT_EVENT,
  type ToolsPresentation,
} from './toolsCommandPresentation'

function parameters(command: ToolsUpscaleGenerationCommand): Record<string, unknown> {
  return command.input.params as Record<string, unknown>
}

function commandSourceWorkspace(parameters: Record<string, unknown>): string | null {
  return typeof parameters.source_workspace === 'string' ? parameters.source_workspace : null
}

function RequestSummary({ command }: { command: ToolsUpscaleGenerationCommand }) {
  const { t } = useUiTranslation('studio')
  const params = parameters(command)
  return <div className="space-y-1 min-w-0">
    <div className="text-xs break-words">
      {String(params.source_kind)} · {String(params.method)} · {command.input.workspace}
    </div>
    {commandSourceWorkspace(params) && <div className="text-xs text-text-muted break-words">
      {t('toolsCommands.sourceWorkspace', { workspace: commandSourceWorkspace(params) })}
    </div>}
    <p className="text-xs break-all max-h-16 overflow-auto" title={String(params.source)}>
      {String(params.source)}
    </p>
    <div className="text-xs text-text-muted">
      {t('toolsCommands.destination', { workspace: command.input.workspace })}
    </div>
  </div>
}

interface Props {
  workspace: string
  source: string
  sourceWorkspace: string | null
  sourceKind: 'image' | 'video' | null
  method: string
  visible: boolean
  onRecovered: (receipt: ToolsUpscaleGenerationReceipt) => Promise<void>
}

/** Durable presentation and recovery surface for the Tools upscale command. */
export function ToolsCommandPanel({ workspace, source, sourceWorkspace, sourceKind, method, visible, onRecovered }: Props) {
  const { t } = useUiTranslation('studio')
  const [shown, setShown] = useState<ToolsUpscaleGenerationCommand | null>(null)
  const [pending, setPending] = useState<ToolsUpscaleGenerationCommand[]>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [receipt, setReceipt] = useState<ToolsUpscaleGenerationReceipt | null>(null)
  const current = useRef({ workspace, source, sourceWorkspace, sourceKind, method, visible })
  const root = useRef<HTMLDivElement>(null)
  const waiting = useRef<ToolsPresentation | null>(null)
  useLayoutEffect(() => {
    current.current = { workspace, source, sourceWorkspace, sourceKind, method, visible }
  }, [workspace, source, sourceWorkspace, sourceKind, method, visible])

  useEffect(() => {
    const refresh = () => {
      try { setPending(pendingToolsUpscaleGenerationCommands(workspace)) }
      catch { setError(i18n.t('studio:toolsCommands.pendingInvalid')) }
    }
    refresh()
    return subscribeToolsUpscaleGenerationCommands(refresh)
  }, [workspace])

  useLayoutEffect(() => {
    const elementAtSetup = root.current
    const receive = (event: Event) => {
      const request = (event as CustomEvent<ToolsPresentation>).detail
      const view = current.current
      const params = parameters(request.command)
      if (!view.visible || request.command.input.workspace !== view.workspace
          || params.source !== view.source || commandSourceWorkspace(params) !== view.sourceWorkspace
          || params.source_kind !== view.sourceKind
          || params.method !== view.method || waiting.current?.active) {
        request.respond(i18n.t('studio:toolsCommands.contextChanged'))
        return
      }
      waiting.current = request
      setShown(request.command)
      setBusy(true)
      setReceipt(null)
      setError('')
    }
    window.addEventListener(TOOLS_PRESENTATION_EVENT, receive)
    if (elementAtSetup) elementAtSetup.dataset.studioToolsListening = 'true'
    return () => {
      if (elementAtSetup) elementAtSetup.dataset.studioToolsListening = 'false'
      const request = waiting.current
      queueMicrotask(() => {
        if (request?.active && (!elementAtSetup || !elementAtSetup.isConnected)) {
          request.respond(i18n.t('studio:toolsCommands.panelUnavailable'))
        }
      })
      window.removeEventListener(TOOLS_PRESENTATION_EVENT, receive)
    }
  }, [])

  useEffect(() => {
    const complete = (event: Event) => {
      const result = (event as CustomEvent<{
        intentId: string
        receipt?: ToolsUpscaleGenerationReceipt
        error?: string
      }>).detail
      if (result.intentId !== shown?.intent_id) return
      setBusy(false)
      setReceipt(result.receipt || null)
      setError(result.error || '')
    }
    window.addEventListener(TOOLS_RESULT_EVENT, complete)
    return () => window.removeEventListener(TOOLS_RESULT_EVENT, complete)
  }, [shown])

  useLayoutEffect(() => {
    const request = waiting.current
    if (!request?.active || request.command !== shown || !root.current) return
    root.current.dataset.studioToolsCommand = request.command.intent_id
    root.current.scrollIntoView?.({ block: 'nearest' })
    let second = 0
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        const view = current.current
        const params = parameters(request.command)
        const valid = root.current?.isConnected && view.visible
          && view.workspace === request.command.input.workspace
          && view.source === params.source
          && commandSourceWorkspace(params) === view.sourceWorkspace
          && view.sourceKind === params.source_kind
          && view.method === params.method
        request.respond(valid ? undefined : i18n.t('studio:toolsCommands.contextChanged'))
        waiting.current = null
      })
    })
    return () => { cancelAnimationFrame(first); cancelAnimationFrame(second) }
  }, [shown])

  const recover = async (command: ToolsUpscaleGenerationCommand) => {
    setBusy(true)
    setError('')
    setShown(command)
    try {
      // Recovery submits the persisted command unchanged. It never rebuilds
      // from currently edited Tools controls or creates a fresh intent ID.
      const admitted = await submitToolsUpscaleGenerationCommand(command)
      setReceipt(admitted)
      await onRecovered(admitted)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally { setBusy(false) }
  }

  return <div
    ref={root}
    data-studio-tools-ready={visible ? 'true' : 'false'}
    className="px-3 space-y-2"
  >
    {shown && <section role="status" className="border border-border rounded-lg p-2 space-y-1 bg-bg-tertiary">
      <strong className="text-xs">
        {receipt ? t('toolsCommands.admitted', { id: receipt.result.job_id }) : t('toolsCommands.prepared')}
      </strong>
      <RequestSummary command={shown} />
      {receipt && <span className="text-[10px] text-text-muted">{t('toolsCommands.queued')}</span>}
    </section>}
    {pending.filter(command => !busy || command.intent_id !== shown?.intent_id).map(command => <section
      key={command.intent_id}
      className="border border-border rounded-lg p-2 space-y-2"
    >
      <strong className="text-xs">{t('toolsCommands.pending')}</strong>
      <RequestSummary command={command} />
      <button
        type="button"
        disabled={busy} title={controlReason(busy, 'disabled.actionInProgress')}
        onClick={() => void recover(command)}
        className="text-xs border border-border rounded px-2 py-1 disabled:opacity-50"
      >{t('toolsCommands.recover')}</button>
    </section>)}
    {error && <p role="alert" className="text-xs text-indicator-error break-words">{error}</p>}
  </div>
}
