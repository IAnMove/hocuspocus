# 2D speech quality and reusable mouths

Save the character in **Character Creator**, then return to **Series Lab → Shots → Regenerate all** (or **Regenerate this shot**). Regeneration creates new editable scenes and unapproved MP4 takes. Existing motion, recordings and approved takes are preserved.

## Resting face

The animation rig retains the wiped, mouthless base plus separate mouth layers. Saving also composes a reusable still from that base and the selected **closed** mouth, using its saved placement. Library thumbnails and still-reference consumers prefer this resting image. A changed base, closed drawing or placement invalidates the old composite; saving rebuilds it. No original image is overwritten and pending assets stay pending.

Series mounts saved mouths on configured visible characters, including listeners and characters in silent shots. An incomplete listener retains its original reference rather than appearing mouthless. Offscreen dialogue keeps its audio and never drives another actor's face. Existing scenes acquire the new appearance when regenerated; old approved takes remain unchanged.

## Timing and drawings

The previous Series planner distributed letters across the recorded phrase. The automatic 2D batch now analyzes each isolated voice recording through Rhubarb, retaining phonetic boundaries, actual pauses and consonant closures. English (`en`/`en-US`) uses PocketSphinx with the known script; other languages use Rhubarb's language-independent phonetic recognizer. Script, recognizer, audio bytes, fragment and executable identity participate in the existing bounded cache.

Rhubarb already inserts suitable intermediate mouth shapes. The editor stores those cues alongside their audio/text provenance and compiles ordinary editable opacity keyframes. Moving a complete line moves its relative cues; changing the text, track binding or duration invalidates the old analysis. No video-generation model runs. If the offline engine is unavailable, the batch reports an error instead of silently claiming phonetic quality from estimated letter timings.

Four legacy positions still work. Nine drawings retain more distinctions:

| Drawing | Rhubarb | Use |
| --- | --- | --- |
| closed | X | Relaxed silence/listening |
| pressed | A | M, B, P |
| small | B | Narrow consonants / EE |
| medium | C | EH and intermediate opening |
| wide | D | AH |
| round | E | O |
| pucker | F | OO/W |
| bite | G | F/V |
| tongue | H | L |

Audio amplitude helps locate activity and pauses; it does not identify vowels by itself. Rhubarb analyzes speech sounds, with a script-assisted recognizer for English. Recognition remains approximate, especially with noisy recordings, accents and very fast speech. The scene's cue track and layers remain editable. For mixed recordings, the existing speech-analysis endpoint can isolate vocals; generated Series voice lines are already isolated and do not need that extra operation.

## Twenty styles to share

Character Creator's mouth selector includes **20 new Studio styles**, each containing nine aligned 512px transparent PNGs. **Download this style** and **Download the 20 new styles** export ZIP files with images, a manifest, slot mapping and reuse instructions. Original generated artwork provenance is recorded in the manifest. All nine sprites share a frame and scale: keep their square canvases to avoid size/placement jumps. The six earlier four-state packs remain available.

The PNGs and manifest ship in both the UI and app preset directories. `scripts/prepare_mouth_presets.py` mechanically slices generated 3×3 atlases; it does not draw replacement artwork.

## Installation and API

Pinokio Install/Update invokes `speech_install.js`. **Advanced → Repair offline lip sync** runs just that step. It installs Rhubarb 1.14.0 in the app's `.runtime/speech` directory from a pinned official archive with a checked SHA-256; no elevated/global install or runtime model download is needed. Bundled releases support x86-64 Linux, Windows and macOS; other architectures can supply a compatible executable through `RHUBARB_EXECUTABLE`. The installer reuses a configured/PATH executable and does not block the rest of the app on unsupported architectures; automatic phonetic production reports unavailable until that engine is supplied.

`GET /api/v1/character-kits/speech/capabilities` reports availability. `POST /api/v1/character-kits/speech/analyze` still accepts raw `audio/wav` (mono, PCM16, 16 kHz, at most 90 seconds). It additionally accepts JSON `{wavBase64, dialogue, language}`; the script is bounded to 4,000 characters and stays out of request URLs. Add `?isolate_vocals=true` for an existing mixed recording when vocal isolation is installed.

```javascript
const wavBase64 = Buffer.from(wavBytes).toString('base64');
const response = await fetch(`${base}/api/v1/character-kits/speech/analyze`, {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({wavBase64, dialogue: 'Move now.', language: 'en'})
});
if (!response.ok) throw new Error(await response.text());
const {mouthCues, recognizer, duration} = await response.json();
```

```python
import base64, requests
with open('voice.wav', 'rb') as audio:
    payload = dict(wavBase64=base64.b64encode(audio.read()).decode(),
                   dialogue='Move now.', language='en')
response = requests.post(f'{base}/api/v1/character-kits/speech/analyze', json=payload)
response.raise_for_status()
cues = response.json()['mouthCues']
```

```sh
curl --fail-with-body "$BASE/api/v1/character-kits/speech/analyze" \
  -H 'Content-Type: application/json' --data-binary @voice-with-script.json
```

Reference: [Rhubarb mouth shapes, recognizers and script hints](https://github.com/DanielSWolf/rhubarb-lip-sync#mouth-shapes).
