# VoxCPM2 speech

VoxCPM2 (OpenBMB, 2B parameters, Apache-2.0) is a local speech engine next to
Qwen3 TTS. It speaks 30 languages, including Spanish, and outputs 48 kHz audio.
One checkpoint serves two model types that follow the Qwen3 conventions:

| Model type | Like | Voice from | `alt_prompt` |
| --- | --- | --- | --- |
| `voxcpm2_voicedesign` | `qwen3_tts_voicedesign` | a written description | the voice description |
| `voxcpm2_base` | `qwen3_tts_base` | a reference recording (`audio_guide`, `audio_guide2`) | the reference transcript(s), one line per speaker |

Neither type has a `model_mode`: VoxCPM2 reads the language from the text. The
clone type also takes `custom_settings.style` (speaking style, up to 300
characters) and `custom_settings.auto_split_every_s`. `Speaker 1:` /
`Speaker 2:` lines with two references make a dialogue. Steps (default 10,
4–30) and guidance (default 2, 1–5) are the regular Studio controls.

## Code

- `app/models/TTS/voxcpm2_handler.py`: WanGP family handler, registered in
  `family_handlers` in `app/wgp.py`.
- `app/models/TTS/voxcpm2/pipeline.py`: generation. It splits the text into
  segments (empty lines, `Speaker N:` lines, optional auto split), builds the
  voice once per speaker and joins the segments with `pause_seconds`.
- `app/models/TTS/voxcpm2/model`, `modules`: the inference code of the
  `voxcpm` package 2.0.3, vendored without its web UI, training, denoiser and
  text normaliser, so it needs no new dependency. Changes are listed in
  `NOTICE.md` next to the code.
- Weights: `openbmb/VoxCPM2` at revision
  `32279effe8c19989596f05d353d1447f51d9e915`, downloaded on first use into the
  `voxcpm2` checkpoint folder (about 5 GB). The repository's tokenizer Python
  file is not downloaded; the model loads its tokenizer as
  `LlamaTokenizerFast`, as upstream does.

## Particularities

- **A parenthesised lead is voice direction.** `(young woman, warm voice)Hola`
  speaks "Hola" in that voice. The pipeline writes the description (design) or
  the style (clone) as that lead, and merges it with a line's own lead, so
  `(whispering) Come here.` is whispered rather than read aloud.
- **A transcript and a style exclude each other.** With a transcript VoxCPM2
  continues the reference recording: the lead would follow the transcript and
  be read aloud. A style direction therefore switches the clone to the
  reference alone, and so does a line that starts with its own direction. The
  measured case: with the transcript, `(susurrando, en secreto)` was spoken
  (word error rate 0.25); reference-only, the line was whispered with word error
  rate 0.
- **Static KV cache.** The model allocates its attention caches on a device
  when it is built, outside the registered buffers. The weights are built on
  the CPU and handed to WanGP's memory manager as `transformer`; the caches are
  allocated again on the execution device before the first generation.
- **CPU as torch's default device.** WanGP makes the GPU the default device;
  VoxCPM2 builds some tensors without a device and moves them itself, so the
  pipeline generates inside `torch.device("cpu")`, the condition the upstream
  code assumes. Weights and caches still run on the GPU.
- **Audio VAE in float32.** The VAE stays float32 and outside the managed
  modules, as upstream decodes it.
- **No `torch.compile`.** Upstream compiles with CUDA graphs, which would keep
  stale weight addresses when WanGP moves weights. Without it an RTX 4090
  still speaks faster than real time.
- **Duration.** One model step makes 0.16 s of audio (6.25 steps per second).
  `duration_seconds` caps the steps; VoxCPM2 also stops itself, and retries a
  take that runs past six times the text length.

## Measurements

RTX 4090, bfloat16, 10 steps, guidance 2, pipeline called directly:

| Case | Audio | Wall time |
| --- | ---: | ---: |
| Design, Spanish sentence | 6.4 s | 3.1 s |
| Clone from reference only | 5.4 s | 2.5 s |
| Clone with transcript | 5.8 s | 2.1 s |
| Two-voice dialogue, four lines | 10.5 s | 3.0 s |

Peak VRAM was 5.6 GB. The app's `qa.speech` measured word error rates from 0
to 0.125 on the Spanish and English takes; the misses were invented names
(Zilia, Gorko) and one dropped word.
