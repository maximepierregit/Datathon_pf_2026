"""Appels des outils métier, dans le processus ou à travers AgentCore Gateway (MCP signé SigV4).

TOOLS_BACKEND=gateway et GATEWAY_URL=https://<id>.gateway.bedrock-agentcore.<région>.amazonaws.com/mcp envoient les
appels à la Gateway, qui les relaie au serveur MCP `monport_tools` (un second AgentCore Runtime). Sinon, ou si la
Gateway échoue, la fonction de `tool_core` tourne ici même: le parcours du client ne casse jamais à cause d'un outil.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Optional

import httpx

from . import tool_core

logger = logging.getLogger(__name__)

TARGET = "monport-tools"  # nom de la cible dans la Gateway: les outils s'y appellent monport-tools___<outil>
TOOLS = ("describe_universe", "screen_assets", "optimize_portfolio", "check_portfolio_constraints",
         "get_latest_macro_snapshot", "get_macro_history")


class SigV4Auth(httpx.Auth):
    """Signe chaque requête HTTP avec les identifiants AWS du processus (rôle d'exécution du runtime)."""

    requires_request_body = True

    def __init__(self, service: str = "bedrock-agentcore", region: Optional[str] = None) -> None:
        import boto3

        self.service = service
        self.region = region or os.getenv("AWS_REGION") or "us-east-1"
        self.session = boto3.Session()

    def auth_flow(self, request: httpx.Request):
        from botocore.auth import SigV4Auth as BotoSigV4
        from botocore.awsrequest import AWSRequest

        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("connection", "content-length")}
        aws = AWSRequest(method=request.method, url=str(request.url), data=request.content, headers=headers)
        BotoSigV4(self.session.get_credentials().get_frozen_credentials(), self.service, self.region).add_auth(aws)
        for key, value in aws.headers.items():
            request.headers[key] = value
        yield request


def enabled() -> bool:
    return os.getenv("TOOLS_BACKEND", "local").lower() == "gateway" and bool(os.getenv("GATEWAY_URL"))


_client = None
_lock = threading.Lock()


def _mcp():
    """Client MCP partagé par le processus, ouvert au premier appel (thread de fond géré par Strands)."""
    global _client
    with _lock:
        if _client is None:
            from strands.tools.mcp import MCPClient

            client = MCPClient(url=os.environ["GATEWAY_URL"], auth_provider=SigV4Auth(), startup_timeout=60)
            client.start()
            _client = client
        return _client


def _reset() -> None:
    global _client
    with _lock:
        if _client is not None:
            try:
                _client.stop(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        _client = None


def _parse(result: dict) -> dict:
    if result.get("status") == "error":
        raise RuntimeError(" ".join(c.get("text", "") for c in result.get("content", [])) or "erreur de l'outil")
    if isinstance(result.get("structuredContent"), dict):
        data = result["structuredContent"]
        # FastMCP enveloppe un retour dict dans {"result": ...} quand le schéma de sortie n'est pas un objet
        return data["result"] if set(data) == {"result"} and isinstance(data["result"], dict) else data
    text = "".join(c.get("text", "") for c in result.get("content", []))
    return json.loads(text)


def call_remote(name: str, arguments: dict) -> dict:
    """Un appel d'outil à travers la Gateway. Lève en cas d'échec."""
    result = _mcp().call_tool_sync(tool_use_id=f"monport-{name}", name=f"{TARGET}___{name}", arguments=arguments)
    return _parse(result)


def run(name: str, market: Any = None, **arguments: Any) -> dict:
    """Exécute l'outil `name` de `tool_core` (à travers la Gateway si activée, avec repli local)."""
    if name not in TOOLS:
        raise ValueError(name)
    if enabled():
        payload = {k: (v.model_dump(mode="json") if hasattr(v, "model_dump") else v) for k, v in arguments.items()}
        if "constraints" in payload:
            payload["constraints"] = [c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                                      for c in arguments["constraints"]]
        try:
            return call_remote(name, payload)
        except Exception:  # noqa: BLE001
            logger.exception("Outil %s: Gateway en échec, calcul local", name)
            _reset()
    fn = getattr(tool_core, name)
    return fn(**arguments, market=market) if market is not None and "market" in fn.__code__.co_varnames else fn(**arguments)
