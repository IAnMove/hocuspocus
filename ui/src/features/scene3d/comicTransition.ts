/** Body of `scene3d.comic.transition`. The UI, the Wizard and MCP post this same operation. */
export function comicTransitionBody(input: {
  workspace: string
  format: 'landscape' | 'portrait'
  panels: Array<string | { image?: string; video?: string; at?: number; cutout?: string }>
  fromPanel: number
  toPanel: number
  exportClips?: boolean
  intentId?: string
}) {
  return {
    operation: 'scene3d.comic.transition',
    version: 1 as const,
    ...(input.intentId ? { intent_id: input.intentId } : {}),
    input: {
      workspace: input.workspace,
      format: input.format,
      panels: input.panels,
      from_panel: input.fromPanel,
      to_panel: input.toPanel,
      export: Boolean(input.exportClips),
    },
  }
}
