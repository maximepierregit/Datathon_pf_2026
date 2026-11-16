"""Test de fumée du runtime AgentCore déployé: vérification, construction puis question à Pépite, dans une même session.

    python scripts/smoke_runtime.py                       # ARN lu dans deploy/state/agents-runtime-arn
    python scripts/smoke_runtime.py --check-only
    python scripts/smoke_runtime.py --url https://xxx.lambda-url.us-east-1.on.aws/   # passe par le proxy Lambda

Sortie non nulle si un mode n'aboutit pas (pas d'événement attendu, ou événement `error`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_local import SAMPLE_CONSTRAINTS, SAMPLE_PROFILE, show  # noqa: E402

STATE = Path(__file__).resolve().parents[2] / "deploy" / "state"


def sse_events(lines):
    """Événements JSON d'un flux text/event-stream (itérable de lignes en bytes)."""
    data: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
        elif not line and data:
            yield json.loads("\n".join(data))
            data = []
    if data:
        yield json.loads("\n".join(data))


def invoke_runtime(arn: str, session: str, payload: dict):
    client = boto3.client("bedrock-agentcore", region_name=arn.split(":")[3])
    resp = client.invoke_agent_runtime(agentRuntimeArn=arn, runtimeSessionId=session, payload=json.dumps(payload),
                                       contentType="application/json", accept="text/event-stream")
    yield from sse_events(resp["response"].iter_lines(keepends=True))


def invoke_url(url: str, session: str, payload: dict):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Session-Id": session})
    with urllib.request.urlopen(req, timeout=900) as resp:
        yield from sse_events(resp)


def run(events, t0: float) -> dict:
    seen: dict = {}
    for e in events:
        show(e, False, t0)
        seen.setdefault(e.get("type"), e)
        if e.get("type") in ("check", "portfolios"):
            seen[e["type"]] = e
        if e.get("session"):
            seen["session"] = e["session"]
    return seen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arn", default=(STATE / "agents-runtime-arn").read_text().strip()
                        if (STATE / "agents-runtime-arn").exists() else None)
    parser.add_argument("--url", help="Function URL du proxy (sinon appel direct au runtime)")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--restore", action="store_true",
                        help="Chat sous un autre runtimeSessionId: microVM neuve, session restaurée par AgentCore Memory")
    parser.add_argument("--chat", default="Pourquoi ce portefeuille me convient-il? Réponds en deux phrases.")
    args = parser.parse_args()

    session = uuid.uuid4().hex + uuid.uuid4().hex  # AgentCore exige au moins 33 caractères
    call = (lambda p: invoke_url(args.url, session, p)) if args.url else (lambda p: invoke_runtime(args.arn, session, p))
    print(f"session {session} via {'proxy ' + args.url if args.url else args.arn}")
    t0 = time.time()
    base = {"profile": SAMPLE_PROFILE, "constraints": SAMPLE_CONSTRAINTS}

    seen = run(call({"mode": "monport_check", **base}), t0)
    if "check" not in seen or "error" in seen:
        print("ÉCHEC: pas de vérification")
        return 1
    if args.check_only:
        return 0
    built = run(call({"mode": "monport", **base, "check": seen["check"]["check"], "session": seen.get("session")}), t0)
    if "portfolios" not in built:
        print("ÉCHEC: pas de portefeuilles")
        return 1
    if args.restore:
        session = uuid.uuid4().hex + uuid.uuid4().hex
        print(f"chat sur une nouvelle microVM (session {session})")
    chat = run(call({"mode": "monport_chat", "session": built.get("session") or seen.get("session"),
                     "message": args.chat}), t0)
    if "error" in chat or "pepite" not in chat:
        print("ÉCHEC: le chat n'a pas retrouvé la session")
        return 1
    print(f"OK en {time.time() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
