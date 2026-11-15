"""Exécute le contrat du frontend en local (appelle Bedrock) et affiche les `PipelineEvent`.

    python scripts/run_web.py                              # pipeline, profil et préférences d'exemple
    python scripts/run_web.py --adjust "pas de pétrole"    # ajustement du portefeuille Équilibré
    python scripts/run_web.py --raw                        # JSON brut, un événement par ligne
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invest_agents.web_adjust import stream_adjust  # noqa: E402
from invest_agents.web_pipeline import stream_web_pipeline  # noqa: E402

# Mêmes valeurs par défaut que DEFAULT_PROFILE (frontend/src/store.ts)
PROFILE = {"age": 35, "amount": 10000, "objective": "fructifier", "horizon": 12, "lossReaction": 2, "comfort": 3}
CONSTRAINTS = {"vehicles": "tous", "classes": {"crypto": 1}, "regions": {"canada": 1},
               "themes": {"fossiles": -2, "tech": 1}, "factors": {}}
LAST = ROOT / "data" / "last_web_result.json"


def show(e: dict, t0: float, raw: bool) -> None:
    if raw:
        print(json.dumps(e, ensure_ascii=False))
        return
    t = f"[{time.time() - t0:5.1f}s]"
    k = e["type"]
    if k == "heartbeat":
        return
    if k == "thinking":
        print(f"{t}   💭 {e['source']}: {e['text'].strip()[:140]}")
    elif k == "agent_status":
        print(f"{t} {e['agent']:12} {e['status']:7} {e['message']}")
    elif k == "portfolios":
        for pid, p in e["portfolios"].items():
            m = p["metrics"]
            alloc = {c: round(w, 2) for c, w in p["allocation"].items() if w > 0}
            print(f"{t} 📊 {p['name']:10} rend {m['expectedReturn']:.1%} vol {m['volatility']:.1%} pire année "
                  f"{m['worstYear']:.1%} frais {m['fees']:.2%} | {len(p['holdings'])} lignes | {alloc}")
            for w in p["warnings"]:
                print(f"{' ' * 9}⚠ {w[:150]}")
            for n in p["agentNotes"]:
                print(f"{' ' * 9}• {n[:150]}")
    elif k == "adjust":
        pr = e["proposal"]
        print(f"{t} 🔧 {pr['reply']}  patch={pr.get('patch')} riskShift={pr.get('riskShift')}")
        for c in pr["changes"]:
            print(f"{' ' * 9}{c['label']}: {c['before']:.1%} → {c['after']:.1%}")
        if pr.get("warning"):
            print(f"{' ' * 9}⚠ {pr['warning']}")
    else:
        print(f"{t} {k}: {json.dumps({x: y for x, y in e.items() if x != 'type'}, ensure_ascii=False)[:200]}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adjust")
    ap.add_argument("--portfolio", default="equilibre")
    ap.add_argument("--raw", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    if args.adjust:
        current = json.loads(LAST.read_text(encoding="utf-8"))[args.portfolio]
        payload = {"mode": "adjust", "portfolio": args.portfolio, "message": args.adjust, "profile": PROFILE,
                   "constraints": CONSTRAINTS, "current": current}
        stream = stream_adjust(payload)
    else:
        stream = stream_web_pipeline({"mode": "pipeline", "profile": PROFILE, "constraints": CONSTRAINTS})
    async for e in stream:
        show(e, t0, args.raw)
        if e["type"] == "portfolios":
            LAST.write_text(json.dumps(e["portfolios"], ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
