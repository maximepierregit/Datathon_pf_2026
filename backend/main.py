"""Point d'entrée Bedrock AgentCore Runtime (déploiement par code: le fichier doit s'appeler main.py).

Le runtime appelle `invoke` avec le JSON envoyé par le client. Comme la fonction est un générateur
asynchrone, chaque `yield` est relayé au client comme un événement SSE (text/event-stream).

Charges utiles:
    {"mode": "pipeline", "profile": {...}, "constraints": {...}}    # contrat du frontend (types.ts)
    {"mode": "adjust", "portfolio": "...", "message": "...", ...}    # chat d'ajustement du frontend
    {"mode": "initial", "form": {...}}                               # contrat interne (scripts/run_local.py)
    {"mode": "refine", "message": "texte libre", "context": {...}}
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402

from invest_agents.orchestrator import stream_pipeline  # noqa: E402
from invest_agents.web_adjust import stream_adjust  # noqa: E402
from invest_agents.web_pipeline import stream_web_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict):
    if not isinstance(payload, dict):
        yield {"type": "error", "code": "invalid_request", "message": "Le corps de la requête doit être un objet JSON."}
        return
    mode = payload.get("mode", "pipeline" if "profile" in payload else "initial")
    stream = {"pipeline": stream_web_pipeline, "adjust": stream_adjust}.get(mode, stream_pipeline)
    async for event in stream(payload):
        yield event


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", "8080")))  # AgentCore exige 8080; PORT sert aux tests locaux
