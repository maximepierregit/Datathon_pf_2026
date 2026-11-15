"""Point d'entrée Bedrock AgentCore Runtime (déploiement par code: le fichier doit s'appeler main.py).

Le runtime appelle `invoke` avec le JSON envoyé par le client. Comme la fonction est un générateur
asynchrone, chaque `yield` est relayé au client comme un événement SSE (text/event-stream).

Charges utiles:
    {"mode": "initial", "form": {...}}
    {"mode": "refine", "message": "texte libre", "context": {...}}     # `context` vient du dernier `result`
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402

from invest_agents.monport import stream_monport  # noqa: E402
from invest_agents.orchestrator import stream_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict):
    if not isinstance(payload, dict):
        yield {"type": "error", "code": "invalid_request", "message": "Le corps de la requête doit être un objet JSON."}
        return
    # « monport »: le frontend MonPort envoie son profil et attend ses propres événements (voir monport.py).
    stream = stream_monport(payload) if payload.get("mode") == "monport" else stream_pipeline(payload)
    async for event in stream:
        yield event


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", "8080")))  # AgentCore exige 8080; PORT sert aux tests locaux
