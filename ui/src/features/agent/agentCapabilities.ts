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
    type: 'prepare_image',
    title: 'Prepare Studio image',
    purpose: 'Open Studio → Image and fill a validated text-to-image form.',
    useWhen: 'The user asks to prepare, configure, show or generate an image, photo or portrait.',
    risk: 'edit',
    parameters: ['prompt', 'model_type', 'resolution', 'aspect_ratio', 'seed', 'output_count'],
  },
  {
    type: 'prepare_audio',
    title: 'Prepare Studio audio',
    purpose: 'Open Studio → Audio and fill Speech, Music or SFX. The Audios gallery only displays finished files.',
    useWhen: 'The user asks to prepare or generate speech, music or a sound effect.',
    risk: 'edit',
    parameters: ['audio_sub_mode', 'prompt', 'duration_seconds', 'model_type', 'negative_prompt'],
  },
  {
    type: 'queue_sfx_pack',
    title: 'Queue a Studio SFX pack',
    purpose: 'Open Studio → Audio → SFX and submit several MMAudio one-shots to the canonical queue.',
    useWhen: 'The user explicitly asks to create or generate a pack of game sound effects.',
    risk: 'compute',
    parameters: ['sfx_clips', 'confirm', 'model_type', 'negative_prompt'],
  },
  {
    type: 'prepare_3d',
    title: 'Prepare Studio 3D',
    purpose: 'Open Studio → 3D (Hunyuan3D) and fill a text-to-mesh form. The 3D gallery only displays finished models.',
    useWhen: 'The user asks to prepare or generate a 3D object, mesh or Hunyuan3D asset.',
    risk: 'edit',
    parameters: ['prompt', 'model_type', 'preset', 'seed'],
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
    title: 'Queue the prepared Studio job',
    purpose: 'Submit the Studio video, image, music/speech or 3D form prepared in the same turn.',
    useWhen: 'The final user message explicitly asks to generate, launch, start, queue that media, or asked for a filled example of that section.',
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
  {
    type: 'create_comic',
    title: 'Create a filled Comics draft',
    purpose: 'Open Comics and fill characters, panels and lettering. Do not draw panel art unless asked.',
    useWhen: 'The user asks for a comic, tebeo, strip or a comic example.',
    risk: 'edit',
    parameters: ['title', 'synopsis', 'visual_style', 'language', 'characters', 'comic_panels'],
  },
  {
    type: 'generate_comic',
    title: 'Generate comic panel artwork',
    purpose: 'Queue local/MiniMax images for every unfinished panel of the open Comics Director plan. Panels run one after another on the shared GPU. There is no Render page button.',
    useWhen: 'The user explicitly asks to launch, draw, generate or render the open comic panels.',
    risk: 'compute',
    parameters: ['confirm'],
  },
  {
    type: 'generate_comic_panel',
    title: 'Regenerate one comic panel',
    purpose: 'Generate only one addressed page/panel of the open comic and replace its current artwork without touching the rest.',
    useWhen: 'The user explicitly asks to generate or regenerate a numbered panel or viñeta.',
    risk: 'compute',
    parameters: ['page_number', 'panel_number', 'confirm'],
  },
  {
    type: 'attach_studio_references',
    title: 'Attach existing image outputs to Studio',
    purpose: 'Resolve real image output names from the active workspace and attach them as a video start frame or subject/style references.',
    useWhen: 'The user asks to use one or more existing generated images as conditioning for Studio Image or Video.',
    risk: 'edit',
    parameters: ['reference_output_names', 'reference_role', 'replace_existing', 'remove_background'],
  },
  {
    type: 'configure_studio_loras',
    title: 'Configure compatible Studio LoRAs',
    purpose: 'Resolve LoRA filenames against the active model, activate them with bounded weights, and optionally replace the current set.',
    useWhen: 'The user asks to use, change or clear LoRAs in Studio Image or Video.',
    risk: 'edit',
    parameters: ['loras', 'replace_existing'],
  },
  {
    type: 'inspect_queue',
    title: 'Inspect the canonical queue',
    purpose: 'Refresh the real task list and open Activity so the user sees current jobs.',
    useWhen: 'The user asks what is in the queue, why the GPU is waiting, or the status of a job.',
    risk: 'read',
    parameters: ['queue_scope'],
  },
  {
    type: 'cancel_task',
    title: 'Cancel a canonical task',
    purpose: 'Cancel one identified active task through the canonical API after an explicit user request.',
    useWhen: 'The user clearly asks to cancel the active job or a specific task id.',
    risk: 'edit',
    parameters: ['task_id', 'confirm'],
  },
  {
    type: 'resume_task',
    title: 'Resume a canonical task',
    purpose: 'Resume one identified resumable task through the canonical API after an explicit user request.',
    useWhen: 'The user clearly asks to resume a specific interrupted or failed resumable task.',
    risk: 'edit',
    parameters: ['task_id', 'confirm'],
  },
  {
    type: 'retry_task',
    title: 'Retry a canonical task',
    purpose: 'Retry a persisted failed, cancelled or interrupted task through the canonical retry endpoint and show Activity.',
    useWhen: 'The user explicitly asks to retry a specific task or the latest failure.',
    risk: 'compute',
    parameters: ['task_id', 'confirm'],
  },
  {
    type: 'select_workspace',
    title: 'Select a workspace',
    purpose: 'Resolve an existing workspace by exact name, switch the canonical backend/store context, and keep the Wizard turn visible.',
    useWhen: 'The user asks to work in an existing named workspace.',
    risk: 'edit',
    parameters: ['workspace_name'],
  },
  {
    type: 'create_workspace',
    title: 'Create and select a workspace',
    purpose: 'Create a new isolated workspace through the canonical API, select it, and continue the Wizard conversation there.',
    useWhen: 'The user explicitly asks to create a new named workspace.',
    risk: 'edit',
    parameters: ['workspace_name'],
  },
]

export function buildAgentCapabilityGuide(): string {
  return AGENT_CAPABILITIES.map(capability => (
    `- ${capability.type} [${capability.risk}]: ${capability.purpose} `
    + `Use when: ${capability.useWhen} Parameters: ${capability.parameters.join(', ') || 'none'}.`
  )).join('\n')
}
