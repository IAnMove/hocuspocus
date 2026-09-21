# Studio speech commands

The shared command boundary for Studio speech is `version=2`,
`operation=generation.speech`:

```json
{
  "version": 2,
  "operation": "generation.speech",
  "intent_id": "stable-client-intention",
  "input": {
    "workspace": "output-workspace",
    "params": {
      "prompt": "literal speech text",
      "model_type": "kugelaudio_0_open",
      "resolution": "1280x720",
      "num_inference_steps": 0,
      "guidance_scale": 3,
      "seed": -1,
      "generation_mode": "audio",
      "image_mode": 0,
      "video_length": 0,
      "_audio_sub_mode": "speech",
      "duration_seconds": 20
    }
  }
}
```

`freeze_studio_speech_spec` validates and deep-copies the complete native
parameter map. The `original` snapshot keeps submitted spelling, omissions,
Unicode and multiline prompt text. The `effective` snapshot adds only the
speech selectors and other deterministic inactive/default values owned by the
adapter. It does not guess a model mode, duration, provider setting or voice
reference. The fingerprint is SHA-256 over version, operation, workspace and
effective parameters; `intent_id` and caller metadata are excluded so a retry
with another transport identity can be compared by content.

The accepted speech model registration is deliberately explicit:

`auk`, `auk_flash`, `kugelaudio_0_open`, `qwen3_tts_customvoice`,
`qwen3_tts_voicedesign`, `qwen3_tts_base`, `chatterbox`, `index_tts2`,
`scenema_audio`, and `dramabox_audio`. The allowlist is
`SPEECH_MODEL_TYPES` in `app/services/studio_speech_spec.py`. The preflight
requires the selected definition to declare `audio_only=true`, no image
output, and locally downloaded model files. Music and SFX handlers also
advertise audio-only and share the `tts` family, so their metadata is not
sufficient to enter this operation.

AuK / AuK Flash keep the instruction verbatim (no `Speaker N:` rewrite) and
reject non-zero guidance. Receta and GPU notes:
[WANGP_1300_AUDIO](WANGP_1300_AUDIO.md). `qwen3_tts_customvoice` is a named
preset; `qwen3_tts_base` is a recorded/imported reference (3–30 s, ≤20 MB)
stored on the character — [Character Kits](../character-kits/HOWUSEIT.md).

Speech references use exact asset IDs or canonical local API URLs. The
resource adapter checks source-workspace containment, file identity and
positive audio format/duration metadata with `ffprobe` through the existing
`StudioSpeechResources` implementation; this preparation step does not claim
full audio decoding or copy the source. Host paths, traversal, remote URLs and
source-workspace overrides are rejected.

The private `_tts_*` fields are typed aliases in the JSON contract. Speaker
names remain strings (or an inactive null), `_tts_voice_count` is an integer
from 0 through 6, and `_tts_original_prompt` remains separate from any
native speaker-tag rewrite. `audio_prompt_type` is checked against the
selected handler's declared choices; voice-count-driven handlers must match
their declared count mapping. `duration_seconds=0` is retained when the
selected model declares it as an auto-duration sentinel.

`custom_settings` is a closed map of the currently registered speech setting
IDs (`auto_split_every_s`, `exaggeration`, `pace`, `vc_steps`, `vc_cfg_rate`,
and `duration_multiplier`). The selected model's own `custom_settings`
metadata supplies the allowed subset and numeric ranges. Native handler
validation remains the final authority for provider-specific prompt syntax,
speaker tags and generative settings.

This slice intentionally does not announce music, SFX, video, avatar, 3D,
remote providers, arbitrary JSON options or a second scheduler. LoRA use is
accepted only when a speech definition explicitly declares
`enabled_audio_lora`; otherwise selected LoRAs fail before resource lookup.
