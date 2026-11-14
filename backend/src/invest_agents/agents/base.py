"""Exécution d'un agent Strands avec sortie structurée et streaming d'événements."""

from __future__ import annotations

from typing import Literal, Sequence, TypeVar

from pydantic import BaseModel
from strands import Agent

from ..events import EventBus
from ..models import build_model

T = TypeVar("T", bound=BaseModel)

LANGUAGE_RULE = (
    "Réponds toujours en français, y compris ta réflexion. "
    "Ne cite que des chiffres fournis dans le contexte ou retournés par les outils; n'invente aucune donnée."
)


class AgentError(RuntimeError):
    pass


async def run_agent(
    *,
    bus: EventBus,
    label: str,
    step: str,
    kind: Literal["strong", "fast"],
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
    tools: Sequence = (),
    start_text: str,
    done_text: str = "Terminé",
) -> T:
    handler = bus.callback_handler(label, step, ignore_tools={schema.__name__})
    agent = Agent(
        model=build_model(kind),
        system_prompt=f"{system_prompt}\n\n{LANGUAGE_RULE}",
        tools=list(tools),
        callback_handler=handler,
    )
    bus.emit("status", step=step, agent=label, state="start", text=start_text)
    try:
        result = await agent.invoke_async(user_prompt, structured_output_model=schema)
    except Exception as exc:
        bus.emit("status", step=step, agent=label, state="error", text=f"Échec: {type(exc).__name__}")
        raise AgentError(f"{label}: {type(exc).__name__}: {exc}") from exc
    finally:
        handler.flush()
    output = result.structured_output
    if output is None:
        bus.emit("status", step=step, agent=label, state="error", text="Aucune sortie structurée")
        raise AgentError(f"{label}: aucune sortie structurée")
    bus.emit("status", step=step, agent=label, state="done", text=done_text)
    return output
