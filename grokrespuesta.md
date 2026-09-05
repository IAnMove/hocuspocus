# Limpieza Wan + TMPDIR junio + Lab vieja — HECHO (23 ago)

Disco: **80% → 63%**. Libres **364 G → 661 G**.

## Qué era “lab vieja”

Había **dos carpetas** de Loreframe en Pinokio:

| Carpeta | Qué era |
|---|---|
| `Maestro-next.git` | **Esta**, la que usas (puertos 42003/42004). Intacta. |
| `Maestro.git` | Copia **anterior** de la misma Lab. Ya le habíamos vaciado los ckpts. Quedaban venv, vendor H3, outputs viejos (~143 G). |

Como solo usas esta, **borré `Maestro.git`**. No es una papelera: no vuelve.

## Qué más borré

- **wan.git** entero (~152 G en `du`; parte era torch hardlinkeado con otras apps, por eso `df` no baja 152 G justos). No había proceso Wan; la Lab viva sigue arriba.
- **TMPDIR de junio** (`tmp88tr04al` + `tmphs_247l0`, 58 G): dump de pesos ACE-Step del 1 de junio, nadie lo tenía abierto. TMPDIR ahora ~480 M.

## Qué queda gordo (si quieres otra ronda)

- Hunyuan3d-2-lowvram.git **52 G** (app Hunyuan aparte; Lore ya tiene Hunyuan)
- Cosmos / Pixal3d / PID **~105 G** (mayo/junio)
- HunyuanDiT **dentro de next** 11 G (desactivado)
- `~/.cache/hy3dgen` 7 G

Loreframe actual **no se tocó**. Labs siguen en 42003 y 42004.

---

# Disco ahora — dónde sigue el peso, y la papelera (23 ago)

Disco: **1,4 T usados / 1,8 T (80%)**, **364 G libres**. Pinokio es **979 G** (antes 1,2 T).

## Papelera

**Vacía.** Ubuntu/GNOME: `~/.local/share/Trash` = **16 K**, 0 ficheros. No hay papelera de Pinokio ni de Loreframe: lo que borramos de ckpts salió con `rm` directo, no se puede recuperar desde la papelera. `/tmp` y `/var/tmp` no cuentan (pocos MB).

## Dónde está ahora (de mayor a menor)

| Sitio | Tamaño | Qué es |
|---|---|---|
| **Maestro-next.git** (Lab viva) | **399–445 G** | Lo que usas: ckpts 379 G, vendor H3 51 G, Hunyuan env 10 G, outputs 14 G, venv 13 G |
| **wan.git** | **143–152 G** | App Wan antigua. 47 G son basura Gradio (`cache/GRADIO_TEMP_DIR`) |
| **Maestro.git** (Lab vieja) | **143–155 G** | **Ya sin ckpts.** Queda vendor MiniMax H3 105 G, env UniRig 12 G, venv 13 G, outputs 9,5 G, loras 7,5 G |
| **pinokio/cache** | **~79–140 G** | TMPDIR 57 G + UV 74 G (UV está *hardlinkeado* a los env: limpiarlo libera poco) |
| Hunyuan3d-2-lowvram.git | 52–59 G | App Hunyuan aparte; Lore ya tiene Hunyuan |
| PID / Cosmos / Pixal3d | 37 + 34 + 34 G | Apps Pinokio sin uso desde mayo/junio |
| ods | 27 G | modelos Comfy/whisper fuera de Pinokio |
| ulimited-ocr, voxcpm, whisper, Sana, GNM | 17+14+7,5+7+3 G | otras apps |
| `~/.cache/hy3dgen` | 7 G | cache Hunyuan viejo, **no** es el de Lore |
| pinokio/bin | 12 G | miniforge/npm del sistema Pinokio — no tocar |

Dentro de la Lab viva, los ckpts gordos: MiniMax H3 **115 G** (varios quants), model3d **54 G** (2mini+2+2mv+**DiT 11 G**), Gemma-3 13 G, LTX distilled 18 G en los .safetensors sueltos, etc.

## Qué se puede borrar con poco riesgo (si confirmas)

| Qué | Libera de verdad | Nota |
|---|---|---|
| `pinokio/cache/TMPDIR/tmp88tr04al` + `tmphs_247l0` | **~58 G** | Dump ACE-Step del **1 jun**. Nadie lo usa |
| HunyuanDiT **en next** (`…/HunyuanDiT-v1.1-Diffusers-Distilled`) | **11 G** | Desactivado; colgaba la GPU |
| `~/.cache/hy3dgen` | **7 G** | Copia vieja fuera de Lore |
| wan `cache/GRADIO_TEMP_DIR` | **47 G** | Temporales Gradio de Wan |
| **Maestro.git entero** | **~100–140 G** | Los ckpts ya no están. El vendor H3 de 105 G es copia; next tiene el suyo (51 G). Outputs viejos 9,5 G se van con ella |
| Hunyuan3d-2-lowvram.git | **~59 G** | Hunyuan ya está en Lore |
| wan.git entero (si no abres Wan) | **~150 G** (47 ya en Gradio) | Vídeo Wan; Lore hace H3 |
| Cosmos + Pixal3d + PID | **~105 G** | Sin uso mayo/junio |

**No limpies `UV_CACHE_DIR` (74 G) esperando 74 G libres:** torch/CUDA están hardlinkeados con los `env` de las apps. `du` cuenta dos veces; `df` casi no baja.

## Qué NO tocar si quieres seguir generando

- `Maestro-next.git` (salvo HunyuanDiT)
- H3 pruned/legacy que usas para las parodies
- Hunyuan **2mini** + **2 paint turbo** + **2mv** (el que acabamos de mover)
- `app/outputs` de next (14 G, galería)

Si me dices “limpia lo seguro”, hago TMPDIR + DiT de next + hy3dgen (~76 G) sin tocar apps. Si además “fuera Lab vieja y Wan/Hunyuan sueltos”, ahí van ~350 G.

---

# HECHO — movidos a Loreframe y detectados como descargados (23 ago 16:21)

Sí: la Lab los marca **descargados** porque mira el disco, no una lista interna.

| Qué moví a next | Flag en código | ¿Sale como descargado? |
|---|---|---|
| Hunyuan3D **2mv turbo** (9,2 G) | `model3d_service.is_model_downloaded('hunyuan3d-2mv-turbo')` | **True** — pestaña Characters / 3D multi-vista |
| UniRig pesos (5,5 G) | `rig_service.is_unirig_downloaded()` | **True** (los pesos) |
| Gemma-4 heretic Q4 + mmproj (5,9 G) | `_download_gguf` encuentra el fichero | **Sí** — no vuelve a bajar si eliges ese LLM |

Comprobado ejecutando esas funciones en el Python de la Lab, no a ojo.

**Matices:**
- 2mv **fast** y 2mv **full** siguen `False`: en el viejo solo estaba el **turbo**, que es el de Character Creator.
- UniRig pesos = descargados. El **motor** Python aún no: en Pinokio, en Loreframe Lab, hay que pulsar **Install AI Rigging (UniRig)** una vez. Sin eso el auto-rig IA no arranca; el rig procedural sí.
- Gemma: ahora mismo Settings usa MiniMax-M3. Cuando cambies a “Gemma 4 4B Heretic”, no descarga. No hace falta restart para los flags de disco.

**Borrado del viejo (ya no hacía falta):** LTX Dev FP8 28 G, LTX Q6 GGUF 15 G, ACE-Step XL no-SFT 5 G, HunyuanDiT + paint no-turbo, carpetas vacías.

Disco: **80%**, ~**364 G libres**. `Maestro.git` aún ocupa ~155 G (venv, vendor H3, outputs viejos) — eso no son ckpts.

---

# Ckpts únicos del Maestro viejo — mover o borrar (23 ago)

Tras borrar los duplicados 100%, en `Maestro.git/app/ckpts` quedan **~80 G que NO están en la Lab actual**. No son un enlace: son pesos distintos. La Lab nueva **sí los sabría usar** si los mueves a la misma ruta relativa bajo `Maestro-next.git/app/ckpts`. Un `mv` (no copiar) es instantáneo y libera el viejo.

Disco ahora: **83%**, ~305 G libres. `Maestro-next` no se tocó.

## Veredicto corto

| Acción | Qué | Gana / ocupa |
|---|---|---|
| **MOVER (sí se usan)** | Hunyuan **2mv**, UniRig, Gemma-4 heretic | ~21 G útiles, 0 descarga |
| **MOVER si quieres LTX local extra** | LTX Dev FP8 + LTX distilled GGUF Q6 | 28 G + 15 G |
| **NO hace falta** | ACE-Step XL no-SFT, paint Hunyuan no-turbo | ~13 G |
| **BORRAR** | HunyuanDiT suelto, carpetas vacías, `llm/bin` | ~3 G basura |

Lo de Loreframe de diario (H3 MiniMax, Hunyuan 2mini, LTX distilled INT8, ACE-Step SFT) **ya está en next**. No dependes del viejo para las parodies.

---

## 1. Mover — la Lab nueva los pide y no los tiene

### Hunyuan3D 2 Multi-view (`2mv`) — **9,2 G — SÍ MUEVE**

- Qué es: modelo 3D **multi-vista** (frente / izquierda / espalda / derecha). El de una sola foto es el 2mini que ya usamos para el alien.
- Para qué: pestaña **Characters** / ficha de personaje. El flujo H3 órbita → 4 stills → `hunyuan3d-2mv-turbo` está escrito en el código de next. **El cache de 2mv en next está vacío.** Sin esto, el primer Character 3D se baja ~9 G de Hugging Face.
- Cómo: mover la carpeta entera del hub (blobs + snapshots), no un fichero suelto:

```
Maestro.git/app/ckpts/model3d/huggingface/hub/models--tencent--Hunyuan3D-2mv
  → Maestro-next.git/app/ckpts/model3d/huggingface/hub/models--tencent--Hunyuan3D-2mv
```

En el viejo solo está el submodelo **turbo** (`hunyuan3d-dit-v2-mv-turbo`), que es exactamente el que usa Character Creator.

### UniRig (rig IA) — **5,5 G — SÍ MUEVE si vas a auto-riggear GLBs**

- Qué es: predice esqueleto + skin de un GLB (VAST-AI UniRig). Checkpoints `skeleton/…/model.ckpt` + `skin/…/model.ckpt`. Completos (la Lab comprueba que pesen >1 MB).
- Next: el botón **Install AI Rigging (UniRig)** instala el *motor* Python. Los pesos se bajan en el primer rig. En next **no hay** `ckpts/rig`.
- Mover:

```
Maestro.git/app/ckpts/rig
  → Maestro-next.git/app/ckpts/rig
```

Ojo: los pesos solos no bastan si no has instalado UniRig en el menú de Pinokio de **next**. El procedural (CPU, sin UniRig) ya funciona sin esto.

### Gemma 4 4B Heretic Q4 + mmproj — **6,0 G — SÍ MUEVE si quieres LLM local**

- Qué es: `gemma-4-E4B-it-heretic-Q4_K_M.gguf` (5,0 G) + `mmproj-F16.gguf` (0,92 G). LLM local uncensored con visión.
- Next: `llm_service.py` lo tiene como **Recommended**. Ahora mismo `wgp_config` usa **MiniMax-M3** (nube). Si algún día cambias Settings → LLM a Gemma-4 heretic, sin este archivo se descarga otra vez.
- Mover (mismos nombres que espera next):

```
Maestro.git/app/ckpts/llm/gemma-4-E4B-it-heretic/
  → Maestro-next.git/app/ckpts/llm/gemma-4-E4B-it-heretic/
```

`llm/bin` del viejo (libs llama.cpp) **no** se mueve: next tiene las suyas.

---

## 2. Mover solo si quieres más variantes de LTX (no las usamos ahora)

La Lab actual ya tiene LTX **distilled 1.1 INT8** (18 G) + VAE + vocoder + upscalers. Con eso hay vídeo LTX local. Estos dos del viejo son **otras ediciones** del mismo modelo 22B. Next ya tiene las recetas JSON; solo faltan los ficheros en `ckpts/`.

### LTX-2.3 Dev FP8 — **28 G**

- Receta next: `app/defaults/ltx2_22B_fp8.json` → busca exactamente `ltx-2.3-22b-dev-fp8.safetensors`.
- Es la variante **dev** (más calidad, más lenta, más VRAM) frente a distilled. Si el día a día es MiniMax H3, esto no se toca. Si quieres LTX “full” local, un `mv` a `Maestro-next.git/app/ckpts/` y aparece en el selector.
- Si no vas a generar LTX-dev: **borrar**. 28 G.

### LTX distilled GGUF Q6_K light — **15 G**

- Receta next: `ltx2_22B_distilled_gguf_q6_k.json`. Alternativa **low VRAM** al INT8 que ya tienes (ahorra ~1,2 GiB, más lento en Linux).
- Redundante si te cabe el INT8 (RTX 4090). **Borrar** salvo que quieras esa opción GGUF.

---

## 3. No hace falta mover

### ACE-Step XL transformer (no SFT) — **5,1 G**

- Next ya tiene `ace_step_v1_5_xl_sft_transformer_quanto_bf16_int8.safetensors` (la versión **SFT**, la buena para música).
- El del viejo es el XL “plano”, receta `ace_step_v1_5_xl.json`. Duplicado funcional. **Borrar.**

### Hunyuan3D-2 paint **no turbo** + VAE turbo suelto — **~7,8 G**

- Next ya texturiza con `hunyuan3d-paint-v2-0-turbo` (el del alien).
- Lo que queda en el viejo es paint **v2-0** (más lento / un poco más calidad) y `hunyuan3d-vae-v2-0-turbo`.
- Solo mueve si quieres texturas “full paint” en vez de turbo. Si no: **borrar.**

---

## 4. Borrar — no sirven en next

| Qué | Tamaño | Por qué |
|---|---|---|
| HunyuanDiT (text_encoder / text_encoder_2 / vae sueltos) | ~3,2 G | Conditioner **desactivado**. Es lo que colgaba la GPU. Next no lo carga. |
| `models--tencent--Hunyuan3D-2mini` vacío | 28 K | Los blobs ya se borraron (duplicados). |
| `models--tencent--Hunyuan3D-2.1` vacío | 12 K | Stub, no hay pesos 2.1. |
| Carpetas ckpts vacías (wav2vec, depth, mask…) | 4 K c/u | Restos de los duplicados. |
| `ckpts/llm/bin` | ~pocos MB | Binarios llama del viejo. |

---

## Cómo se usarían si los movemos

No hay que “instalar” nada extra para 2mv / LTX / Gemma / ACE: la Lab mira `app/ckpts/` por **nombre de fichero**. Si el archivo está, el modelo sale como descargado.

- **2mv:** primer generate Character 3D deja de bajar 9 G.
- **UniRig:** primer auto-rig deja de bajar 5,5 G, *si* el env UniRig está instalado.
- **Gemma-4:** aparece en Settings → LLM sin descarga.
- **LTX fp8 / Q6:** aparecen en el selector de modelos de vídeo LTX.

Mover = `mv` de carpeta/fichero. Copiar duplicaría disco otra vez. No hace falta symlink: next no apunta al viejo.

---

## Recomendación práctica

1. **Mover ya:** `Hunyuan3D-2mv` + `ckpts/rig` (UniRig) + `llm/gemma-4-E4B-it-heretic`. ~21 G que next usará.
2. **Decidir LTX:** si no generas LTX-dev ni GGUF, borrar **43 G** (28+15).
3. **Borrar el resto** (~16 G: ACE no-SFT, paint no-turbo, DiT, vacíos).

Cuando confirmes, lo hago yo: primero los 3 `mv`, luego el borrado que digas.

---

# Character Creator — H3 ficha, luego Hunyuan (no al revés)

El enlace original es el workflow de [PoopMan333/H3_Character_Sheet_Generator](https://huggingface.co/PoopMan333/H3_Character_Sheet_Generator) (post de SlipperyGem). El truco no es Hunyuan primero.

**Orden correcto**

1. Refs + **A Prompt** (qué se toma / qué se ignora por foto) concatenado al **B Prompt** oficial (A-pose, estatua, órbita 360 0–3 s, close-ups 3–5 s).
2. Un solo pase MiniMax H3 **Ref2VA**, portrait **768×1344**, **124 frames**, 25 steps.
3. Recortar **4 stills** de ese vídeo (frames **2 / 21 / 42 / 63** = frente / izquierda / espalda / derecha).
4. **Después** esas 4 fotos van a Hunyuan3D multi-view (`hunyuan3d-2mv-turbo`) y sale el GLB.

**Lo que vi en Comfy y qué hacemos aquí**

- Custom nodes (KJNodes `MiniMaxChunkFeedForward` / `ModelPatchTorchSettings`, `ModelAttentionBackend` kitchen, rgthree): speed-ups de Comfy. **No se meten en Lore.** El runtime nativo de H3 ya atiende eso.
- LoRA: `minimax_h3_ref2v_turbo_4step` a 0.75. En Character Creator hay un checkbox **Turbo LoRA** que usa el adapter nativo de Maestro. Calidad baja un poco; para ficha final, déjalo apagado.

**Qué estaba mal en Lore:** 864×480, 360 genérico, fotos al 2/25/50/75 % del clip, y ningún Hunyuan al final.

---

# Plastilina: Gandalf pica en Bolsón Cerrado — después de los 3 Vader

Cuando acaben los 3 videoclips de Vader IT: corto 16:9, **1–2 min**, muñecos de plastilina (Aardman). Solo Gandalf llama a la puerta y habla con Frodo.

Diálogo:

- Frodo: Llegas tarde.
- Gandalf: Un mago nunca llega tarde, Frodo Bolsón. Ni pronto. Llega exactamente cuando se propone.
- Frodo: Entra, te estábamos esperando.
- Gandalf: ¿Y el té?

Sin fiesta, sin Anillo, sin Nazgûl.

---

# Trilogía Vader IT — en marcha (3 videoclips)

1. Obi-Wan desplegó un **kernel lleno de errores un viernes** y dejó a Anakin solo → nace Vader.
2. **Le negaron el merge a `main`** / Palpatine le da root / force-push.
3. **«En mi máquina funciona.»** Staging verde, producción Mustafar.

El resto de ideas: `ideas.md`.

Te aviso cuando estén los tres `*_multiclip.mp4`.

---

# Luke y el DELETE sin WHERE — ya está

Videoclip: `app/outputs/minimax_h3_85e4e916_multiclip.mp4`  
Canción: `app/outputs/2026-08-21-09h52m01s_seed769466180_[Estrofa]En la granja de humedad….wav`

---

# Luke y el DELETE sin WHERE — en marcha

Canción + videoclip landscape 16:9. Protagonista: **Luke Skywalker joven** en Tatooine. Lección: no hagas `DELETE FROM` sin `WHERE` porque te cargas toda la tabla.

Estribillo:

> No debes hacer un delete from sin el where  
> porque borras toda la tabla, no solo al imperio  
> si pulsas enter sin filtro, no hay fuerza que la recupere

Te aviso cuando esté el `*_multiclip.mp4`.

---

# Chistes retrato (tanda 2) — en cola

Un vídeo suelto del **presentador** (nunca más sale después) y luego **16 personajes** en 9:16, para montar **2 o 3 vídeos de ~1 min**.

Presentador (`df3f69de`, ~6,6 s): *Oye, tienes diez segundos. ¡Cuenta un chiste!*

Personajes (~3,1 min en total). Packs sugeridos:

**Vídeo 1 (~54 s)**  
Office `a0500d9a` · Friends `e8e7f02a` · Simpson `d2a242e3` · Tyrion `198c6e06` (14 s) · Sherlock `7a071767`

**Vídeo 2 (~54 s)**  
House `3cc80d93` · Walter `429ed304` (14 s) · Sheldon `8b5e4776` · Saul `8de0065b` · Ted Lasso `f1f7e317`

**Vídeo 3 (~62 s)**  
Wednesday `b6f6756c` (14 s) · Jake `57fd8b11` · Geralt `5f0ee2ed` · Doctor Who `6f7f2990` (14 s) · Seinfeld `566a4c1b` (14 s)

Sobra Ron Swanson `0b6ede6f` (14 s) por si quieres alargar el 3 o un extra.

Retrato `544x960`. El presentador no se mete en esos montajes.

---

# No desplieges en viernes — ya está

Videoclip: `app/outputs/minimax_h3_138828b9_multiclip.mp4`  
Canción: `app/outputs/2026-08-20-22h49m45s_seed879588768_[Estrofa]En el pantano el maestro….wav`

Análisis Series/tráilers: `informe.md`

---

# No desplieges en viernes — en marcha

Canción de maestros de cine (tipo Yoda, Gandalf, Miyagi) + videoclip landscape 16:9. El aprendizaje: si despliegas el viernes y se rompe, te comes el finde; los refuerzos no llegan hasta el lunes.

Estribillo (cadencia Yoda):

> En viernes, desplegar no debes  
> si cae producción, el finde te come  
> hasta el lunes no llegan refuerzos  
> en viernes, desplegar no debes

Te aviso cuando esté el `*_multiclip.mp4`.

---

# Fry mala suerte — ya está

Videoclip: `app/outputs/minimax_h3_7d5b4dba_multiclip.mp4`  
Canción: `app/outputs/2026-08-20-18h28m35s_seed46558511_[Estrofa]Pidió una pizza….wav`

---

# Fry mala suerte — en marcha

Canción cómica + videoclip landscape 16:9. Fry de Futurama (dibujo 2D, chaqueta roja) en gags de mala suerte: tropiezos, café, paloma, criogenización, pizza mil años tarde. Sin raperos.

Estribillo:

> Los tipos como Fry tienen mala suerte  
> si hay un hoyo en la calle, él lo encuentra de frente  
> si hay un botón de pánico, lo pulsa sin querer  
> los tipos como Fry tienen mala suerte

Te aviso cuando esté el `*_multiclip.mp4`.

---

# Sysadmins-gremlins — ya está

Videoclip: `app/outputs/minimax_h3_53c5eae3_multiclip.mp4`  
Canción: `app/outputs/2026-08-20-17h17m34s_seed671395397_[Estrofa]Tres reglas en el rack….wav`

---

# Sysadmins que son gremlins — en marcha

Canción + videoclip landscape 16:9. MiniMax Music si deja; si no, ACE-Step y MiniMax M3 escribe los planos.

Mezcla: película Gremlins (1984) + CPD. Criaturas pequeñas, no humanos, no raperos. Tres reglas = no mojar el rack, no deploy después de medianoche, la luz del servidor.

Estribillo:

> Somos sysadmins, somos gremlins  
> el pager nos llama, el cluster se ríe  
> si cae producción, multiplicamos  
> café en el suelo, alarmas, y dientes

Te aviso cuando esté el `*_multiclip.mp4`.

---

# Hobbits — ya está

Videoclip landscape: `app/outputs/minimax_h3_5187197c_multiclip.mp4`  
Canción (ACE-Step): `app/outputs/2026-08-20-13h48m57s_seed520219708_[Estrofa]La colina es verde….wav`

MiniMax Music rechazó otra vez; MiniMax M3 sí escribió los planos.

---

# Última respuesta (hobbits, mientras se generaba)

Va en marcha, mismo esquema que enanos y orcos.

MiniMax Music volvió a rechazar. Está generando la canción en local (ACE-Step): folk de la Comarca, silbato, guitarra, letra en español, sin rap. Cuando exista el WAV, MiniMax M3 escribe los planos y H3 monta el **landscape 16:9** con hobbits de Weta (pequeños, pies peludos, puertas redondas). Nada de raperos.

Estribillo:

> Por el segundo desayuno / por la cerveza y el sol / si el mundo se pone serio / nosotros cantamos igual

Te aviso cuando esté el `*_multiclip.mp4`.

Letra completa:

```
[Estrofa]
La colina es verde, la puerta es redonda
el pan está caliente, la pipa no se apaga
pies peludos en el césped, la tarde se alarga
la Comarca no corre, la Comarca camina

[Estribillo]
Por el segundo desayuno
por la cerveza y el sol
si el mundo se pone serio
nosotros cantamos igual

[Estrofa]
Bilbo guarda secretos, Frodo mira el camino
Sam no deja el huerto, Merry parte el pan
Pippin se ríe bajo el árbol de la fiesta
pequeños, constantes, dueños del jardín

[Estribillo]
Por el segundo desayuno
por la cerveza y el sol
si el mundo se pone serio
nosotros cantamos igual
```

---

# Piezas que ya estaban hechas

**Retrato de enanos** (misma canción que el landscape)  
`app/outputs/minimax_h3_d724fcfe_multiclip.mp4`

**Canción de orcos** (ACE-Step; MiniMax Music cerrado)  
`app/outputs/2026-08-20-12h18m45s_seed835598373_[Estrofa]Nacimos en foso….wav`

**Videoclip de orcos**  
`app/outputs/minimax_h3_6442199c_multiclip.mp4`

**Landscape de enanos**  
`app/outputs/minimax_h3_dcd06270_multiclip.mp4`

---

# Auditoría de prompts — 20 ago 2026

Qué se generó, qué prompt usó H3 de verdad (el de cada `.meta.json`), y qué cambiar.

Vídeo landscape de enanos: `app/outputs/minimax_h3_dcd06270_multiclip.mp4` (quedó bien).

---

## 1. Chistes (45 clips, 3 tandas)

| Tanda | Resolución | IDs |
|---|---|---|
| Landscape 15 | `960x544` | `01f7a55c` … `e8e8508a` |
| Retrato 15 | `544x960` | `5f13d7b1` … `1ff22fd9` |
| Retrato B 15 | `544x960` | `d0697eae` … `07674dd6` |

Forma de todos (igual que el short bueno `aa7b3e3f`):

```
integrated_multimodal_description: [Shot 1] … Dice: <d>[Spanish] …</d>
overall_soundscape: …
non_diegetic_music: N/A
```

### Lo que está bien

- El chiste del JSON coincide **literal** con el `<d>` usado.
- No hay italiano ni letra de canción en el diálogo.
- ~1080 caracteres: compactos, no los 8–10k del planner viejo.
- Resolución correcta por tanda.

### Errores / riesgos

**1. El mínimo de H3 estira el chiste**  
H3 no baja de 5,167 s (124 frames). Un gag de 8–15 sílabas se programa a hablar casi todo el plano. El short bueno tenía dos frases + caminar.

- Solución: negocio mudo (mirada, ceja, pausa) y habla en 1,5–2,5 s; o dos frases cortas.

**2. El personaje no está nombrado junto al `<d>`**  
Bueno: `Mario dice: <d>[Spanish] …`. Chistes: `Dice: <d>…` sin hablante. El VOCAL TIMELINE habla de “assigned speaker” y “every other character” en un plano de una persona.

- Solución: `Michael Scott dice: <d>[Spanish] …</d>`.

**3. Mandaloiano con casco** (`2a394bac`, `761c376e`)  
Pedimos que suelte el chiste. Con visor no hay visemas.

- Solución: voz en off, o casco que no articule.

**4. Un solo estilo para series distintas**  
Casi todos: “Cómic cinematográfico, grano suave, no fotorealismo 3D”. Simpson sí va a 2D; Futurama / Arcane / Rick and Morty deberían ser animación; Alien / Gremlins, cine.

- Solución: preset por serie.

**5. Soundscape genérico**  
Siempre “Sala quieta. Solo su voz.” El bueno describía el suelo (paso sobre empedrado).

- Solución: una línea diegética real (fluorescente, viento, gotera). Sin listas de “no hay X”.

**6. Landscape sin decir 16:9 en el texto**  
La resolución sí era `960x544`. Menor: el short bueno tampoco decía “portrait” y salió bien.

**7. VOCAL TIMELINE LOCK en inglés dentro del visual**  
También está en el short bueno; H3 lo inyecta. El riesgo es el párrafo largo en inglés mezclado con el gag.

- Solución a medio plazo: lock más corto con el nombre del hablante.

### No es error

- Etiqueta `<d>[Spanish]` (el short bueno igual).
- Falta de `PORTRAIT COMPOSITION LOCK` en Studio: Director lo pone en pipelines; el short que gustó tampoco lo tenía. El tensor ya es `544x960`.

---

## 2. Videoclip landscape de enanos (`dcd06270`)

- Canción: MiniMax Music sigue cerrado a usuarios nuevos. WAV local ACE-Step de las 08:27.
- Planner: MiniMax Chat M3 (API, con clave). Sin 401 ni GGUF 404.
- 4 segmentos de audio → 7 planos nativos H3 `960x544`.
- Tratamiento: narrativa, `performer_presence: 0`, sin lip-sync a cámara, sin raperos.
- Salida: `minimax_h3_dcd06270_multiclip.mp4`.

### Lo que está bien en esos 7 prompts

- `[Shot 1]`, 16:9, Weta / Jackson, enanos, sin raperos, sin `<d>`, sin italiano.
- ~1250–1470 caracteres.

### Problemas (aunque el render final gustó)

**1. Poca acción escrita**  
“Frozen mid-strike”, “immovable figures”, “absolute stillness”, “By the final beat…”. El compilador describe un fotograma final, no un plano de 9–12 s. El vídeo puede haber funcionado por el modelo, no por el texto.

- Solución: acción continua (pico, paso, jarra). Prohibir frozen / still / immovable / by the final beat.

**2. `overall_soundscape: Silence` en los 7**  
La canción se mezcla después, pero H3 no genera pico ni forja.

- Solución: una línea diegética (pico, fuego, piedra).

**3. Continuidad sucia**  
`PROJECT CONTINUITY … project world/franchise: No character speaks` — el silencio se coló en el campo de franquicia.

- Solución: silencio solo en el VOCAL TIMELINE; el mundo = Khazad-dûm / antorchas.

**4. Boilerplate en inglés**  
`NO VISIBLE TEXT LOCK` + continuidad + VOCAL TIMELINE ~70% del prompt. La acción útil es una frase al final.

**5. Plano 2: “eyes locked on the lens”**  
A cámara, con `performer_presence: 0`.

**6. `non_diegetic_music: Follow the selected song`**  
En los chistes era `N/A`. H3 podría inventar banda; el rejoin ya pone el WAV.

- Solución: `N/A` y dejar el anclaje al rejoin.

---

## 3. Fallos de MiniMax (ya corregidos en código)

| Síntoma | Causa | Arreglo |
|---|---|---|
| 404 Hugging Face `MiniMax-M3/...gguf` | M3 cargado como GGUF local | `9fad346`: M3/M2.7 siempre a `api.minimax.io` |
| 401 chat completions | Director llamaba a MiniMax sin la clave | Misma commit: pasa `minimax_api_key` |
| Music API “no longer available to new users” | MiniMax cerró Music Generation a usuarios nuevos el 20 ago 2026 | No es un corte temporal. Canción local ACE-Step; planner sigue siendo MiniMax Chat |

---

## 4. Encargo siguiente (este archivo se escribió al lanzarlo)

1. **Retrato de enanos** con la **misma canción**, `544x960`, mismo mundo Weta, MiniMax M3 escribe los planos.
2. Cuando acabe: **canción oscura de orcos** (Tierra Media, no raperos) y videoclip con orcos como protagonistas.

---

# Respuesta: commits, rama, Scenes/3D, español vs inglés

No. En esta tanda no he estado haciendo commits por tarea. El árbol está sucio y nada de lo de esta sesión (política H3 sin audio, Character Creator, `result_kind`, transiciones, pestaña Audit Dev, scripts overnight) está commiteado.

**Rama:** `audit-full-remediation-2026-08-16`, tracking `origin/audit-full-remediation-2026-08-16`, **9 commits por delante** (del 19–20 ago, estilo `feat(…)` / `fix(…)` por área). Encima hay **35 archivos modificados** (~1046/+620) y un montón de scripts/tests sin trackear.

Si quieres commits por tarea, el corte natural sería:

1. H3: 0% descripción de sonido, solo `<d>`
2. Character Creator: 4 stills → Hunyuan + visión M3
3. Galería: `result_kind` + tabs Videoclips/Trailers/Chapters
4. Concat freeze 0.5s + crossfade 0.4s
5. Audit Dev
6. Scripts overnight (o dejarlos fuera del repo)

No commiteo hasta que me digas que sí, y qué entra.

**Scenes y 3D no muestran las películas.** No está roto el filtro: son otras cosas.

| Tab | Qué es de verdad | Qué hay ahora |
|---|---|---|
| **Scenes** | Archivos `.scene.json` del compositor 3D Video, no planos de cine | **1** archivo: `Untitled-scene` del 18 jul |
| **3D** | Mallas Hunyuan `.glb` | **26** modelos del 10–18 jul (9 sin preview) |
| **3D Video** | El editor de capas, no una galería | Panel `SceneAnimatorPanel` |

Las parodias, Bag End, Moria, etc. son **vídeos**. Salen en **Videos**, **Capítulos** (`series_episode` / `chapter`), **Videoclips** (`music_video`) o **Multi-clip**. Nunca en Scenes/3D.

Por eso Scenes parece vacío/inútil y 3D parece un cajón de mallas viejas. Los nombres chocan: Scenes ≠ “escenas de película”, 3D ≠ “3D Video”.

**Qué haría:** no meter mixes en esas tabs. Renombrar **Scenes → Scene files** (o ocultarla si no usas el compositor) y **3D → 3D models**. Las películas siguen en Chapters / Videos.

**Español vs inglés.** El chrome del producto es inglés (`All`, `Images`, `Videos`, `Story Lab`, `Character Creator`). Encima hay parches en español: `Tráilers`, `Capítulos`, `Hoja de estilos`, `Auditoría interna dev`, más botones en Story Lab / Character Creator / Style Sheet (`Generar`, `Cancelar`, `Guardar`). El **contenido generado** (diálogos, cine, Weta) sí debe seguir en español. Eso es política de pipeline, no de UI.

**Sugerencia:** una sola lengua de interfaz, y el contenido generado aparte.

1. **Ahora (lo que haría):** chrome **100% inglés**. `Trailers`, `Chapters`, `Style sheet`, `Audit Dev`. Diálogos y películas siguen en español.
2. **Después, si quieres la app en español:** i18n de verdad (`en` / `es`) con conmutador. No ir traduciendo strings a mano.
3. **No hacer:** seguir mezclando labels. Eso es lo que se siente “lleno de español” en una UI inglesa.

Si me dices “chrome en inglés” lo unifico en un commit. Si prefieres UI en español, el trabajo es i18n, no un find-replace.

¿Commits partidos, chrome a inglés, y renombrar Scenes/3D?

---

# Respuesta: Video Editor — import roto + multiselect

El import se rompía porque el editor buscaba un archivo llamado `minimax_h3_713afac9.mp4?workspace=default`. La query del workspace se colaba en el nombre. En el picker, un clic añadía un solo clip y cerraba.

**Import.** El cliente ahora manda solo el filename al probe. Contra el Lab que está en marcha:

- con query → el mismo error que viste
- con `minimax_h3_713afac9.mp4` → probe OK (`5.167s`, 960×544)

El backend también recorta esa query (para drafts viejos y export). Eso no entra en el proceso actual hasta un reinicio de Lab; no lo he tocado porque parodies2 sigue generando.

**Multiselect.** En **From Loreframe Lab**: clic = toggle, Shift-clic = rango, Select all shown, **Add N videos**. El orden de selección es el de la timeline.

Recarga fuerte Video Editor (`Ctrl+Shift+R`). Luego abre el picker, marca varios y pulsa Add.

No pude pulsar el picker en el navegador (no hay browser tools aquí); lo cubren tests de UI y el curl al probe.

`grokrespuesta.md`, `ideas.md` e `informe.md` son notas locales. No se commitean.

---

# Respuesta: Die Hard Nakatomi habla sinsentido (sin `<d>`)

El prompt que pegaste es el que se mandó de verdad (`minimax_h3_d3166bc6`). No hay `<d>`, y `overall_soundscape` / `non_diegetic_music` ya son `N/A`. Eso no basta.

H3 es un modelo conjunto imagen+audio. Si ve a **John McClane** 10 s en un **still** (“1988 action still”), inventa catchphrases. N/A no es “no hables”; es “no describas el sonido”. El hueco lo rellena él.

**Qué faltaba en las reglas**

- Sin `<d>`, toda cara visible mantiene **labios cerrados y mandíbula quieta**. Eso es actuación visible, no una nota de audio. MiniMax lo usa así en sus guías.
- Hay que **llenar la duración con acción física**. Un still de un personaje que en la peli habla = frases inventadas.
- No asignar `(S1)` si no hay línea. No escribir silencio, “nadie habla”, ni quiet time.

**Qué cambié en código (aún no está en el Lab en marcha)**

- El compilador, si no hay `<d>`, añade: `On-screen faces keep lips closed and jaws still while physical action continues.`
- Guías LLM: lo contrario de “no instruyas bocas”. Eso era el error.
- Planos mudos de Forrest / Home Alone / Gladiator / Pan / Scarface: más movimiento. Die Hard y Vader gofres ya estaban en cola con el prompt viejo.

No regenero Nakatomi ahora: parodies2 sigue (Vader gofres). El arreglo entra en **jobs nuevos** tras reiniciar Lab. Si quieres, cuando acabe esa tanda rehago el plano Nakatomi.

Tests: 110 passed (`test_h3_director_dialogue` y prompting).

---

# Cómo se hicieron los clips (no fue Lore / Story Lab)

No abrí Story Lab, Series Lab ni un Lore. No hay proyecto de Director guardado para estas tandas.

**Fueron scripts Python que yo escribí**, con los planos y las frases en el propio archivo, y luego `POST /api/v1/generate` a MiniMax H3 nativo, un job por plano.

## Películas / parodias / Bag End

1. Yo inventé cada plano: `visual` (inglés, plastilina Weta) y, si habla, `line` (español).
2. El script arma un Context-IR a mano:

```
integrated_multimodal_description: [Shot 1] {estilo} {visual} <d>[Spanish] {línea}</d>
overall_soundscape: N/A
non_diegetic_music: N/A
```

3. Lo manda a H3 (`minimax_h3_legacy`, 960×544, 20 steps).
4. Cuando acaban los planos, ffmpeg los junta (`overnight_*_multiclip.mp4`) y escribe un `.meta.json` con `result_kind: series_episode` para que salgan en Capítulos.

Archivos: `scripts/overnight_parodies2.py`, `overnight_surprise.py`, `overnight_iconic.py`, `claymation_bagend.py`, `queue_joke_round.py`.

Bag End sí pasa el prompt por `compile_h3_clip_plans` (el compilador de diálogo de Director) **en el script**, no abre el panel de Director.

## Videoclips

La canción no es MiniMax Music (410). Es **ACE-Step local** vía `/api/v1/director/generate-music`. Los planos de vídeo son el mismo truco: prompts míos + H3. Luego se muxea el WAV encima → `*_mv.mp4`, `result_kind: music_video`.

## Qué no es

| | ¿Lo usé? |
|---|---|
| Story Lab / un “Lore” | No |
| Series Lab | No |
| Cola Director en la UI | No |
| LLM desglosando la historia en planos | No (excepto el compilador H3 en Bag End) |
| Prompts escritos por mí en Python | Sí |

Por eso no aparecen como proyecto en Story/Series: son jobs sueltos de Studio + un concat. La UI solo ve los mp4 y el sidecar.

---

# Respuesta: sistema vs scripts, salto a Videos, tabs vacías, ACE-Step

**¿Hemos probado “nuestro sistema”?**  
No, no para estas tandas. Los clips overnight son `POST /api/v1/generate` + concat. Eso **sí usa el runtime H3 nativo de Lore** (mismo modelo, mismo compilador de prompts). **No** usa Story Lab / Series Lab / Director UI. Si quieres vender “hecho con nuestro sistema de producción”, hay que hacer una tanda por Story Lab (historia → planos → Generate). El motor de vídeo es el mismo; el producto de venta es el flujo de Lore, y ese flujo no se ha ejercitado en estas parodias.

**Salto / refresh al acabar un vídeo**  
Al terminar un job se recargaba toda la galería. Ahora: mini aviso abajo (~4 s) y **no se recarga** si estás en Story Lab, Video Editor, o en Videos pero scrolleado. Recarga solo si cambias a una tab de galería o subes al tope de esa tab.

**Tabs vacías / cola en Images / Trailers**  
Images/3D/Scenes filtraban los 100 archivos más nuevos (casi todos mp4), así que 3D y Scenes salían vacíos y la cola de H3 se veía en todas. Ahora cada tab pide su tipo al servidor. La cola de vídeo solo se muestra en All/Videos. Trailers vacíos ya no tapan la columna con la queue.

**MiniMax Music**  
No se elimina. Default = **ACE-Step 1.5 XL**. Story Lab puede seguir eligiendo Music 3.0/2.6. El escritor de canciones usa la guía ACE-Step (STYLE en prosa + letras con [Verse]/[Chorus]) cuando el modelo es ACE-Step.

Recarga fuerte (`Ctrl+Shift+R`). Gallery/tabs son UI; no hace falta reiniciar Lab para eso.

---

# HOWUSEIT 3D compositor (fase 1)

Guía para agentes: `docs/3d-video-compositor/HOWUSEIT.md` (índice en `docs/HOWUSEIT.md`).

Idea: MiniMax H3 no pinta *esa* nave. Hunyuan hace el GLB, el compositor **3D Video** la mueve sobre un fondo (imagen o vídeo H3), Record saca WebM, Video Editor lo corta con los planos H3.

Límites de hoy: no hay `POST /scenes/render`. Grabar es el navegador (canvas de model-viewer). Guardar escena pide un PNG de preview. GPU: no Hunyuan y H3 a la vez.

Fase 2 (no hecha): intención → JSON de escena + MP4. Fase 3: usarlo como tipo de plano en trailers / videoclips / series.

---

# LLM escribe, la página ejecuta y guarda MP4 — ¿hasta dónde?

Entendí **MP4** (vídeo), no mp3.

**Hoy (~60–70%).** Un agente ya puede: generar fondos H3/imagen, Hunyuan GLB, rig, y un JSON de escena. La página **aún no** orquesta eso sola ni graba sola. Record es un clic humano (MediaRecorder en el canvas de 3D Video). El WebM se descarga; no entra solo a la galería.

**Sí es posible que lo ejecute la propia página** (mejor que un script Python): un botón “Ejecutar receta” que 1) llama a las APIs, 2) monta las capas, 3) espera a que el GLB pinte, 4) graba el canvas, 5) sube el vídeo y lo deja en Outputs. Eso es fase 2. Falta ese orquestador y el upload del WebM→MP4. No hace falta un renderer 3D en el servidor si el navegador ya pinta.

**No es posible hoy** sin ese trabajo: intención en texto → MP4 en galería, cero clics.

---

# Video Editor (hecho, recarga fuerte)

- **All gaps** + Apply to all: una transición para todos los huecos; cada hueco se sigue pudiendo cambiar a mano.
- **Bordes del clip** en la timeline: arrastra inicio/fin despacio (80 px ≈ 1 s). No deja el clip por debajo de 0,4 s.
- **Auto-scroll** al arrastrar un clip cerca del borde izquierdo/derecho, lento.
- **Split** en el playhead (también en la secuencia completa). Antes fallaba porque al seleccionar un clip el cabezal saltaba al inicio.
- **Barra de seek** más gruesa; en un clip suelto ahora recorre ese clip, no se queda a 0.

---

# Cómo haríamos “LLM escribe, la página graba el MP4”

En el **navegador**, no un script Python overnight. El canvas de 3D Video ya sabe pintar el GLB (copia el canvas de `model-viewer`). Un renderer 3D en el servidor no hace falta.

Guía para el agente: `docs/3d-video-compositor/HOWUSEIT.md` (índice en `docs/HOWUSEIT.md`). Diseño de esta fase: **§11**.

1. El LLM **solo** saca un JSON de receta (sin prosa). Sistema = ese HOWUSEIT + un schema. Campos:
   - `assets[]`: `{ id, kind: image|video|model3d, prompt, model/preset }`
   - `scene`: width/height/fps/duration + capas que apuntan a esos ids + un preset de movimiento (`space-cruise`, `landing`, `meteor`, …)
   - `record: true`
2. Un botón **Run recipe** en la pestaña **3D Video**:
   1. Crea cada asset con las APIs actuales (generate / Hunyuan). Poll hasta `completed`. **Nunca** Hunyuan mientras H3 está muestreando.
   2. Reescribe `source` de cada capa a `/api/v1/file/<filename>`.
   3. `replaceScene(scene)` y espera a que cada capa `model3d` tenga canvas pintable.
   4. Llama al Record actual, pero en `MediaRecorder.onstop` **sube** el blob (`POST /api/v1/upload`) en vez de solo descargar.
   5. Opcional: transcode WebM → MP4 con FFmpeg, luego galería.
   6. `POST /api/v1/scenes` con un PNG de preview para que quede en **Scenes**.
3. Si falla: escena parcial + toast; no saltar de pestaña.
4. Luego **Video Editor** junta esos MP4 con planos H3.

Ejemplo que cubre esto: ovni detrás de montañas + crucero espacial = dos records del compositor + un plano pueblo H3, cortados en el editor.

**Eso es fase 2. No está implementado.** Un agente hoy puede generar assets y el JSON; grabar el MP4 sigue siendo un clic humano.

**Fase 3** (después): Director marca algunos planos `tool: compositor` dentro de Story Lab / trailers / videoclips / series. Solo cuando la fase 2 ya devuelve un MP4 al mismo pipeline de galería / `result_kind`.

---

# Git / release (respuesta completa)

**Rama:** `audit-full-remediation-2026-08-16`  
**Remote:** `origin` → `IAnMove/loreframe-studio` (`git@github.com:IAnMove/loreframe-studio.git`)  
**Push:** hecho (`91f6fee..4d4f780`). Tracking configurado.  
**No** está mergeada a `main`. Para soltar release: PR o merge de esta rama a `main` cuando tú lo digas.

Commits de esta tanda (los 8 de arriba hacia `4d4f780`):

| hash | mensaje |
|---|---|
| `5b38a06` | `feat(h3): keep mute shots visual-only and close lips` |
| `725fcdb` | `feat(characters): capture four H3 stills before Hunyuan` |
| `108a308` | `feat(mix): tag assembled results and soften clip joins` |
| `8901863` | `feat(video-editor): import Lab clips and edit the timeline` |
| `fdfef61` | `feat(gallery): filter mixes by kind and stop jumping the feed` |
| `1fe5ea1` | `feat(music): default new songs to ACE-Step` |
| `6405605` | `feat(api): wire sheet describe-refs, mix kinds, and media refs` |
| `4d4f780` | `docs: add a HOWUSEIT guide for the 3D Video compositor` |

Qué entra en cada uno, en corto:

1. **H3** — planos mute sin describir sonido; lock de labios cerrados; `overall_soundscape` / `non_diegetic_music` = N/A; solo `<d>` cuando hay diálogo.
2. **Characters** — 4 stills de un pase H3 y luego Hunyuan; no Hunyuan-first.
3. **Mix** — `result_kind` (videoclips / trailers / chapters) + concat suave (hold 0,5 s + fade 0,4 s).
4. **Video Editor** — import desde Lab (`?workspace=`), multiselect, timeline.
5. **Gallery** — filtros por tipo; Images/3D/Scenes piden su media; toast al completar en vez de saltar a Videos.
6. **Music** — ACE-Step por defecto en canciones nuevas; MiniMax Music 410 sigue opcional.
7. **API** — describe-refs de ficha, mix kinds, media refs.
8. **Docs** — `docs/3d-video-compositor/HOWUSEIT.md`.

**Fuera del commit a propósito** (no los subas):

- `grokrespuesta.md`, `ideas.md`, `informe.md`
- todos los `scripts/overnight_*`, `scripts/*_mv.py`, pipelines/song JSON, logs de generación

**Lab en vivo:** no lo he reiniciado. parodies2 / H3 siguen. El Python que está sirviendo es el de **antes** de estos commits hasta que reinicies. La UI nueva sale con recarga fuerte (`Ctrl+Shift+R`) si `ui/dist` está reconstruido; el backend (H3 mute, media refs, mix) no se entera hasta restart.

upstream Maestro (`Blizaine/Maestro`) no se ha tocado.

---

# Video Editor: Play desde el clip/transición y cabezal preciso

**Por qué no iba fino:** la barra nativa (`<input type="range">`) mapea toda la secuencia a unos pocos píxeles, y cada movimiento llamaba a `startSequenceAt`, que remonta los `<video>`. El `requestAnimationFrame` leía el `currentTime` viejo (el seek HTML5 es asíncrono) y **devolvía el cabezal** al sitio anterior. Por eso no podías dejarlo en el segundo exacto.

**Qué hace ahora**

1. **Clic en un clip** → el cabezal va al **inicio de ese clip** (pausa). Play arranca ahí y sigue el resto de la timeline.
2. **Clic en una transición** → el cabezal va al **inicio de esa transición** (corte, crossfade, o tarjeta “Momentos después”). Play arranca ahí.
3. **Barra nueva** (no el range nativo): arrastras con el puntero a cualquier punto de la secuencia. En el mismo clip **no remonta** el vídeo: escribe `currentTime` en el elemento vivo.
4. **Campo `s`** a la derecha: escribes `12`, `12.50` o `1:02.25` y Enter/blur. Paso 0,01 s.
5. Teclado con la barra enfocada: flechas 0,1 s, Shift+flecha 1 s, Alt+flecha 0,01 s, Home/End.

Play en el medio de la timeline sigue desde el cabezal. Si estás al final, vuelve a empezar en el clip o la transición que tengas seleccionado. El botón de rewind sigue yendo a 0.

Recarga fuerte (`Ctrl+Shift+R`) después de reconstruir `ui/dist`. Lab no se reinicia.
