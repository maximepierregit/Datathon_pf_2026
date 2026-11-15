"""Exécution d'un agent Strands avec sortie structurée et événements de streaming.

`run_agent` lance un agent jetable. `AgentHandle` garde l'agent (et donc son historique: réflexion, outils, essais)
pour qu'on puisse l'interroger plus tard, par exemple quand le client demande pourquoi un portefeuille a cette forme.
"""

from __future__ import annotations

import asyncio
from typing import Optional, Sequence, TypeVar

from pydantic import BaseModel
from strands import Agent
from strands.agent.conversation_manager import NullConversationManager

from ..events import AgentStreamHandler, EventBus
from ..models import ModelKind, build_model

T = TypeVar("T", bound=BaseModel)

LANGUAGE_RULE = (
    "Réponds toujours en français, y compris ta réflexion. "
    "Ne cite que des chiffres fournis dans le contexte ou retournés par les outils; n'invente aucune donnée."
)


class AgentError(RuntimeError):
    pass


class AgentHandle:
    """Un agent Strands réutilisable. Les appels sont sérialisés (Strands refuse deux appels simultanés).

    `persistent=True` garde l'historique complet: pas de fenêtre glissante, car les blocs de réflexion sont liés au
    début de la conversation et Bedrock rejette un historique tronqué (400). Une conversation de MonPort reste courte.
    """

    def __init__(
        self,
        *,
        label: str,
        step: str,
        kind: ModelKind = "strong",
        system_prompt: str,
        tools: Sequence = (),
        persistent: bool = False,
    ) -> None:
        self.label, self.step = label, step
        self._lock = asyncio.Lock()
        self._handler = AgentStreamHandler(None, label, step, set())  # type: ignore[arg-type]  # lié à chaque appel
        self.agent = Agent(
            name=label,  # nom affiché dans les traces CloudWatch (invoke_agent <nom>)
            trace_attributes={"monport.agent": label, "monport.model_kind": kind},
            model=build_model(kind),
            system_prompt=f"{system_prompt}\n\n{LANGUAGE_RULE}",
            tools=list(tools),
            callback_handler=self._handler,
            conversation_manager=NullConversationManager() if persistent else None,
        )

    async def _invoke(self, bus: EventBus, prompt: str, schema: Optional[type[BaseModel]], *, step: Optional[str],
                      start_text: str, done_text: str):
        step = step or self.step
        async with self._lock:
            self._handler.bind(bus, step, {schema.__name__} if schema else ())
            bus.emit("status", step=step, agent=self.label, state="start", text=start_text)
            try:
                if schema is None:
                    result = await self.agent.invoke_async(prompt)
                else:
                    result = await self.agent.invoke_async(prompt, structured_output_model=schema)
            except Exception as exc:
                bus.emit("status", step=step, agent=self.label, state="error", text=f"Échec: {type(exc).__name__}")
                raise AgentError(f"{self.label}: {type(exc).__name__}: {exc}") from exc
            finally:
                self._handler.flush()
            output = str(result).strip() if schema is None else result.structured_output
            if not output:
                bus.emit("status", step=step, agent=self.label, state="error", text="Aucune sortie")
                raise AgentError(f"{self.label}: aucune sortie structurée" if schema else f"{self.label}: réponse vide")
            bus.emit("status", step=step, agent=self.label, state="done", text=done_text)
            return output

    async def run(self, bus: EventBus, prompt: str, schema: type[T], *, start_text: str, done_text: str = "Terminé",
                  step: Optional[str] = None) -> T:
        """Un tour qui se termine par une sortie structurée."""
        return await self._invoke(bus, prompt, schema, step=step, start_text=start_text, done_text=done_text)

    async def ask(self, bus: EventBus, question: str, *, start_text: str, done_text: str = "Réponse prête",
                  step: Optional[str] = None) -> str:
        """Un tour en texte libre (par exemple une justification demandée plus tard)."""
        return await self._invoke(bus, question, None, step=step, start_text=start_text, done_text=done_text)


async def run_agent(
    *,
    bus: EventBus,
    label: str,
    step: str,
    kind: ModelKind,
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    tools: Sequence = (),
    start_text: str,
    done_text: str = "Terminé",
) -> T:
    handle = AgentHandle(label=label, step=step, kind=kind, system_prompt=system_prompt, tools=tools)
    return await handle.run(bus, user_prompt, schema, start_text=start_text, done_text=done_text)
