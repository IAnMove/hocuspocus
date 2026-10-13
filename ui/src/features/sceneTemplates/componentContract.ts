import i18n from '../../i18n'
import {
  getCandidateSceneTemplate,
  templateCatalogVersion,
  type ReviewStatus,
  type TemplateAssetKind,
  type TemplateSlotName,
} from './catalog'

/**
 * Stable labels shared by the template picker and the Wizard prompt: one slot
 * vocabulary for every card. They describe roles only; they do not bind an
 * asset or authorize a generation request. Read at call time so the UI language
 * is current.
 */
export function templateSlotLabels(): Record<TemplateSlotName, string> {
  return {
    subject_1: i18n.t('scene3d:slotLabels.subject_1'),
    subject_2: i18n.t('scene3d:slotLabels.subject_2'),
    background: i18n.t('scene3d:slotLabels.background'),
    prop_1: i18n.t('scene3d:slotLabels.prop_1'),
    prop_2: i18n.t('scene3d:slotLabels.prop_2'),
    foreground: i18n.t('scene3d:slotLabels.foreground'),
  }
}

export type TemplateComponent = {
  readonly key: TemplateSlotName
  readonly label: string
  readonly description: string
  readonly required: boolean
  readonly kinds: readonly TemplateAssetKind[]
}

export type TemplateComponentContract = {
  readonly schema: 'hocuspocus.template-components'
  readonly version: 1
  readonly templateId: string
  readonly templateVersion: 1
  readonly catalogVersion: string
  readonly status: ReviewStatus
  readonly generationPolicy: 'provided_only'
  readonly description: string
  readonly components: readonly TemplateComponent[]
  readonly limits: readonly string[]
}

export function describeTemplateComponents(id: string): TemplateComponentContract {
  const template = getCandidateSceneTemplate(id)
  const labels = templateSlotLabels()

  return {
    schema: 'hocuspocus.template-components',
    version: 1,
    templateId: template.id,
    templateVersion: template.version,
    catalogVersion: templateCatalogVersion(template),
    status: template.status,
    generationPolicy: 'provided_only',
    description: template.description,
    components: template.slots.map(slot => ({
      key: slot.id,
      label: labels[slot.id],
      description: slot.description,
      required: slot.required,
      // Copy this array so a consumer cannot mutate catalog state through a
      // serialized contract object.
      kinds: [...slot.kinds],
    })),
    limits: [...template.limits],
  }
}

const TEMPLATE_COMPONENT_PROMPT_INSTRUCTION = [
  'Asigna cada componente únicamente mediante un asset canónico conocido por su assetId y workspace.',
  'Este contrato es descriptivo: no autoriza llamadas a APIs, colas, generación ni creación de archivos.',
  'No inventes archivos, rutas, nombres ni IDs; si falta un asset canónico, informa del faltante.',
  'Mantén separados el cuerpo o identidad y la pose: no sustituyas un cuerpo por una pose ni una pose por un cuerpo.',
].join(' ')

/**
 * Return a readable, valid JSON prompt that can be pasted into the Wizard.
 * The instruction is deliberately advisory: the contract cannot grant a
 * provider or a generator permission that the caller did not already have.
 */
export function templateComponentPrompt(id: string): string {
  return JSON.stringify({
    ...describeTemplateComponents(id),
    instruction: TEMPLATE_COMPONENT_PROMPT_INSTRUCTION,
  }, null, 2)
}
