import type { AgentAction } from './agentActions'

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
 * Canonical knowledge catalog for the embedded Wizard. Add a capability here
 * when its parser and executor become available. The system prompt and the
 * handoff documentation can then describe the same contract without teaching
 * the model a second, contradictory version of it.
 */
export const AGENT_CAPABILITIES: AgentCapabilityDescriptor[] = [
  {
    type: 'open_tab',
    title: 'Open an application section',
    purpose: 'Navigate to a real HocusPocus section through its store state.',
    useWhen: 'The user asks to go somewhere or opening a section materially helps the answer.',
    risk: 'read',
    parameters: ['tab'],
  },
  {
    type: 'prepare_video',
    title: 'Prepare Studio video',
    purpose: 'Open Studio → Video and fill a validated text-to-video form.',
    useWhen: 'The user asks to prepare, configure, show or generate a video.',
    risk: 'edit',
    parameters: ['prompt', 'model_type', 'duration_seconds', 'resolution', 'aspect_ratio', 'seed', 'output_count'],
  },
  {
    type: 'open_story_section',
    title: 'Open a Story Lab section',
    purpose: 'Open Story Lab and select Overview, World, Characters, Relationships, Structure or Productions.',
    useWhen: 'The user asks for a specific part of Story Lab or that section helps explain the next step.',
    risk: 'read',
    parameters: ['story_section'],
  },
  {
    type: 'open_series_section',
    title: 'Open a Series Lab section',
    purpose: 'Open Series Lab and select Setup, Canon, Episode room, Shots or Review.',
    useWhen: 'The user asks for a specific part of Series Lab or that section helps explain the next step.',
    risk: 'read',
    parameters: ['series_section'],
  },
  {
    type: 'start_generation',
    title: 'Queue the prepared video',
    purpose: 'Submit the video prepared in the same turn to the canonical task queue.',
    useWhen: 'The final user message explicitly asks to generate, launch, start or queue the video.',
    risk: 'compute',
    parameters: [],
  },
  {
    type: 'create_story',
    title: 'Create a filled Story Lab draft',
    purpose: 'Create and persist a new story with overview, world, cast, locations and story beats, then show it in Story Lab.',
    useWhen: 'The user directly asks for a new story, plot or filled Story Lab example.',
    risk: 'edit',
    parameters: ['title', 'project_type', 'creative_brief', 'premise', 'logline', 'synopsis', 'theme', 'ending', 'characters', 'locations', 'outline_beats'],
  },
  {
    type: 'create_series_episode',
    title: 'Create a filled Series Lab episode',
    purpose: 'Find or create a series, prepare the minimum canon needed, create a filled episode outline and show Episode room.',
    useWhen: 'The user directly asks for a chapter or episode of a series. This belongs in Series Lab, not Story Lab.',
    risk: 'edit',
    parameters: ['series_title', 'series_premise', 'episode_title', 'episode_premise', 'episode_logline', 'characters', 'locations', 'outline_beats'],
  },
]

export function buildAgentCapabilityGuide(): string {
  return AGENT_CAPABILITIES.map(capability => (
    `- ${capability.type} [${capability.risk}]: ${capability.purpose} `
    + `Use when: ${capability.useWhen} Parameters: ${capability.parameters.join(', ') || 'none'}.`
  )).join('\n')
}
