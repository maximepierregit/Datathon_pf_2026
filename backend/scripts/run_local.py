"""Exécute le parcours MonPort en local, dans le processus (appelle Bedrock pour de vrai), et affiche les événements.

    python scripts/run_local.py                                  # vérification puis construction
    python scripts/run_local.py --chat "Pourquoi autant d'obligations?"   # puis une question à Pépite
    python scripts/run_local.py --check-only                     # vérification seulement
    python scripts/run_local.py --raw                            # événements en JSON brut
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invest_agents.workflow.flow import stream_chat, stream_check, stream_monport  # noqa: E402

# Même forme que `Profile` et `Constraints` de frontend/src/types.ts
SAMPLE_PROFILE = {"age": 35, "amount": 10000, "objective": "fructifier", "horizon": 12, "lossReaction": 2, "comfort": 3}
SAMPLE_CONSTRAINTS = {"vehicles": "tous", "classes": {}, "regions": {}, "themes": {}, "factors": {}}
LAST_RESULT = ROOT / "data" / "last_result.json"


def show(event: dict, raw: bool, t0: float) -> None:
    if raw:
        print(json.dumps(event, ensure_ascii=False, default=str))
        return
    t = f"[{time.time() - t0:5.1f}s]"
    kind = event.get("type")
    if kind == "agent_status":
        print(f"{t} ▶ {event['agent']} ({event['status']}): {event.get('message', '')}")
    elif kind == "pepite":
        print(f"{t} 🐾 Pépite: {event['text'][:300]}")
    elif kind == "check":
        c = event["check"]
        print(f"{t} 🔎 Vérification: cohérent={c.get('coherent')} | {c.get('summary')}")
    elif kind == "portfolios":
        for pid, p in event["portfolios"].items():
            m = p.get("metrics") or {}
            print(f"{t} ✅ {pid} « {p.get('name')} »: rend. {m.get('expectedReturn')} | vol {m.get('volatility')} | "
                  f"{len(p.get('holdings') or [])} positions")
    elif kind in ("warning", "error"):
        print(f"{t} ⚠ {kind}: {event.get('message') or event}")
    elif kind != "done":
        print(f"{t} · {kind}")


async def run(stream, raw: bool, t0: float) -> dict:
    """Relaie un flux et retourne les derniers événements utiles (check, portfolios, session)."""
    seen: dict = {}
    async for event in stream:
        show(event, raw, t0)
        if event.get("type") in ("check", "portfolios"):
            seen[event["type"]] = event
        if event.get("session"):
            seen["session"] = event["session"]
    return seen


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat", help="Message libre envoyé à Pépite après la construction")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    t0 = time.time()
    base = {"profile": SAMPLE_PROFILE, "constraints": SAMPLE_CONSTRAINTS}
    seen = await run(stream_check({"mode": "monport_check", **base}), args.raw, t0)
    if args.check_only or "check" not in seen:
        return
    seen |= await run(stream_monport({"mode": "monport", **base, "check": seen["check"]["check"],
                                      "session": seen.get("session")}), args.raw, t0)
    if "portfolios" in seen:
        LAST_RESULT.write_text(json.dumps(seen["portfolios"], ensure_ascii=False, indent=2), encoding="utf-8")
    if args.chat and seen.get("session"):
        await run(stream_chat({"mode": "monport_chat", "session": seen["session"], "message": args.chat}), args.raw, t0)


if __name__ == "__main__":
    asyncio.run(main())
