"""Verify the Nebius Token Factory model catalog.

Lists the models available to this API key, checks that LLM_MODEL and EMBED_MODEL
exist, runs one tiny chat call and one embedding call, and checks EMBED_DIM.
User-facing output is in Spanish (see AGENTS.md §6).

Usage: uv run python scripts/verify_models.py
"""

import sys

from openai import APIConnectionError, AuthenticationError, OpenAI

from assistant.config import get_settings


def main() -> int:
    settings = get_settings()
    client = OpenAI(
        base_url=settings.nebius_base_url,
        api_key=settings.nebius_api_key.get_secret_value(),
        timeout=30,
    )

    try:
        model_ids = sorted(m.id for m in client.models.list())
    except AuthenticationError:
        print("✘ La API key fue rechazada. Revisa NEBIUS_API_KEY en tu archivo .env.")
        return 1
    except APIConnectionError:
        print(f"✘ No se pudo conectar a {settings.nebius_base_url}. Revisa NEBIUS_BASE_URL.")
        return 1

    nvidia = [m for m in model_ids if "nvidia" in m.lower() or "nemotron" in m.lower()]
    print(f"✔ Conectado a Nebius. Modelos disponibles: {len(model_ids)}")
    print("\nModelos NVIDIA / Nemotron en el catálogo:")
    for m in nvidia:
        print(f"  - {m}")

    ok = True
    for label, model in (("LLM_MODEL", settings.llm_model), ("EMBED_MODEL", settings.embed_model)):
        if model in model_ids:
            print(f"\n✔ {label} = {model} existe en el catálogo.")
        else:
            print(f"\n✘ {label} = {model} NO está en el catálogo. Elige uno de la lista.")
            ok = False
    if not ok:
        return 1

    # Smoke test: one short chat completion. Nemotron 3 models "think" before answering;
    # reasoning tokens count against max_tokens, so we disable thinking for this check.
    chat = client.chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "user", "content": "Responde solo con: hola"}],
        max_tokens=50,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    answer = (chat.choices[0].message.content or "").strip()
    if not answer:
        print("✘ El chat respondió vacío. Revisa LLM_MODEL y max_tokens.")
        return 1
    print(f"✔ Chat responde: {answer!r}")

    # Smoke test: one embedding, and check its dimension against EMBED_DIM.
    emb = client.embeddings.create(model=settings.embed_model, input=["ping"])
    dim = len(emb.data[0].embedding)
    if dim == settings.embed_dim:
        print(f"✔ Embeddings responden. Dimensión = {dim} (coincide con EMBED_DIM).")
    else:
        print(f"✘ Dimensión real = {dim}, pero EMBED_DIM = {settings.embed_dim}. Corrige .env.")
        return 1

    print("\n🎉 Todo listo: Nebius y los modelos NVIDIA funcionan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
