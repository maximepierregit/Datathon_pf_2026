"""Test de fumée de la Gateway: liste les outils, filtre l'univers, optimise un portefeuille et le vérifie, en MCP
signé SigV4 (identifiants AWS courants). URL lue dans deploy/state/gateway-url.

    python scripts/smoke_gateway.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from strands.tools.mcp import MCPClient  # noqa: E402

from invest_agents.gateway import TARGET, SigV4Auth, _parse  # noqa: E402

URL = (ROOT.parent / "deploy" / "state" / "gateway-url").read_text().strip()


def main() -> int:
    client = MCPClient(url=URL, auth_provider=SigV4Auth(), startup_timeout=60)
    client.start()
    try:
        names = sorted(t.tool_name for t in client.list_tools_sync())
        print("outils:", names)
        t0 = time.time()
        constraints = [{"type": "max_position_weight", "value": 0.25}]
        screen = _parse(client.call_tool_sync("s", f"{TARGET}___screen_assets", {"constraints": constraints, "limit": 10}))
        symbols = [a["symbol"] for a in screen["assets"]]
        opt = _parse(client.call_tool_sync("o", f"{TARGET}___optimize_portfolio",
                                           {"symbols": symbols, "objective": "max_sharpe", "constraints": constraints}))
        print(f"optimize_portfolio: {opt['status']}, volatilité {opt['metrics']['volatility']:.3f}, "
              f"{len(opt['weights'])} positions ({time.time() - t0:.1f} s)")
        check = _parse(client.call_tool_sync("c", f"{TARGET}___check_portfolio_constraints",
                                             {"weights": opt["weights"], "constraints": constraints}))
        print("contraintes respectées:", check["all_hard_respected"])
        return 0 if len(names) >= 6 and opt["status"] in ("optimal", "feasible") and check["all_hard_respected"] else 1
    finally:
        client.stop(None, None, None)


if __name__ == "__main__":
    sys.exit(main())
