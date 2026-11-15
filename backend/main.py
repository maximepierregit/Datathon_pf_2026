"""Point d'entrée Bedrock AgentCore Runtime (déploiement par code: le fichier doit s'appeler main.py).

Le runtime appelle `invoke` avec le JSON envoyé par le client. Comme la fonction est un générateur
asynchrone, chaque `yield` est relayé au client comme un événement SSE (text/event-stream).

Charges utiles (voir workflow/flow.py):
    {"mode": "monport_check", "profile": {...}, "constraints": {...}}
    {"mode": "monport", "profile": {...}, "constraints": {...}, "check": {...}, "adjustment": "...", "session": id}
    {"mode": "monport_chat", "session": id, "message": "texte libre"}
"""

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bedrock_agentcore import BedrockAgentCoreApp  # noqa: E402

from invest_agents.workflow.flow import stream_chat, stream_check, stream_monport  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = BedrockAgentCoreApp()

# MonPort, mené par Pépite: vérification, construction, puis questions du client.
STREAMS = {"monport_check": stream_check, "monport": stream_monport, "monport_chat": stream_chat}


@app.entrypoint
async def invoke(payload: dict):
    if not isinstance(payload, dict):
        yield {"type": "error", "code": "invalid_request", "message": "Le corps de la requête doit être un objet JSON."}
        return
    stream = STREAMS.get(payload.get("mode"))
    if stream is None:
        yield {"type": "error", "code": "invalid_request",
               "message": "Le champ `mode` doit valoir monport_check, monport ou monport_chat."}
        yield {"type": "done"}
        return
    async for event in stream(payload):
        yield event


if __name__ == "__main__":
    app.run(port=int(os.getenv("PORT", "8080")))  # AgentCore exige 8080; PORT sert aux tests locaux
