"""Exécute le pipeline en local (appelle Bedrock pour de vrai) et affiche le flux d'événements.

    python scripts/run_local.py                          # parcours initial avec le formulaire d'exemple
    python scripts/run_local.py --refine "pas d'énergie" # relance, à partir du dernier résultat sauvegardé
    python scripts/run_local.py --raw                    # affiche les événements en JSON brut
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

from invest_agents.orchestrator import stream_pipeline  # noqa: E402

SAMPLE_FORM = {
    "age": 42,
    "investment_amount_cad": 150000,
    "horizon_years": 12,
    "risk_tolerance": 3,
    "max_acceptable_loss_pct": 18,
    "objective": "balanced",
    "experience": "intermediate",
    "liquidity_needs": "low",
    "constraints": [
        {"type": "max_position_weight", "value": 0.12, "hard": True, "source": "form"},
        {"type": "min_positions", "value": 10, "hard": True, "source": "form"},
        {"type": "exclude_sector", "target": "Energy", "hard": True, "source": "form"},
    ],
}
LAST_RESULT = ROOT / "data" / "last_result.json"


def show(event: dict, raw: bool, t0: float) -> None:
    if raw:
        print(json.dumps(event, ensure_ascii=False, default=str))
        return
    t = f"[{time.time() - t0:5.1f}s]"
    kind, agent, step = event["type"], event.get("agent") or "-", event.get("step") or "-"
    if kind == "heartbeat":
        return
    if kind == "thinking":
        print(f"{t} 💭 {agent}: {event['text'].strip()[:220]}")
    elif kind == "tool":
        print(f"{t} 🔧 {agent}: outil {event['name']}")
    elif kind == "status":
        print(f"{t} ▶ [{step}] {agent} ({event.get('state')}): {event.get('text')}")
    elif kind == "profile":
        a = event["data"]["assessment"]
        print(f"{t} 👤 Profil: {a['risk_label']} (score {a['risk_score']}/10), vol max {a['suggested_max_volatility']:.0%}")
    elif kind == "clarification":
        print(f"{t} ❓ Clarification requise: {event['questions']}")
    elif kind == "error":
        print(f"{t} ❌ {event['code']}: {event['message']} {event.get('details')}")
    elif kind == "result":
        d = event["data"]
        print(f"{t} ✅ Résultat. Portefeuille conforme: {not d['no_compliant_portfolio']}")
        for item in d["portfolios"]:
            p, v = item["portfolio"], item["verdict"]
            m = p["metrics"]
            line = f"   - {p['mandate']}: " + (
                f"rend. {m['expected_return']:.1%} | vol {m['volatility']:.1%} | {m['n_positions']} pos. | "
                f"conforme={v['compliant'] if v else None}" if m else f"échec ({p['failure_reason']})"
            )
            print(line)
        if d["risk_report"]:
            r = d["risk_report"]
            print(f"   CRO: {len(r['profile_inconsistencies'])} incohérence(s), {len(r['warnings'])} mise(s) en garde")
            print(f"   {r['summary']}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refine", help="Message libre de relance")
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    if args.refine:
        context = json.loads(LAST_RESULT.read_text(encoding="utf-8"))["context"]
        payload = {"mode": "refine", "message": args.refine, "context": context}
    else:
        payload = {"mode": "initial", "form": SAMPLE_FORM}

    t0 = time.time()
    async for event in stream_pipeline(payload):
        show(event, args.raw, t0)
        if event["type"] == "result":
            LAST_RESULT.write_text(json.dumps(event["data"], ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
