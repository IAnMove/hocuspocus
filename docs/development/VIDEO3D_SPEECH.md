# Voz y labios en Vídeo 3D

Contrato vigente del editor. Las caras, voces e intervenciones pertenecen al
sujeto seleccionado y se guardan en el documento nativo de la escena.

## Recorrido recomendado

1. Abre **Estudios → Vídeo 3D**, elige el GLB y selecciona ese sujeto.
2. Abre **Voz y lip-sync → Añadir labios**. Solo cambia la cara de este sujeto.
   La estimación inicial puede requerir ajustes; si no reconoce un hueso de
   cabeza, ofrece una posición editable basada en la geometría.
3. Pulsa **Colocar con un clic sobre la cara** y haz clic donde está su boca en
   el visor. La selección se limita a ese sujeto. Escape o Cancelar cierra la
   colocación. El clic también funciona sobre una pose animada: guarda las
   coordenadas originales de la piel, antes de la animación.
4. Ajusta **Anchura/Altura** y, si hace falta, **Boca X/Y/Z**: izquierda/derecha,
   arriba/abajo y profundidad. Mira la cara de frente; el pintado asume que la
   cara apunta hacia +Z en la geometría original. No se reconstruye una boca 3D.
   Los números usan las unidades originales del GLB, que pueden ser grandes.
5. Pulsa **Usar ejemplo en inglés**, después **Reproducir**. La frase incluida es
   “Hello! This is a quick voice test. Watch my lips move as I speak.” Incluye
   audio y gestos precalculados, sin generar otra voz ni necesitar Rhubarb.
6. Para tu propia voz, elige audio local/de HocusPocus o pulsa **Grabar con
   micrófono → Detener grabación → escuchar → Usar grabación para este sujeto**.
   Descartar no cambia la voz del personaje. Cancelar, cerrar el panel o cambiar
   de sujeto libera el micrófono, también si el permiso llega tarde.
7. Una grabación o audio nuevo empieza con movimiento aproximado por volumen.
   **Calcular gestos con Rhubarb (local)** añade análisis fonético si está
   instalado. La vista previa de audio permite escuchar antes de reproducir la
   escena. La grabación se limita a 90 segundos y requiere HTTPS o localhost;
   en HTTP de red local siguen disponibles el ejemplo y la subida de archivos.
8. Configura el inicio y recorte del audio. **Ajustar duración a las voces**
   permite incluir su final. Para varias intervenciones de un sujeto, despliega
   su sección de intervenciones; para otra voz, selecciona el otro sujeto.
9. **Guardar ajuste para este modelo** conserva la calibración por hash del GLB.
   **Guardar plano JSON** conserva toda la escena. **Exportar MP4** incluye las
   voces y los efectos de sonido.

Las referencias Mira/Seren/Grog/Zik están en **Referencias de colocación
avanzadas**. Aplican coordenadas al sujeto actual: revisar siempre el encaje.
La biblioteca de personajes y voces preferidas está en otro apartado avanzado;
**Usar personaje** sí sustituye el modelo, por elección explícita. Importar un
kit de Taberna también sustituye el GLB y carga su voz, atlas y calibración.

Añadir labios mantiene desactivados los ojos adicionales y la cobertura de la
boca original. Se pueden activar en los ajustes. Las barbas, hocicos, materiales
con varios submateriales o caras que miran hacia otro eje requieren revisión.
El pintado soporta una malla con un material MeshStandardMaterial o derivado;
no requiere un rig, UV ni blendshapes para la colocación manual. La estimación
por huesos usa Head/mixamorigHead, UV y una orientación humanoide convencional.

## Modelo de datos y conservación

`Scene3DSlot.speech` es opcional y versionado. `FacePlacement` contiene índice de
malla, centro, tamaño, piel y ojos en coordenadas originales anteriores al
skinning. El shader pinta sobre el material; no modifica el archivo GLB ni crea
morph targets. El tamaño de la zona frontal sigue las dimensiones de la boca,
para admitir modelos en metros y centímetros.

Audio y atlas usan `Scene3DSourceRef`. Los gestos viven en el reloj del audio:
`tiempo de escena - inicio + recorte`. Hasta 32 intervenciones por personaje;
se rechazan solapamientos. Una canción común se conserva en la pista de escena
y puede guiar una boca silenciada para evitar duplicar el sonido. Para canciones,
las voces aisladas suelen dar una guía más útil que la mezcla instrumental.

Cambiar GLB mediante el selector borra su calibración. Las escenas guardan
snapshots independientes. Los perfiles guardados se identifican por el contenido
del GLB; hay que cargar un perfil existente antes de sobrescribirlo. Un JSON
solo referencia medios: no los empaqueta para otro ordenador.

## Rhubarb y exportación

Instala [Rhubarb Lip Sync](https://github.com/DanielSWolf/rhubarb-lip-sync) con sus
recursos y licencia. Configura `RHUBARB_EXECUTABLE` con la ruta absoluta al
binario, o añádelo a PATH, y reinicia HocusPocus. No hay descargas automáticas.
Sin él se puede usar el ejemplo, importar gestos o trabajar por volumen.

`POST /api/v1/character-kits/speech/analyze` recibe WAV PCM mono, 16 kHz/16 bits,
hasta 90 s / 3 MB. Un proceso, dos hilos y timeout de 90 s. No acepta rutas ni
URLs externas. El editor convierte el audio antes de enviarlo. Una voz existente
puede durar hasta 600 s / 32 MB; se analizan fragmentos de hasta 90 s.

La separación vocal y Rhubarb reutilizan una caché por contenido del audio,
versión de herramienta, parámetros y ventana analizada. Las solicitudes
simultáneas comparten el trabajo; ventanas distintas mantienen resultados
independientes. La mezcla final conserva la banda sonora original.
La caché usa `cache/speech-analysis/` o `SPEECH_ANALYSIS_CACHE_DIR`, con límites
configurables `SPEECH_ANALYSIS_CACHE_MAX_BYTES` (128 MiB) y
`SPEECH_ANALYSIS_CACHE_MAX_ENTRIES` (64). Los fallos no publican entradas
parciales. La separación opcional requiere sus modelos ya instalados: estas
operaciones no descargan modelos para completar el análisis.

Exportación con voces: hasta 180 segundos de salida, 1280×720, mezcla mono a
48 kHz. La velocidad se aplica una sola vez, también al tono. El documento se
congela durante la exportación. Si el navegador no codifica AAC, envía PCM junto
al vídeo y el servidor finaliza con FFmpeg. La descarga recupera el MP4 audible;
un fallo de finalización se informa como error.

## Wizard y MCP

`scenes.speech.prepare` recibe la escena, el slot exacto y un audio existente;
calcula los gestos y devuelve un documento preparado sin guardar ni exportar.
Puede reutilizar la calibración guardada en el JSON. El Wizard usa el mismo
comando a través de `prepare_programmatic_video.scene_command`. Ver el contrato
[SFX, operaciones compartidas y MCP](SCENE_EFFECTS_AND_MCP.md).

Grabar y colocar mediante clic son acciones del navegador. MCP puede preparar
la voz sin una pestaña, pero este circuito de exportación utiliza el editor.

## Evidencia y recursos

La frase incluida se generó localmente con KugelAudio 0 Open 7B. Su texto,
modelo, semilla, formato y hash están en
[PROVENANCE.md](../../ui/public/speech-examples/PROVENANCE.md).
Los tests comprueban colocación sin rig, coordenadas antes del skinning,
liberación del micrófono, aislamiento entre sujetos, ejemplo y exportación.
Los dispositivos de los tests E2E son señales simuladas; MediaRecorder,
conversión WAV y WebGL son reales. Las demostraciones de aceptación con GLB y
Rhubarb reales se conservan en outputs, fuera de Git.
