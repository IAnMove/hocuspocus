# Validación local de FLUX 3 y Drama 3 — 2026-10-16

Pruebas reales mediante los comandos HTTP de HocusPocus, partiendo de
`development` `15ad9232aa58`. Equipo: Linux, RTX 4090 de 24 GB y 64 GB de RAM.
Se usaron los pesos y revisiones fijados en la
[guía de generación](FLUX3_DRAMA3.md). No se llamaron proveedores LLM externos.

## Resultados

| Prueba | Configuración | Resultado | Tiempo de la tarea |
| --- | --- | --- | --- |
| FLUX texto → imagen | 1280×720, 16 steps, Euler/simple, CFG 1, seed 42 | PNG revisado visualmente | 11,07 s |
| FLUX edición | Una imagen, mismos ajustes, seed 43 | Nuevo encuadre del mismo zorro de cobre y cristal | 13,37 s |
| FLUX con dos imágenes | Imagen principal y una referencia adicional, seed 44 | El personaje dentro del mundo del cubo | 16,39 s |
| FLUX con seed aleatoria | 512×512, 4 steps, seed solicitada −1 | Seed efectiva positiva guardada en metadatos | 8,95 s |
| Drama voz nueva EN | INT8, cache 12 GB, temperature 1, top-p 0.9, top-k 30, seed 46 | Audio no silencioso, 5,48 s, palabras completas | 239,52 s |
| Drama voz nueva ES | Mismos ajustes, seed 47 | Audio no silencioso, 5,76 s, palabras completas | 184,18 s |
| Drama clonación EN | Referencia sintética EN anterior, seed 48 | 17,09 s, WER 0, sin avisos de QA | 199,46 s |
| Drama clonación ES | Misma referencia sintética EN, seed 57 | 12,86 s, WER 0, sin avisos de QA | 115,72 s |

Los tiempos salen de `generation_time` de los metadatos de cada archivo: incluyen
arranque/carga, inferencia, codec y cierre; no incluyen espera en cola. No son un
benchmark estable: se ejecutaban comprobaciones de desarrollo en el mismo equipo.
No se confirma tiempo real para Drama en esta instalación. El muestreo parcial
de VRAM observó hasta 21.831 MiB para el dispositivo completo; no constituye una
medición aislada del pico de cada modelo.

Whisper transcribió las frases de prueba cortas correctamente. En inglés separó
«Hocus Pocus», lo que eleva el WER si se compara literalmente con «HocusPocus».
Las dos locuciones finales no tienen omisiones ni añadidos según el servicio
`qa.speech`, normalizando nombres y números. Esto evalúa las palabras, no prueba
por sí mismo la calidad perceptiva, el acento ni la similitud entre voces.

Se probaron dos referencias en GPU. El contrato y la construcción del grafo se
comprobaron hasta diez, conservando el orden y rechazando una undécima; no se
ha medido el consumo de diez imágenes ni 4K.

## Fallos detectados y correcciones

- Dos primeras solicitudes de voz fallaron por interpretar el marcador inactivo
  de outpainting de WanGP (`#`) como una edición. El validador ya lo reconoce.
- La primera edición de imagen detectó el nuevo campo obligatorio
  `resolution_steps` de ComfyUI; el grafo fija 16 y la repetición se completó.
- Una locución inglesa llegó a generarse pero se perdió su publicación al agotar
  el timeout de una consulta de estado. La supervisión ahora reintenta consultas
  transitorias mientras el proceso sigue vivo, comprueba cancelación y mantiene
  un límite de una hora. La repetición pasó hasta la publicación nativa.
- Una toma española de clonación terminó a los 2,83 s sin completar la frase.
  Se descartó por QA y se repitió con otra semilla y referencia. INT8 también
  requiere revisar cada toma.

El catálogo web generado se sincronizó con el contrato ejecutable de voz. Studio
expone una grabación y transcripción obligatoria para clonar, o una dirección
opcional para voz nueva, con etiquetas en inglés y español. La preparación evita
que nombres o referencias de antiguos slots de voz alteren el texto de Drama.
Los modelos se agrupan en FLUX 3 y Text to Speech, respectivamente, para que
aparezcan en los selectores de imagen y audio. La seed aleatoria se resuelve antes
de llamar a ComfyUI y los metadatos conservan la seed efectiva de cada repetición.
La galería de Audio reconoce las salidas FLAC de Drama, además de WAV y MP3.

## Evidencia y reproducción

El workspace local `flux3-drama3-showcase` contiene PNG, FLAC y sus `.meta.json`.
Los comandos, recibos, tareas terminales y resultados de QA se conservan en
`logs/creation-validation/`; los medios y las credenciales están excluidos de Git.
El cliente [creation_job.py](../../pinokio_agent/skills/api/hocuspocus/clients/creation_job.py)
puede repetir la observación de un intent sin duplicar su generación.

Los cortos se componen con las tres imágenes, la voz aprobada de cada idioma,
movimientos de cámara, fundidos y títulos. Se guardan como escenas Video 2D
editables y se exportan con el compositor nativo. Son cortos narrados; no son una
prueba de animación corporal ni de lip-sync.

Versiones finales: `hocuspocus-flux3-drama3-en.mp4` (**18,708 s, 449 frames**) y
`hocuspocus-flux3-drama3-es.mp4` (**14,5 s, 348 frames**), ambas 1280×720 a 24 fps,
H.264 y AAC, calidad final. Exportación: 147,68 s y 119,58 s, respectivamente.
Se revisaron fotogramas de títulos y cierre y se volvió a transcribir el audio
de los MP4: **WER 0 en ambos**. QA señala el silencio de 1,4 s del cierre,
previsto para dejar leer la tarjeta final. Cada corto tiene una escena editable
con nombre terminado en `EN - final` o `ES - final` en el mismo workspace.

Comprobaciones: 356 tests de contratos dirigidos, 50 de caracterización del
servidor, 3.145 tests UI y 31 dirigidos de voz/catálogo tras añadir sus controles,
además de las regresiones de seed y agrupación. Los grupos se solapan; no son un
total de tests diferentes. Playwright: **107 pasados, 3 omitidos**. Lint, build,
i18n, guardas de repositorio/documentación y ratchet de complejidad pasados.

## Coste de la tarea

- Tests simulados: 0 tokens externos.
- Llamadas LLM externas: 0; tokens de Codex: N/A.
- Solicitudes locales de generación admitidas: 13, incluidos reintentos.
- Salidas producidas por modelos: 4 imágenes y 6 audios. De esos audios, uno quedó
  sin publicar por el timeout corregido y otro fue descartado por texto incompleto.
- Exportaciones locales de vídeo: 4 (dos primeras versiones y dos finales).
- Proveedores/modelos: FLUX 3 Klein distilled INT8 y Drama 3 INT8 locales; Whisper
  small en CPU para QA. No se entrenó un modelo ni se usó una voz de persona real.
