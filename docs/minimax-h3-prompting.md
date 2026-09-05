# MiniMax H3 prompting sources

Maestro treats MiniMax's official H3 prompt-writing guides as the canonical
source for H3 prompt structure. Local enhancer and Director guides may add
validation, exact-dialogue preservation, timing and UI-specific reference
mapping, but must not change the official field names or their order.

Canonical upstream sources:

- [Base / FL2VA prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md)
- [Ref2VA prompt guide](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md)
- [Official consolidated H3 prompt-writing skill](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md)

The contracts locked by regression tests are:

- Base / FL2VA: `integrated_multimodal_description`,
  `overall_soundscape`, `non_diegetic_music`.
- Ref2VA: `subject_definitions`, `summary`, `retention_analysis`,
  `detailed_description`, `overall_soundscape`, `non_diegetic_music`.
- Structural sections are written in English; literal dialogue, lyrics and
  visible requested text retain their intended language.
- Reference labels and retention vocabulary follow the official guide; the
  deterministic compiler binds them to the real per-shot media manifest.

When upstream changes, update the local files under
`app/services/llm_guides/{enhance,dialect}/` and their tests together. Do not
silently improvise another H3 dialect.
