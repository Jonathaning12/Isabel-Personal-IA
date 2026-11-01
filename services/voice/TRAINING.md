# Entrenar la palabra «Isabel» (openWakeWord)

Isabel trae dos detectores de su nombre:

| Detector | Cómo funciona | Precisión |
|---|---|---|
| **Básico (Vosk)** | Reconocedor de voz general con una gramática de dos palabras: «isabel» o «desconocido». | Correcta, con algunas falsas alarmas. Viene listo. |
| **Entrenado (openWakeWord)** | Un modelo pequeño entrenado **solo** para reconocer «Isabel», sobre las características de voz de Google que usa openWakeWord. | Mucho más preciso. Necesitas entrenarlo una vez. |

La app usa el entrenado automáticamente en cuanto existe el archivo `data/wakeword/isabel.onnx`.
En Ajustes → Voz verás cuál está activo.

## Por qué no se entrena en tu PC

El entrenamiento genera miles de grabaciones sintéticas de «Isabel» con voces de computadora y
las mezcla con varios GB de ruido de fondo. En un procesador de laptop eso tarda muchas horas.
En **Google Colab** (gratis, con GPU) tarda **menos de una hora** y no ocupa tu computadora.

## Pasos

1. Abre el cuaderno oficial de openWakeWord en Colab (enlace en su README, «Training New Models»):
   <https://colab.research.google.com/drive/1q1oe2zOyZp7UsB3jJiQ1IFn8z5YfjwEb>
2. Inicia sesión con tu cuenta de Google. En **Entorno de ejecución → Cambiar tipo de entorno**,
   elige **GPU** (T4, gratis).
3. En el campo de la palabra o frase objetivo escribe `isabel`.
   - Las voces sintéticas del cuaderno son en inglés. Si al escuchar los ejemplos que genera no
     suena como lo dices tú, prueba con grafías que fuercen la pronunciación española, como
     `isa bel` o `eesabel`. Elige la que suene más parecida.
4. Ejecuta todas las celdas en orden (**Entorno de ejecución → Ejecutar todas**). Al final el
   cuaderno descarga un archivo `.onnx` (también puede generar `.tflite`, que no se usa).
5. Renómbralo a `isabel.onnx` y cópialo a la carpeta del proyecto:
   `data/wakeword/isabel.onnx`. La carpeta `data/` nunca se sube a git.
6. Reinicia el servicio de voz y la app:

   ```bash
   docker compose restart voice
   ```

   Después cierra Isabel desde el icono de la bandeja → Salir, y ábrela de nuevo.
7. En Ajustes → Voz debería decir «Detector de «Isabel»: modelo entrenado (openWakeWord)».

## Ajustes finos

- **Se activa sola a veces:** sube el umbral en `.env`, por ejemplo `WAKEWORD_THRESHOLD=0.6`, y
  reinicia el servicio. El valor por defecto es 0.5.
- **No te oye a la primera:** bájalo, por ejemplo a `0.4`.
- Detrás del detector sigue el segundo filtro: si la transcripción no contiene «Isabel», se
  ignora. Una falsa alarma ocasional del modelo no llega al agente.

## Privacidad

Con el detector entrenado, mientras Isabel espera su nombre el audio del micrófono viaja de la app
al servicio de voz **en tu misma PC** (`127.0.0.1:8100`). No se guarda y no sale de la máquina.

## Licencias

openWakeWord (código y modelos de características) es Apache-2.0. El modelo que entrenas es tuyo.
