# PITCH.md

> Documento para presentar y defender el proyecto ante los jueces.
> Se actualiza al final de cada paso con los conceptos nuevos.

## El problema y la solución en 30 segundos
*(Se completa al final de la Fase 2, cuando la demo de RAG funcione.)*

Borrador: un asistente personal de IA **privado** que conoce tus notas y documentos, recuerda lo que le cuentas y puede ejecutar pequeños programas por ti, pero **siempre pidiendo permiso**. Tus datos se guardan en tu propia máquina; solo la inferencia se hace en Nebius con modelos abiertos de NVIDIA.

## Cómo cumplimos los requisitos del hackathon
| Requisito | Cómo lo cumplimos | Dónde está en el código |
|---|---|---|
| Inferencia en Nebius Token Factory | Todas las llamadas de chat y embeddings van a la API de Nebius (compatible con OpenAI) | `src/assistant/config.py`, `scripts/verify_models.py` |
| Al menos un modelo open source de NVIDIA | **Nemotron 3 Super 120B** genera todas las respuestas y decisiones del agente. Para los embeddings usamos Qwen3-Embedding-8B, también en Nebius; las reglas lo permiten porque piden *al menos un* modelo NVIDIA. | `.env` → `LLM_MODEL`, `EMBED_MODEL` |
| Privacidad y control de datos | Qdrant corre en un contenedor en tu máquina, con un volumen local. Los puertos solo escuchan en `127.0.0.1`, así que nadie en tu red puede acceder. *(Fase 2: aquí se guardarán tus documentos y recuerdos.)* | `docker-compose.yml` |
| Sandbox de ejecución | *(Fase 3: contenedor Docker aislado)* | — |

**¿Por qué es una app de terminal y no una web?**
Porque la privacidad es el centro del proyecto: tus documentos y tu memoria se quedan en tu máquina. Una web pública significaría subir tus datos a un servidor. Además, la terminal permite mostrar claramente el flujo de aprobación antes de ejecutar código.

## Arquitectura explicada (sin jerga)
*(Se completa en la Fase 3.)*

## Guion de la demo (paso a paso, con comandos)
*(Se completa en la Fase 4.)*

## Preguntas probables de los jueces y respuestas

**¿Por qué no hay ninguna API key en el código?**
Todas las credenciales se leen del archivo `.env`, que Git ignora (está en `.gitignore`). En el código la key es un `SecretStr`, así que no aparece en logs ni en mensajes de error. El repositorio incluye `.env.example` con los nombres de las variables, pero sin valores.

**¿Cómo sabéis que los modelos que usáis existen y funcionan?**
Antes de escribir la lógica, ejecutamos `scripts/verify_models.py`. Pide a Nebius la lista real de modelos (`GET /v1/models`), comprueba que los nuestros están, hace una llamada de prueba al chat y otra a los embeddings, y verifica la dimensión del vector.

**¿Por qué usáis embeddings de Qwen y no de NVIDIA?**
Nebius Token Factory no ofrece ningún modelo de embeddings de NVIDIA; el único disponible es `Qwen/Qwen3-Embedding-8B`. Lo comprobamos con la lista real del catálogo. Las reglas piden *al menos un* modelo open source de NVIDIA, y Nemotron lo cumple. Así mantenemos el 100% de la inferencia en Nebius. Todo el razonamiento y las respuestas los genera **Nemotron 3 Super** de NVIDIA; Qwen solo convierte texto en vectores para buscar. Cambiar de modelo de embeddings es una línea en `.env` más reindexar.

**¿Por qué Nemotron 3 Super 120B y no el Ultra o el Nano?**
Probamos los cuatro con tool calling y todos funcionaron. Super ofrece el mejor equilibrio entre calidad y velocidad (~2 s). Ultra es más grande y caro, y Nano razona peor. Nano queda como respaldo si hay límites de uso.

**¿Qué pasa si Nebius falla o tarda?**
Cada llamada tiene un tiempo máximo (*timeout*). Los errores temporales, como el 429 (demasiadas peticiones), los errores 5xx y los cortes de red, se reintentan hasta 4 veces, esperando cada vez más (*backoff* exponencial). Los errores de nuestra parte (4xx, por ejemplo una petición mal formada) no se reintentan, porque repetirlos no sirve. Todo está probado con tests que simulan la API.

**¿Cómo sabéis que funciona sin gastar créditos en cada test?**
Hay dos tipos de pruebas. Las **unitarias** simulan la API de Nebius (con `respx`) y comprueban reintentos, errores y lotes sin hacer ninguna llamada real; tardan menos de 1 segundo. Las **live** (`pytest -m live`) llaman a Nebius de verdad y se ejecutan solo cuando queremos.

**¿Cómo evitáis subir una API key a GitHub por error?**
Además de `.gitignore`, cada `git commit` pasa por **gitleaks**, un escáner de secretos. Lo probamos con una key falsa y bloqueó el commit. La imagen Docker tampoco contiene el `.env`: la key se pasa solo al arrancar el contenedor.

**¿Cómo reproduce otra persona vuestro entorno?**
Con `uv sync`. El archivo `uv.lock` fija las versiones exactas de todas las dependencias, y `.python-version` fija Python 3.12.

## Glosario de IA
| Término | Definición simple | Dónde está en el código |
|---|---|---|
| **LLM** (Large Language Model) | Modelo que genera texto prediciendo la siguiente palabra. Es el "cerebro" del asistente. Usamos Nemotron de NVIDIA. | `.env` → `LLM_MODEL` |
| **Inferencia** | Usar un modelo ya entrenado para obtener una respuesta. Nosotros no entrenamos: solo hacemos inferencia en Nebius. | `scripts/verify_models.py` |
| **API compatible con OpenAI** | Nebius usa el mismo formato de peticiones que OpenAI, así que usamos el SDK `openai` cambiando solo la URL base. Es como cambiar de proveedor REST sin cambiar el cliente. | `config.py` → `nebius_base_url` |
| **Embedding** | Convierte un texto en una lista de números (vector) que representa su significado. Textos con significado parecido dan vectores cercanos. | `.env` → `EMBED_MODEL` |
| **Dimensión del embedding** | La longitud de ese vector (por ejemplo, 4096 números). La base de datos de vectores necesita saberla de antemano. | `.env` → `EMBED_DIM` |
| **Modelo de razonamiento** | Modelo que "piensa" internamente (genera tokens de razonamiento ocultos) antes de dar la respuesta. Nemotron 3 lo es. Esos tokens cuentan en el límite `max_tokens`, y el razonamiento se puede apagar en tareas simples para ir más rápido. | `scripts/verify_models.py` → `enable_thinking` |
| **Tool calling** | El modelo no ejecuta nada: devuelve un JSON diciendo "quiero llamar a la función X con estos argumentos". Nuestro código decide si ejecutarla. | *(Fase 3)* `src/assistant/tools/` |
| **Streaming** | En lugar de esperar la respuesta completa, el modelo la envía token a token y la mostramos mientras llega (como ChatGPT). Es la misma idea que una respuesta HTTP por chunks. | `src/assistant/llm/chat.py` → `stream()` |
| **Batching (lotes)** | Enviar varios textos en una sola petición de embeddings en lugar de uno por uno. Es más rápido y gasta menos peticiones. | `src/assistant/llm/embeddings.py` |
| **Token** | El trozo de texto con el que trabaja el modelo (aprox. ¾ de una palabra). Los límites y costes se miden en tokens. | `.env` → `MAX_COMPLETION_TOKENS` |

## Cómo comprobarlo tú mismo (estado actual)
```
uv run pytest -q                     # 8 pruebas unitarias, API simulada (< 1 s)
uv run pytest -q -m live             # 2 pruebas reales contra Nebius
docker compose up -d                 # arranca la API y Qdrant
curl http://127.0.0.1:8000/health    # debe decir "nebius":"ok" y "qdrant":"ok"
```
También puedes abrir http://127.0.0.1:8000/docs en el navegador: FastAPI genera la documentación de la API automáticamente (Swagger).

## Limitaciones honestas y trabajo futuro
- La inferencia no es local: el texto que se envía al modelo sale de la máquina hacia Nebius. Lo que es local es el **almacenamiento** (documentos, vectores, memoria).
