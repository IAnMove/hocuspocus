import type { CHARACTER_VOICES } from './characterVoice'

// Qwen's original speaker profiles, not measured accents in translated speech.
// https://github.com/QwenLM/Qwen3-TTS#custom-voice-generate
export const CHARACTER_VOICE_PROFILES = {
  vivian: { name: 'Vivian', origin: 'chinese' },
  serena: { name: 'Serena', origin: 'chinese' },
  uncle_fu: { name: 'Uncle Fu', origin: 'chinese' },
  dylan: { name: 'Dylan', origin: 'beijing' },
  eric: { name: 'Eric', origin: 'sichuan' },
  ryan: { name: 'Ryan', origin: 'english' },
  aiden: { name: 'Aiden', origin: 'americanEnglish' },
  ono_anna: { name: 'Ono Anna', origin: 'japanese' },
  sohee: { name: 'Sohee', origin: 'korean' },
} as const satisfies Record<typeof CHARACTER_VOICES[number], { name: string; origin: string }>
