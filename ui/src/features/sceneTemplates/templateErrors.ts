/** A template compile error with the stable code the MCP bridge and the Python compile share. */
export class TemplateError extends Error {
  readonly code: string
  readonly details: Readonly<Record<string, unknown>>

  constructor(code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'TemplateError'
    this.code = code
    this.details = details
  }
}
