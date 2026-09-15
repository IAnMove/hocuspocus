# YuE2, AuK y la web móvil de Deepy

Fuente: [WanGP 13.00](https://github.com/deepbeepmeep/Wan2GP/tree/09a6c1dad469fc3a2dc7577b9ab0a08254be9ad2),
anunciado el 13 de septiembre de 2026. La adopción de audio conserva la cola,
los comandos, los IDs de trabajos y la galería de HocusPocus.

## Deepy en el teléfono: investigación

La [guía oficial de Deepy](https://github.com/deepbeepmeep/Wan2GP/blob/09a6c1dad469fc3a2dc7577b9ab0a08254be9ad2/docs/DEEPY.md)
describe una web adaptada al móvil, con Chat, Imagen/vídeo, Audio y Ajustes.
El teléfono envía instrucciones y archivos al ordenador que ejecuta WanGP;
la generación sigue en ese servidor. Cerrar el navegador no detiene los trabajos
aceptados mientras el proceso continúa funcionando.

Desde la interfaz de WanGP se abre con **Deepy → Settings → Web app →**.
Comparte conversación, medios seleccionados, progreso y cola con Gradio cuando
ambos clientes usan el mismo proceso. Los borradores de generación que aún no se
han enviado siguen siendo propios de cada página Gradio.

- Con WanGP normal: `http://IP-DEL-PC:7860/deepy/`, si escucha en ese puerto
  y admite conexiones de la red local (`--listen`).
- Modo web independiente: `python wgp.py --deepy-server --listen --server-port 7860`;
  abre `http://IP-DEL-PC:7860/`. Es otro proceso: no se conecta a una instancia
  ya abierta ni comparte automáticamente su trabajo activo.
- iPhone: Safari → Compartir → Añadir a pantalla de inicio. Android: Instalar
  aplicación o Añadir a pantalla de inicio, según el navegador.
- Permite subir fotos y grabaciones, consultar conversaciones, reproducir y
  descargar resultados, pausar o detener trabajo y cambiar sesiones guardadas.
  En teléfonos, el dictado usa el teclado del sistema.
- Funciona con Zero y Prime; la guía presenta Prime para tareas con varios pasos.
  Los ajustes completos y algunas operaciones de sesiones siguen en Gradio.
- Para acceso fuera de casa, la guía recomienda VPN. `--auth` activa una
  contraseña compartida de acceso web; HTTPS protege la conexión y puede ser
  necesario para funciones del micrófono del navegador.

HocusPocus ya tiene su propio Wizard, API y cola. Esta integración de audio no
instala el servidor Deepy ni añade `/deepy/` a HocusPocus. Portar esa interfaz
exigiría adaptarla a las sesiones, referencias y comandos propios; copiar sus
archivos web no bastaría para compartir el estado de HocusPocus.

## Audio incorporado

| Modelo | Ubicación | Entradas y resultado |
| --- | --- | --- |
| YuE2 (`yue2`) | Audio → Música | Letra literal + estilo; canción estéreo a 48 kHz. Planificación de melodía y acordes, solo melodía o generación directa |
| AuK (`auk`) | Audio → Voz | Instrucción completa; audio fuente opcional. Voz, clonación, edición de palabras, limpieza y selección de hablante; mono a 24 kHz |
| AuK Flash (`auk_flash`) | Audio → Voz | Mismas entradas, receta fija de cuatro pasos sin CFG |

Los modelos se añaden al catálogo habilitado una sola vez mediante la migración
de preferencias v12. La selección actual se conserva. Los pesos faltantes se
instalan mediante el gestor de modelos existente; los comandos duraderos
rechazan la admisión si faltan los archivos requeridos.

YuE2 conserva `prompt` como letra y `alt_prompt` como estilo. `model_mode` es
0/1/2. La duración de 1–600 segundos es un máximo, no una duración garantizada.
El contrato Story mantiene su mínimo editorial de 20 segundos; Studio admite el
mínimo nativo de un segundo. Esta adopción cubre generación desde letra/estilo;
no expone covers mediante SheetSage2, importación ABC ni exportación ABC/MIDI.

AuK conserva la instrucción exacta, sin convertir nombres en `Speaker N:`.
El selector admite texto (`audio_prompt_type=""`) o una fuente (`"A"`). La
referencia usa el selector de recursos existente, tanto biblioteca como subida.
Base admite pasos y guidance; Flash fija 4 pasos y guidance 0. El límite nativo
es 300 segundos, con 5 segundos iniciales. Si se usa una referencia, se procesa
su inicio y la duración del resultado no supera la del clip ni el límite elegido.
La clonación requiere una muestra al menos tan larga como la salida deseada.

Ejemplos de instrucciones documentadas por upstream:

```text
Say the following with the same voice: "Welcome back."
Replace "tomorrow" with "next week", keeping the same speaker and tone.
Remove background noise and reverberation while preserving all spoken words and speakers.
Keep only the second speaker in order of appearance and remove the other speakers.
```

AuK produce una grabación nueva: una edición no conserva exactamente la onda
original. Upstream documenta inglés y chino; no acredita español. Los pesos de
YuE2 son CC BY-NC 4.0; el componente Qwen de AuK tiene condiciones de
investigación/evaluación. Los archivos de licencia del código se conservan y las
licencias de componentes descargados forman parte de sus recursos.

## Procedencia y compatibilidad

[upstream.json](../../app/shared/wangp1300/upstream.json) registra commit, rutas
y hashes originales. Los recursos de `DeepBeepMeep/TTS` se fijan a la revisión
`864a479cbf3e810e1b2c1993b438510750e383b2`. No se incluyen pesos ni medios en Git.

El motor de tokens y las capas Qwen nuevas viven en `shared/wangp1300`, con
imports propios. Los modelos anteriores conservan sus clases y cachés. Los
handlers usan el cargador/offload y la salida de audio existentes. No se ha
sustituido Torch, Transformers ni MMGP, ni modificado los launchers.
No hay cifras medidas de memoria mínima para estos modelos en HocusPocus;
su catálogo omite la estimación genérica.

## Validación

Las pruebas dirigidas cubren los handlers reales, el registro de comandos,
la conservación de letra/instrucciones, los modos, límites, recetas Flash,
referencias canónicas, controles React y cálculo de un transformer AuK pequeño
en CPU. La suite UI completa pasa 1.832 pruebas y el recorrido de navegador
pasa 46 pruebas con API simulada. La suite Python obtuvo 3.515 pases y dos skips;
el único fallo fue una entrada de inventario arquitectónico pendiente para el
nuevo test del store. Tras añadir esa entrada explícita, las cinco pruebas de
arquitectura y las 22 de audio pasan. No se regeneraron baselines de métricas.

Se ejecutaron tres generaciones con pesos reales fijados a la revisión anterior,
en Linux, RTX 4090, Torch 2.7, Transformers 4.57.1 y MMGP 3.7.6, usando BF16 y
perfil de offload 3. Los pesos y resultados están en el directorio local ignorado
`outputs/yue2-auk-adoption/` del worktree de implementación.

| Prueba real | Resultado |
| --- | --- |
| AuK Flash, instrucción de voz en inglés | WAV mono, 24 kHz, 5 s; RMS 0,0608 |
| AuK Flash, instrucción de limpieza con la muestra anterior como fuente | WAV mono, 24 kHz, 5 s; RMS 0,0565 |
| YuE2, letra/estilo en inglés, melodía y acordes, límite 8 s | WAV estéreo, 48 kHz, 7,999 s; RMS 0,1239 |

Todos los resultados tienen muestras finitas y señal no nula. YuE2 agotó el
límite de tokens de esos ocho segundos: el fragmento no demuestra una canción
completa. Estas pruebas llaman los pipelines directamente; no certifican la
cola HTTP y publicación en galería con esos pesos, fidelidad de palabras,
calidad perceptual, clonación, edición concreta, una mejora audible de limpieza,
AuK Base, duración máxima, español, Windows ni los motores acelerados de YuE2.
Las cargas iniciales estuvieron afectadas por E/S; no se presenta un benchmark
ni una estimación de memoria mínima.

La web móvil de Deepy se ha investigado mediante documentación y código upstream,
sin ejecutarla ni cambiar los servicios de la máquina.
