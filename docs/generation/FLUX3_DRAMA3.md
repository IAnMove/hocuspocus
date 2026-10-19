# FLUX 3 Image Klein y Drama 3

Guía de generación local. Los dos modelos aparecen en el catálogo y usan la cola
de generación de HocusPocus, con tareas, cancelación, archivos y metadatos en el
workspace. La instalación opcional mantiene sus dependencias separadas de WanGP
y MiniMax H3.

## Instalar

1. En Pinokio abre **Advanced → Install FLUX 3 / Drama 3 Support**.
2. Para FLUX, acepta el acceso en el [repositorio de pesos de BFL](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy).
   Configura `HF_TOKEN` en el entorno de **esta aplicación** en Pinokio. El token
   debe pertenecer a la cuenta que obtuvo el acceso; aceptar con otra cuenta no
   autoriza las descargas. Reinicia HocusPocus si cambias su entorno.
3. En **Settings → Models**, descarga y activa el modelo para que aparezca en el
   selector de Studio. Las variantes
   de una misma familia comparten pesos; borrarlos afecta a ambas variantes.

El motor opcional soporta NVIDIA CUDA en Linux y Windows. Usa Python 3.11,
PyTorch 2.10 y ComfyUI 0.41 en un entorno propio. El instalador fija las revisiones
en `app/runtime/vendors.json`, los paquetes en los locks de `app/runtime/locks/`
y los pesos en `app/services/creation_model_catalog.py`. No hay que actualizar
manualmente el entorno principal ni instalar un segundo Studio.

| Modelo en el catálogo | ID | Uso |
| --- | --- | --- |
| FLUX 3 Image Klein — INT8 | `flux3_klein` | Crear una imagen a partir de texto |
| FLUX 3 Image Klein Edit — INT8 | `flux3_klein_edit` | Editar con una imagen y referencias adicionales |
| TTS Drama 3 — Voice Generation | `drama3_voicedesign` | Crear una voz desde texto y dirección opcional |
| TTS Drama 3 — Voice Clone | `drama3_base` | Usar una grabación de referencia y su transcripción |

FLUX descarga aproximadamente **11 GB** entre transformer INT8, encoder Qwen3-VL
INT8 y VAE. Drama descarga **40,3 GB decimales**, incluidos los expertos INT8 y
el codec. La caché de Hugging Face puede necesitar espacio adicional si no se
pueden crear enlaces físicos. Los pesos se guardan en `app/ckpts/creation_models/`.

## FLUX: crear y editar imágenes

En **Direct generation → Image**, selecciona FLUX 3 Klein para crear o su variante
Edit para editar. El punto de partida es **16 steps, Euler, scheduler simple y
CFG 1**. También se ofrece ER-SDE. Las dimensiones deben ser múltiplos de 16;
empieza con 1024×1024 o 1280×720. Los steps admitidos son 4–50; menos pasos no
garantizan conservar la calidad.

Edit acepta **hasta diez imágenes en total**, contando la imagen principal.
Por ejemplo, una vista frontal como principal y espalda, izquierda y derecha
como tres referencias. Describe la función de cada una y el resultado deseado:
«El mismo personaje de las imágenes 1–4, ahora sentado, conserva ropa y colores».
Cada referencia se codifica por separado y se ajusta a aproximadamente un
megapíxel; no se convierte en un collage.

Esto ayuda a generar poses y vistas coherentes, pero sigue siendo generación
de imágenes: no reconstruye automáticamente un modelo 3D ni garantiza identidad
perfecta. Diez referencias o un lienzo 4K consumen más memoria; no se promete
que cualquier combinación quepa en 24 GB. Esta primera integración no incorpora
LoRAs adicionales, máscaras, outpainting ni controles gráficos de bounding boxes.

Se integra el modelo **distilled** INT8. El modelo Base para entrenamiento o
fine-tuning no forma parte de este instalador. Fuentes:
[código de BFL](https://github.com/black-forest-labs/flux-3-image-klein),
[pesos para ComfyUI](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy),
[workflow oficial de edición](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux3_klein_distilled_image_edit.json).

## Drama: inglés, español y grabaciones de referencia

Selecciona Drama 3 en la generación de **Speech**. En Voice Generation escribe
lo que debe decir y, si quieres, una dirección como «voz adulta cálida, pausada».
Puedes terminar el texto con `[language: en]` o `[language: es]` para orientar
el idioma. Las etiquetas expresivas se escriben en el punto deseado, por ejemplo
`[sighs]` o `[laughs]`; comprueba cada toma porque el resultado es estocástico.

Para **Voice Clone**, selecciona una grabación limpia mediante el campo de
referencia y copia sus palabras exactas en **Exact reference transcript**.
En el prompt va el texto nuevo. El archivo puede proceder de una grabación o
de una voz sintética que hayas generado. La fidelidad de la voz requiere escuchar
y comparar las tomas; una transcripción correcta solo comprueba las palabras.

Valores iniciales: **temperature 1, top-p 0.9, top-k 30**. El límite de segundos
es un máximo por bloque de texto, no una orden para alargar la locución. Los
textos largos se dividen automáticamente. El resultado se guarda en FLAC a
44,1 kHz, con su tarea y metadatos. Algunas tomas pueden acabar antes de
completar el texto, incluso con INT8: verifica la transcripción y prueba otra
semilla o una referencia distinta antes de aprobarlas.

Los expertos INT8 permanecen en RAM y se cachean parcialmente en GPU. La guía del
integrador indica unos **48 GB de RAM** para INT8; es razonable partir de un
equipo con **64 GB**. El control **Expert GPU cache** admite 0 (automático) o
0–16 GB; las pruebas de esta integración usan 12 GB en una RTX 4090.
La carga inicial puede tardar minutos: no se ofrece una garantía de tiempo real.
Se elige INT8 frente a W4A8 por la advertencia del integrador sobre tomas silenciosas
en W4A8.

El modelo original admite varias voces y edición con historial. Esta primera
superficie de HocusPocus genera una voz por tarea y clona una referencia; no
expone un editor de 16 speakers, infilling ni revisión multi-turn. La transcripción
de QA usa el servicio Whisper de HocusPocus; Qwen3-ASR no se descarga con Drama.
Fuentes: [modelo oficial](https://huggingface.co/fishaudio/drama-3),
[código Fish Speech](https://github.com/fishaudio/fish-speech),
[nodos de PedroMarinhoDev](https://github.com/PedroMarinhoDev/ComfyUI-Drama3),
[pesos optimizados](https://huggingface.co/PedroMarinhoDev/Drama-3-ComfyUI).
Consulta las licencias originales antes de distribuir los pesos o usar los
resultados comercialmente; el acceso a Hugging Face no sustituye sus condiciones.

## API y comprobación

Ambos motores usan `POST /api/v1/generation/commands`. Para voz y edición se usa
version 2. Ejemplo de voz sin referencia:

```json
{
  "version": 2,
  "operation": "generation.speech",
  "intent_id": "mi-drama-es-1",
  "input": {
    "workspace": "mi-proyecto",
    "params": {
      "model_type": "drama3_voicedesign",
      "resolution": "1024x1024",
      "prompt": "Hola. Vamos a contar una historia. [language: es]",
      "alt_prompt": "Una voz adulta cálida y clara.",
      "seed": 42,
      "duration_seconds": 30,
      "temperature": 1.0,
      "top_p": 0.9,
      "top_k": 30
    }
  }
}
```

Para editar, usa `operation:"generation.image"`, `model_type:"flux3_klein_edit"`,
`image_guide` con una URL durable del workspace y `video_prompt_type:"V"`.
Si añades `image_refs:[...]`, usa `"VI"`. Para clonar, usa `drama3_base`,
`audio_guide`, `audio_prompt_type:"A"` y `alt_prompt` con las palabras de referencia.

La respuesta inicial admite una tarea; el archivo está listo cuando
`GET /api/v1/tasks/{task_id}?workspace=...` indique `completed` y tenga `result_refs`.
El cliente [creation_job.py](../../pinokio_agent/skills/api/hocuspocus/clients/creation_job.py)
guarda comando, recibo y tarea terminal. Puede reanudarse con el mismo comando.
`POST /api/v1/qa/speech` recibe `{workspace,file,text,language,names}` y devuelve
transcripción, WER, duración y silencios. Separa la evaluación del contenido
de la evaluación perceptiva de la voz.

## Settings de la comunidad

La [validación local](FLUX3_DRAMA3_VALIDATION.md) recoge las primeras imágenes,
pruebas EN/ES, clonaciones, tiempos y fallos encontrados en una RTX 4090.

Anota aquí combinaciones probadas de resolución, referencias, steps, sampler,
caché de expertos, temperatura y duración, junto con GPU/RAM, seed, tiempos y
ejemplos. Mantén separados los datos medidos de las recomendaciones del autor.
