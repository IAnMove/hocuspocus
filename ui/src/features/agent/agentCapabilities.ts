import type { AgentAction } from './agentActions'
import { getCapability } from './capabilityRegistry'
import { AGENT_ACTION_TYPES } from './agentActionTypes'

export type AgentCapabilityRisk = 'read' | 'edit' | 'compute'

export interface AgentCapabilityDescriptor {
  type: AgentAction['type']
  title: string
  purpose: string
  useWhen: string
  risk: AgentCapabilityRisk
  parameters: string[]
}

/**
 * Canonical knowledge catalog for the embedded Wizard.
 *
 * The prompt guide is deliberately projected from the same registry that owns
 * parsing, validation and execution. Adding a capability anywhere else cannot
 * silently teach the LLM an action that the application does not implement.
 */
export const AGENT_CAPABILITIES: AgentCapabilityDescriptor[] = AGENT_ACTION_TYPES.map(type => {
  const capability = getCapability(type)
  if (!capability) throw new Error(`Agent action ${type} has no registered capability`)
  return {
    type: capability.name,
    title: capability.title,
    purpose: capability.description,
    useWhen: capability.useWhen,
    risk: capability.risk === 'external_cost' ? 'compute' : capability.risk,
    parameters: capability.parameters,
  }
})

export function buildAgentCapabilityGuide(): string {
  return AGENT_CAPABILITIES.map(capability => (
    `- ${capability.type} [${capability.risk}]: ${capability.purpose} `
    + `Use when: ${capability.useWhen} Parameters: ${capability.parameters.join(', ') || 'none'}.`
  )).join('\n')
}
