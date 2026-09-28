// Video 3D glue for the server template library.
import type { TemplateSummary } from '../../api/templates'
import type { Scene3DDocument } from './types.ts'
import { WORLD3D_TEMPLATE_KIND, type World3DUserTemplate } from './userTemplates.ts'

const titles = new Map<string, string>()

/** A library template, already applied into the workspace, as the editor's mountable pack. */
export function packFromApplied(summary: TemplateSummary, document: Scene3DDocument): World3DUserTemplate {
  titles.set(summary.id, summary.title)
  return {
    kind: WORLD3D_TEMPLATE_KIND, version: 1, id: summary.id, title: summary.title, description: summary.description,
    includeAssets: summary.media > 0, createdAt: summary.createdAt, document,
  }
}

export function userTemplateTitle(id: string | undefined): string | undefined {
  return id ? titles.get(id) : undefined
}
