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
| Modelos open source de NVIDIA | Modelos Nemotron (chat) y NV-Embed o equivalente (embeddings), verificados contra el catálogo real | `.env` → `LLM_MODEL`, `EMBED_MODEL` |
| Privacidad y control de datos | *(Fase 2: Qdrant local)* | — |
| Sandbox de ejecución | *(Fase 3: contenedor Docker aislado)* | — |

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
Nebius Token Factory no ofrece ningún modelo de embeddings de NVIDIA; el único disponible es `Qwen/Qwen3-Embedding-8B`. Lo comprobamos con la lista real del catálogo. Así mantenemos el 100% de la inferencia en Nebius. Todo el razonamiento y las respuestas los genera **Nemotron 3 Super** de NVIDIA; Qwen solo convierte texto en vectores para buscar. Cambiar de modelo de embeddings es una línea en `.env` más reindexar.

**¿Por qué Nemotron 3 Super 120B y no el Ultra o el Nano?**
Probamos los cuatro con tool calling y todos funcionaron. Super ofrece el mejor equilibrio entre calidad y velocidad (~2 s). Ultra es más grande y caro, y Nano razona peor. Nano queda como respaldo si hay límites de uso.

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
| **Token** | El trozo de texto con el que trabaja el modelo (aprox. ¾ de una palabra). Los límites y costes se miden en tokens. | `.env` → `MAX_COMPLETION_TOKENS` |

## Limitaciones honestas y trabajo futuro
- La inferencia no es local: el texto que se envía al modelo sale de la máquina hacia Nebius. Lo que es local es el **almacenamiento** (documentos, vectores, memoria).
