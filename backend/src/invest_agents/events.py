"""Bus d'événements pour le streaming vers le frontend.

Chaque événement est un dict JSON-sérialisable:

    {"type": "status" | "thinking" | "tool" | "clarification" | "result" | "error" | "heartbeat",
     "step": str | None, "agent": str | None, ...}

Les agents tournent en parallèle (3 PM, 3 juges). Ils poussent dans une file partagée, que
l'orchestrateur relaie dans l'ordre d'arrivée.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Iterable, Optional

logger = logging.getLogger(__name__)

THINKING_FLUSH_CHARS = 160
HEARTBEAT_SECONDS = 10.0
_END = object()


class EventBus:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue()

    # ------------------------------------------------------------------ #
    # Émission
    # ------------------------------------------------------------------ #
    def emit(self, type: str, *, step: Optional[str] = None, agent: Optional[str] = None, **data: Any) -> None:
        self._queue.put_nowait({"type": type, "step": step, "agent": agent, **data})

    def close(self) -> None:
        self._queue.put_nowait(_END)

    def callback_handler(self, agent: str, step: str, ignore_tools: Iterable[str] = ()) -> "AgentStreamHandler":
        return AgentStreamHandler(self, agent, step, set(ignore_tools))

    # ------------------------------------------------------------------ #
    # Consommation
    # ------------------------------------------------------------------ #
    async def stream(self, worker: "asyncio.Task[Any]") -> AsyncIterator[dict]:
        """Relaie les événements jusqu'à la fin du worker. Envoie un heartbeat si rien ne passe."""
        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield {"type": "heartbeat", "step": None, "agent": None}
                continue
            if item is _END:
                break
            yield item
        await worker  # propage une exception éventuelle du worker


class AgentStreamHandler:
    """`callback_handler` Strands qui convertit les événements d'un agent en événements du bus.

    - réflexion du modèle (`reasoningText`): regroupée en blocs avant l'envoi
    - appels d'outils (`current_tool_use`): un événement au démarrage de chaque outil
    """

    def __init__(self, bus: EventBus, agent: str, step: str, ignore_tools: set[str]) -> None:
        self._bus, self._agent, self._step = bus, agent, step
        self._ignore = ignore_tools  # ex.: l'outil interne de sortie structurée
        self._thinking: list[str] = []
        self._seen_tools: set[str] = set()

    def bind(self, bus: EventBus, step: Optional[str] = None, ignore_tools: Iterable[str] = ()) -> None:
        """Rattache le handler au bus d'une nouvelle requête (les agents persistants vivent plus longtemps qu'elle)."""
        self.flush()
        self._bus, self._ignore = bus, set(ignore_tools)
        if step is not None:
            self._step = step

    def __call__(self, **kwargs: Any) -> None:
        try:
            text = kwargs.get("reasoningText")
            if text:
                self._thinking.append(text)
                if sum(len(t) for t in self._thinking) >= THINKING_FLUSH_CHARS or "\n" in text:
                    self.flush()
            tool = kwargs.get("current_tool_use")
            if (
                tool
                and tool.get("name")
                and tool["name"] not in self._ignore
                and tool.get("toolUseId") not in self._seen_tools
            ):
                self.flush()
                self._seen_tools.add(tool["toolUseId"])
                self._bus.emit("tool", step=self._step, agent=self._agent, name=tool["name"])
        except Exception:  # un handler ne doit jamais faire échouer l'agent
            logger.exception("Erreur dans le callback handler")

    def flush(self) -> None:
        if self._thinking:
            self._bus.emit("thinking", step=self._step, agent=self._agent, text="".join(self._thinking))
            self._thinking = []
