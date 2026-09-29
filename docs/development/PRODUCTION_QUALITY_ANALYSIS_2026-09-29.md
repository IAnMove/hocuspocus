Por qué bajó la calidad de los videoclips de Sol (2026-09-29) y qué se cambia en HocusPocus

DATOS (workspaces de 42017; segmentos reales de cada producción)
| producción | duración | clips H3 | tiempo en imágenes fijas | seeds canción | max_takes | planos cantados |
| omarchy-riso (Sol)       |  76 s | 7  | 25 % | 3 | 3 | 3 |
| omarchy-neon (Sol)       | 178 s | 10 | 32 % | 3 | 1 | 0 |
| musk-tomorrow (Sol)      | 162 s | 9  | 48 % | 3 | 1 | 0 |
| three-minds (Sol)        | 166 s | 8  | 56 % | 3 | 1 | 0 |
| open-ai-commons (Sol)    | 164 s | 9  | 43 % | 3 | 1 | 0 |
| gremlins v1 (Sol)        | 160 s | 9  | 54 % | 1 | 1 | 0 |
| gremlins v2 (Claude)     | 120 s | 17 | 0 %  | 3 | 2 | 3 |
Ningún tramo congelado tras el final del clip (0 s en todos): el problema no son bugs, es presupuesto.

CAUSAS
1. Duración x2 con los mismos clips. Las últimas piezas duran 160-178 s pero llevan 8-10 clips H3 (el presupuesto del
   documento GPT_SOL6: "25-35 min de GPU, 5 planos"). El resto son imágenes con zoom lento: 43-56 % del metraje, planos de
   6-9 s. El vídeo de riso (76 s, 75 % en movimiento) es el que mejor se ve.
2. Sin puerta de calidad. max_takes 1 y sin planos cantados: qa.lipsync no corre (veredicto "ok" por defecto), así que
   se acepta el primer clip sea cual sea. Los cuatro chequeos de review son de código (barras, congelado, título,
   personas) y no ven una mala composición ni criaturas duplicadas.
3. Menos selección donde sí había: gremlins v1 usó UNA semilla de canción (sin candidatos), imágenes con Klein (4 pasos)
   en casi todas y personajes con parecido a Yoda/Gremlins.
4. Instrucciones que premian gastar poco: "< 20k tokens", "no mires clips ni escenas, solo la hoja final" y "como
   mucho una corrección". Optimiza coste, no resultado.
5. Detalles de acabado: rótulos pequeños (3,3-3,7 %), el mismo still reutilizado 3 veces, el mismo fill repetido.

QUÉ ENTRÓ EN HOCUSPOCUS (#608; después #613 paquete editable y #614 quality/clips al llegar/hoja de fotogramas; #624 panel y comandos de edición)
- dry_run avisa antes de gastar GPU: too_static (>35 % en imágenes fijas), long_shot (>10 s), still_reused (>=3 usos),
  single_take (max_takes 1) y few_song_seeds (<3), y devuelve motion {static_ratio, longest_shot_s, avg_shot_s}.
- shots:"auto" ya no mete escritorios Tokyo Night: los planos sin cantar son clips H3 cortos (o stills si los hay).
- Frames y hojas de cast se reintentan con job nuevo (el diario devolvía el job fallido) y más pequeños tras un OOM; si aun
  así falta un frame el run se para con frames_incomplete y status lista frame_failures. Antes 13 de 17 frames de Qwen
  con tres referencias se perdían en silencio.
- cast[].count: el prompt del frame añade "Exactly N distinct subjects, no duplicated characters" (una hoja con varias
  vistas hacía que Qwen dibujara al personaje 3 veces).
- Jobs perdidos por reinicio de cola no cuentan como toma; auto-resume solo si se pide; already_running; revisión de status
  cacheada y fuera del bucle de eventos.

LO QUE FALTA (siguientes pasos, por orden de impacto)
1. Perfil "quality" en el spec (draft | standard | max): fija seeds>=3, max_takes>=2, image_steps de Qwen, plano medio
   <= 4-5 s y un mínimo de clips por minuto (>= 7). dry_run ya lo mide; falta que production.plan lo aplique.
2. Puerta de calidad para clips no cantados: movimiento medio del clip, número de criaturas por plano y coherencia de
   color con la hoja de cast, con retoma automática por semilla (hoy solo hay lip-sync para los cantados).
3. Referencias de grupo: cast[].group=[ids] que construya la imagen compuesta (yo la hice a mano con ffmpeg) para no
   pasar 3 referencias a Qwen.
4. Acción del plano sin "otros": H3 inventa criaturas cuando la acción menciona a otros (pasó con "los otros dos
   rebotan"); el planificador debe escribir "solo X en el plano" en planos de un solo personaje.
5. Rótulos: tape/dymo con letras troqueladas es ilegible sobre fondos oscuros; el estilo por defecto de letra debe llevar
   caja crema y texto oscuro (o la app debe avisar con text_low_contrast en la exportación de producción).
6. Instrucciones para agentes: quitar el tope de 20k tokens y "una sola corrección"; mirar la hoja de contactos completa y
   un fotograma a tamaño real de cada plano cantado antes de entregar.
