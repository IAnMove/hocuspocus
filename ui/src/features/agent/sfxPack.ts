export interface AgentSfxClip {
  name: string
  prompt: string
  durationSeconds: number
}

const STYLE = 'Retro fantasy arcade game sound effect, slightly modern mix, not pure 8-bit chiptune, not cinematic orchestra, no speech, no singing.'

export const ARCADE_HORDE_SFX_PACK: AgentSfxClip[] = [
  {
    name: 'coin_pickup',
    prompt: `${STYLE} coin_pickup: very short bright metallic coin collect sparkle, 8-bit glint, one-shot, 0.5 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'xp_gem_collect',
    prompt: `${STYLE} xp_gem_collect: crystalline ascending chime, gem pickup, clean and tiny, 0.6 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'player_hit',
    prompt: `${STYLE} player_hit: heavy body impact thud, player damage, short tight reverb, 0.4 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'enemy_hit',
    prompt: `${STYLE} enemy_hit: wet flesh squish impact, monster hit, light gore, 0.3 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'sword_swipe',
    prompt: `${STYLE} sword_swipe: sharp blade whoosh with a slight metal ring, 0.5 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'magic_cast',
    prompt: `${STYLE} magic_cast: rising magical energy pulse whoosh, spell cast, 0.7 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'level_up',
    prompt: `${STYLE} level_up: short triumphant power-up jingle fanfare, arcade level up, 1.2 seconds.`,
    durationSeconds: 2,
  },
  {
    name: 'footstep_dirt',
    prompt: `${STYLE} footstep_dirt: single soft footstep on dry dirt and gravel, 0.4 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'door_creak_old',
    prompt: `${STYLE} door_creak_old: old wooden crypt door creak, rusty hinge, 1.0 seconds.`,
    durationSeconds: 1,
  },
  {
    name: 'horde_spawn_drone',
    prompt: `${STYLE} horde_spawn_drone: low tense dark drone, monster horde approaching, loop-friendly bed, 4 seconds, no melody.`,
    durationSeconds: 4,
  },
]
