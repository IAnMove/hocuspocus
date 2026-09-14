# Wizard and MCP usage (corpus guide)

Status: H17 usage guide for published native commands. This is **not** whole-app
QA. Evidence states follow [AGENT_QA_POLICY](AGENT_QA_POLICY.md): a simulation
is not a real generation; a queued receipt is not a finished file.

Machine fixture: [`tests/fixtures/wizard_mcp_corpus.json`](../../tests/fixtures/wizard_mcp_corpus.json).
Expect **actions and receipts**, never the exact wording of the language model.

Related contracts: [SHARED_NATIVE_COMMANDS](SHARED_NATIVE_COMMANDS.md),
[IMAGE_COMMANDS](IMAGE_COMMANDS.md), [SPEECH_COMMANDS](SPEECH_COMMANDS.md),
[MUSIC_COMMANDS](MUSIC_COMMANDS.md), [SFX_COMMANDS](SFX_COMMANDS.md),
[TOOLS_COMMANDS](TOOLS_COMMANDS.md), [WORKSPACE_COMMANDS](WORKSPACE_COMMANDS.md).

---

## English

### What Wizard is, and what MCP is

- **Wizard** is the chat inside the web app. You speak; the app turns that into
  typed actions (`prepare_image`, `start_generation`, `retry_task`, …). The
  visible answer is built from execution receipts and rejection codes, not from
  “I created the file” model prose.
- **MCP** is an external client talking to `POST /api/v1/mcp` with a
  Bearer token. You call a **named tool**. The server does not ask Wizard’s LLM
  to interpret that call.

Both share the same published operations, the same `intent_id`, and the same
canonical task. Closing the browser does not cancel an already admitted job.

Wizard's model interprets the intended outcome using the conversation and current
project. Its structured `intent` distinguishes conversation, clarification and
action, with an execution scope of none, preparation or running work. The panel
validates that plan without reconstructing actions from keywords. Clarification
questions stay visible alongside navigation receipts. A series request without
creative direction can start with one question. Once the user supplies a subject,
setting, tone or references, Wizard develops a first episode draft, inventing
provisional missing titles and plot details. It does not require another explicit
creation command or a phrase delegating invention. Requests to discuss before
saving remain conversational. Opening Series Lab alone does not create an episode
or render a video. Creation receipts include the premises actually saved.

### Before you start

1. Choose the **output workspace**. Generations land there.
2. In **Settings**, enable only models that are already installed. This guide
   never downloads weights.
3. For MCP, enable it in Settings (or set `HOCUS_MCP_TOKEN` before start). The
   endpoint is `http://SERVER:PORT/api/v1/mcp`. Keep the token out of
   screenshots and reports. If no token is configured, MCP answers `503`.
4. Open **Ask to the Wizard** or connect your MCP client. Discovery is
   authoritative: `GET /api/v1/generation/commands` and MCP `tools/list`.

### Published operations (this tree)

| Operation | Who uses it | What success means |
| --- | --- | --- |
| `generation.image` | Studio Image, Wizard `prepare_image` + `start_generation`, MCP | Admission queued. Inspect the task. |
| `generation.speech` | Studio Audio → Speech, MCP | Same. Literal text is preserved. |
| `generation.music` | Studio Audio → Music, MCP | Lyrics and Music Caption stay distinct. |
| `generation.sfx` | Studio Audio → SFX, MCP | Text or a canonical video guide. |
| `tools.upscale` | Tools → Upscale, MCP | Exact source + method. |
| `generation.receipt` | HTTP GET or MCP | Recovers the same admission after a lost response. |

Collections (`collections.create` / `update` / `get` / `list` / `commands.receipt`)
are a separate catalog at `GET /api/v1/commands`.

**Not published here:** `generation.video`. Asking MCP for that tool must fail
without creating a task. Wizard can still fill Studio → Video through
`prepare_video` (a UI action, not this native command). Native video is a
different lane.

Legacy MCP names `generate` / `upscale` still exist. Do not mix their envelopes
with the typed operations above.

### Wizard tour (visible)

1. Open **Ask to the Wizard**.
2. **Refusal.** “Prepare a Flux image of a red boat, but do not generate it.”
   The form may fill. **No new Activity task.** The reply must not claim a file.
3. **How-to.** “How do I generate an image in Studio?” Navigation or
   explanation only. No `start_generation`.
4. **Ambiguous.** “Generate that again.” Without an exact target this cannot
   start. The Wizard should ask which item you mean. An inconsistent action
   proposal produces a local rejection, never an invented filename.
5. **Workspace change.** “Switch to workspace corpus-b, then prepare a lantern.
   Do not generate yet.” The destination must change **before** a later
   generate. Recover receipts in the **original** output workspace.
6. **Retry.** After a timeout, repeat the **same** intention. Do not invent a
   second job. In Wizard, `retry_task` with the exact task id retries that job.
7. **Compound.** Preparation must precede start. The model interprets requests
   to prepare and generate together, regardless of phrasing, and orders the
   actions. If its proposal puts start before preparation, validation rejects
   that start. A request to prepare for later must not launch work. Queued ≠
   completed.
8. **Unpublished.** If the model proposes `generation_video` or another unknown
   action, the panel lists **Actions not executed**. That is not success.

Spanish equivalents are in the fixture (`es-negation-no-generes`,
`es-how-to-image`, `es-workspace-change`, …).

### MCP client tour

1. `initialize` then `tools/list`. Confirm the published names. `generation.video`
   must be absent.
2. Call `generation.image` with `version`, `intent_id`, and `input` (no
   `operation` field; the tool name carries it).
3. Save `receipt.result.job_id` and `receipt.result.task_id`. Status is
   **queued**.
4. Repeat the **identical** call (lost HTTP response). `replayed: true` and the
   **same IDs**. Two clients must show that same id.
5. `generation.receipt` with the original workspace + `intent_id`.
6. Call `generation.video`. `isError: true`, **zero** tasks.
7. Wrong Bearer token → `401`. Disabled MCP → `503`.

Example image envelope (replace the model with an **installed** id):

```json
{
  "version": 1,
  "intent_id": "one-client-intention",
  "input": {
    "workspace": "my-outputs",
    "model_type": "flux2_klein_4b",
    "prompt": "A red boat on calm water",
    "resolution": "512x512",
    "num_inference_steps": 1,
    "seed": 42,
    "guidance_scale": 1.0
  }
}
```

A deliberate second generation needs a **new** `intent_id`, even if the prompt
is identical. Changing the prompt under the old id is a conflict (`409`), not a
retry.

### Errors and recovery

| Situation | What you should see | What not to do |
| --- | --- | --- |
| “Don’t generate” / “cómo genero” | No task | Do not treat model prose as a receipt |
| Extra/unknown fields | HTTP `422`, no admission | Do not reuse that payload |
| Unpublished tool | MCP `isError`, Wizard rejection | Do not promise an MP4 |
| Timeout after admit | Same job id on replay | Do not mint a new `intent_id` |
| Receipt in another workspace | `404` | The physical output folder is part of identity |
| Queued / running | Distinct labels | Do not say “finished” |

### Evidence matrix (this cut)

| Item | Designed | Implemented | Simulated | Real-executed | Pending |
| --- | --- | --- | --- | --- | --- |
| HTTP catalog | yes | yes | yes | read-only probe | not every model |
| MCP `tools/list` | yes | yes | yes | no (token not read from the shared runtime) | live list |
| image/speech/music/sfx/upscale admit+replay | yes | yes | yes | **no GPU job** | one small real generate |
| `generation.video` | yes | **no** (H01) | unpublished error | n/a | native video command |
| Wizard EN/ES corpus | yes | yes | parser + e2e harness | no live LLM | paid/live Wizard |

Local evidence (not in git): `outputs/wizard-mcp-corpus-20260911/`.

Conversation-only plans keep the model's explanation; it is not an execution
receipt. Plans with actions or validation rejections replace free-form claims
with actual receipts. Clarification plans display their dedicated question.

Follow-up verification (2026-09-13): four live MiniMax-M3 planning probes covered
a broad series ambition, an indirect episodic idea, creative delegation using
earlier context with video deferred, and an explanation-only request. All four
returned the expected intent and execution scope. Proposed actions were not
executed. Local evidence: `outputs/wizard-intent-20260913/live-plans.json`.

The creative-continuation regression can be checked against the configured LLM
from `ui/` with `HOCUSPOCUS_BASE_URL=http://127.0.0.1:PORT node_modules/.bin/tsx
--tsconfig tsconfig.app.json scripts/check-wizard-intent-live.ts` (use the actual
running port). It covers creative references, indirect follow-up without a title,
discussion before saving and an idea without a subject. It validates plans only
and does not execute actions. `seriesWizardDraft.test.ts` separately exercises
the Series adapter against simulated persistence, including the saved premises
in its receipt and excluding media generation.

---

## Español

### Qué es el Wizard y qué es MCP

- **Wizard** es el chat de la aplicación. Convierte tu frase en acciones
  tipadas. La respuesta visible sale de recibos y rechazos, no de un “ya está
  el archivo” inventado por el modelo.
- **MCP** es un cliente externo contra `POST /api/v1/mcp` con token
  Bearer. Llamas a una **herramienta con nombre**. El servidor no pasa esa
  llamada por el LLM del Wizard.

Comparten operaciones publicadas, `intent_id` y la tarea canónica. Cerrar el
navegador no cancela un trabajo ya admitido.

El modelo interpreta la intención usando la conversación y el proyecto actual.
Distingue entre conversar, pedir un dato necesario y actuar, y entre preparar
algo o ejecutarlo. La aplicación valida ese plan sin reconstruir acciones a
partir de palabras clave. Las preguntas se muestran incluso cuando también se
abre una sección. Si todavía no hay dirección creativa puede preguntar, pero al
recibir un tema, ambiente, tono o referencias desarrolla un primer borrador y
propone los títulos y detalles que falten. No necesita otra orden de creación
ni una frase que delegue la invención. Si pides conversar antes de guardar, se
mantiene en esa fase. El recibo muestra las premisas guardadas. Abrir Series Lab
por sí solo no crea el episodio ni genera vídeos.

### Antes de empezar

1. Elige la **carpeta de salida**.
2. En **Ajustes**, deja visibles solo modelos **ya instalados**. Esta guía no
   descarga pesos.
3. Para MCP, actívalo en Ajustes (o `HOCUS_MCP_TOKEN` al arrancar). El
   endpoint es `http://SERVIDOR:PUERTO/api/v1/mcp`. No guardes el token
   en capturas. Sin token, MCP responde `503`.
4. Abre **Ask to the Wizard** o conecta el cliente. La autoridad de
   descubrimiento es `GET /api/v1/generation/commands` y `tools/list`.

### Operaciones publicadas

Las mismas de la tabla inglesa. **No está publicado** `generation.video`: una
llamada MCP debe fallar sin crear tarea. El Wizard puede rellenar Studio →
Vídeo con `prepare_video` (acción de UI, no este comando nativo).

### Recorrido Wizard

1. Abre el asistente.
2. **Negación.** «Prepara una imagen de un barco rojo, no la generes.» Puede
   rellenar el formulario. **No hay tarea nueva.**
3. **Cómo.** «¿Cómo genero una imagen en Studio?» Sin `start_generation`.
4. **Ambiguo.** «Genera eso otra vez.» Sin destino exacto pregunta a qué recurso
   te refieres; no arranca una generación inventada.
5. **Cambio de workspace.** Cambia a `corpus-b` y prepara; no generes aún.
   Los recibos se recuperan en el workspace **original**.
6. **Reintento.** Tras un timeout, la **misma** intención. No un segundo
   trabajo. `retry_task` usa el id exacto.
7. **Compuesto.** Preparar y luego generar. En cola no es terminado.
8. **No publicado.** Si propone `generation_video`, verás **Acciones no
   ejecutadas**, no un MP4.

### Recorrido MCP

1. `tools/list` sin `generation.video`.
2. `generation.image` con `intent_id` estable.
3. Guarda `job_id` / `task_id`. Estado **en cola**.
4. Repite la llamada idéntica: mismos ids, `replayed: true`. Dos clientes
   muestran el mismo id.
5. `generation.receipt` en el workspace original.
6. `generation.video` → error, cero tareas.
7. Token incorrecto → `401`.

Una segunda generación deliberada lleva **otro** `intent_id`. Cambiar el
contenido con el mismo id es un conflicto `409`.

### Matriz y límites

La matriz está arriba. Este corte **no** declara QA de toda la aplicación ni
lanza inferencia en el runtime compartido aunque haya modelos instalados
(`flux2_klein_4b`, `kugelaudio_0_open`, ACE-Step). La generación real queda
**PENDING**. Fallos ajenos (vídeo nativo H01, frames del Video Editor H09) se
registran con reproducción; no se “arreglan” aquí.
