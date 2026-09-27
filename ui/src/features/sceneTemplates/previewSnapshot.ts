import type { Scene } from '../../types'
import { parseSceneFile } from '../../lib/sceneFile'
import { templateCatalogVersion, type SceneTemplateDefinition } from './catalog'

type ReferenceIdentity = { id: string; version: number; catalogVersion: string; variant: 'coral' }
const record = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('The reference contains no valid metadata.')
  return value as Record<string, unknown>
}

/** The reviewed movie's saved scene is authoritative, not today's compiler. */
export function parseRenderedReferenceScene(payload: unknown, expected: ReferenceIdentity): Scene {
  const metadata = record(payload)
  if (metadata.templateId !== expected.id || metadata.templateVersion !== expected.version
    || metadata.catalogVersion !== expected.catalogVersion || metadata.variant !== expected.variant
    || metadata.status !== 'rendered-not-approved') throw new Error('The reference\'s identity or version does not match the template.')
  const scene = parseSceneFile(JSON.stringify(record(metadata.scene)))
  if (scene.generationPolicy !== 'provided_only' || scene.narrative?.templateId !== expected.id
    || scene.narrative.controls.catalogVersion !== expected.catalogVersion
    || scene.narrative.controls.templateVersion !== expected.version) throw new Error('The saved scene does not match the reference or its policy.')
  return scene
}

export async function loadRenderedReferenceScene(template: SceneTemplateDefinition, previewBaseUrl: string, signal?: AbortSignal): Promise<Scene> {
  const response = await fetch(`${previewBaseUrl.replace(/\/+$/, '')}/${template.id}.json`, { cache: 'no-store', signal })
  if (!response.ok) throw new Error('This video\'s snapshot is not available. No other scene was rebuilt or opened.')
  const text = await response.text()
  if (text.length > 4_000_000) throw new Error('The reference snapshot exceeds the 4 MB limit.')
  return parseRenderedReferenceScene(JSON.parse(text), { id: template.id, version: template.version, catalogVersion: templateCatalogVersion(template), variant: 'coral' })
}
