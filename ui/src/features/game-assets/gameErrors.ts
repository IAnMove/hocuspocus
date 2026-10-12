import { GameApiError } from '../../api/gameAssets'
import i18n from '../../i18n'
import type { GameProblem } from './types'

/** What the user was doing; ``actions.<name>`` is the fallback message. */
export type GameAction =
  | 'load' | 'open' | 'save' | 'preset' | 'create' | 'duplicate' | 'delete' | 'styleSheet' | 'approveStyle'
  | 'discard' | 'addCharacter' | 'linkKit' | 'openEditor' | 'saveAsset' | 'checkList' | 'commitList'
  | 'produce' | 'cancel' | 'resume' | 'poll' | 'approve' | 'reject' | 'lock' | 'approveClean' | 'export'

/** A local failure that carries a translatable ``errors.<code>``. */
export class GameCodeError extends Error {
  readonly code: string

  constructor(code: string) {
    super(code)
    this.name = 'GameCodeError'
    this.code = code
  }
}

type Translate = (key: string, options?: Record<string, unknown>) => string

function translate(key: string, options?: Record<string, unknown>): string {
  return (i18n.t as unknown as Translate)(key, options)
}

export function gameText(key: string, options?: Record<string, unknown>): string {
  return translate(`gameAssets:${key}`, options)
}

/** ``<group>.<code>`` in the gameAssets catalog, or ``fallback`` when there is no such key. */
export function codeLabel(group: string, code: string, fallback = code, options?: Record<string, unknown>): string {
  const key = `gameAssets:${group}.${code}`
  return code && i18n.exists(key) ? translate(key, options) : fallback
}

function codeOf(error: unknown): string {
  const code = error && typeof error === 'object' ? (error as { code?: unknown }).code : undefined
  return typeof code === 'string' ? code : ''
}

/** The translated ``errors.<code>``, else the server message, else the action fallback. */
export function errorText(error: unknown, action: GameAction): string {
  const code = codeOf(error)
  const known = codeLabel('errors', code, '')
  if (known) return known
  const server = error instanceof GameApiError ? error.serverMessage : ''
  if (server && server !== code) return server
  return gameText(`actions.${action}`)
}

export function problemsOf(error: unknown): GameProblem[] {
  return error instanceof GameApiError ? error.problems : []
}

/** ``Line N: message``; line 0 and a missing line mean the whole list and print no line. */
export function problemText(problem: GameProblem): string {
  const code = typeof problem.code === 'string' ? problem.code : ''
  const message = (typeof problem.message === 'string' && problem.message && problem.message !== code)
    ? problem.message
    : codeLabel('errors', code, code || gameText('actions.checkList'))
  const where = typeof problem.field === 'string' && problem.field ? `${problem.field}: ` : ''
  const line = typeof problem.line === 'number' && problem.line > 0 ? problem.line : 0
  return line ? gameText('problemLine', { line, message: `${where}${message}` }) : `${where}${message}`
}
