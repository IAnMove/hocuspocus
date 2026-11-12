// Video 3D glue for the server template library.
import type { TemplateSummary } from '../../api/templates'
import type { World3DLibraryCard, World3DWorkspaceTemplate } from '../../api/world3dWorkspace'
import { stageLine, stageTitle } from './stageShelf'
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

/** A personal template stored in the workspace (an agent's world3d.templates.user.put) as a mountable pack. */
export function packFromWorkspace(summary: World3DWorkspaceTemplate, document: Scene3DDocument): World3DUserTemplate {
  titles.set(summary.id, summary.title)
  return {
    kind: WORLD3D_TEMPLATE_KIND, version: 1, id: summary.id, title: summary.title, description: summary.description,
    includeAssets: true, createdAt: summary.createdAt || summary.updatedAt || new Date().toISOString(), document,
  }
}

/** A stage card (``stage-<mold>``) with the document ``world3d.templates.get`` built for it, as a mountable pack. */
export function packFromStage(card: World3DLibraryCard, document: Scene3DDocument, locale: 'en' | 'es'): World3DUserTemplate {
  const title = stageTitle(card, locale)
  titles.set(card.id, title)
  return {
    kind: WORLD3D_TEMPLATE_KIND, version: 1, id: card.id, title, description: stageLine(card, locale),
    includeAssets: false, createdAt: new Date().toISOString(), document,
  }
}

export function userTemplateTitle(id: string | undefined): string | undefined {
  return id ? titles.get(id) : undefined
}
