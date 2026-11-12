import { Component, useState, type ErrorInfo, type ReactNode } from 'react'
import { AlertTriangle, Copy, RefreshCw, RotateCcw } from 'lucide-react'
import { useUiTranslation } from '../i18n'
import { describeError, reportUiError } from '../lib/reportUiError'

type Props = {
  children: ReactNode
  /** Names the failing area in the log; also enables "Try again", which remounts it. */
  scope?: string
  /**
   * A new value clears a shown error (the user moved to another tab) without remounting healthy children:
   * a `key` would remount them, and a panel kept alive while it works (Lips Creator) would stop.
   */
  resetKey?: string
  className?: string
}

type State = { failed: boolean; error: unknown }

class Boundary extends Component<Props, State> {
  state: State = { failed: false, error: null }

  static getDerivedStateFromError(error: unknown): State {
    return { failed: true, error }
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    reportUiError(error, this.props.scope ? `boundary:${this.props.scope}` : 'boundary', info.componentStack)
  }

  componentDidUpdate(previous: Props): void {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false, error: null })
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return (
      <ErrorFallback
        error={this.state.error}
        className={this.props.className}
        onRetry={this.props.scope ? () => this.setState({ failed: false, error: null }) : undefined}
      />
    )
  }
}

export function AppErrorBoundary(props: Props) {
  return <Boundary {...props} />
}

function ErrorFallback({ error, className, onRetry }: {
  error: unknown
  className?: string
  onRetry?: () => void
}) {
  const { t } = useUiTranslation('common')
  const [copied, setCopied] = useState(false)
  const message = error instanceof Error ? error.message : String(error)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(describeError(error))
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  const button = 'inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover'
  return (
    <div role="alert" className={`flex items-center justify-center p-6 ${className ?? 'min-h-screen bg-bg-primary'}`}>
      <div className="w-full max-w-lg rounded-2xl border border-red-500/30 bg-bg-secondary p-5 text-text-primary">
        <div className="flex items-start gap-3">
          <AlertTriangle size={20} className="mt-0.5 shrink-0 text-red-400" />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">{t('errorBoundary.title')}</h2>
            <p className="mt-1 text-xs text-text-muted">{t('errorBoundary.body')}</p>
          </div>
        </div>
        <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-bg-tertiary p-3 font-mono text-[11px] text-red-300">{message}</pre>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={() => window.location.reload()} className={`${button} bg-accent-blue/10 text-accent-blue`}>
            <RefreshCw size={13} />{t('actions.reload')}
          </button>
          <button type="button" onClick={() => void copy()} className={button}>
            <Copy size={13} />{copied ? t('errorBoundary.copied') : t('errorBoundary.copyError')}
          </button>
          {onRetry && (
            <button type="button" onClick={onRetry} className={button}>
              <RotateCcw size={13} />{t('actions.retry')}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
