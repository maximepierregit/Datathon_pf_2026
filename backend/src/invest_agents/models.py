"""Fabrique de modèles Bedrock pour Strands."""

from __future__ import annotations

from typing import Literal, Optional

from botocore.config import Config
from strands.models import BedrockModel

from .config import get_settings


def build_model(kind: Literal["strong", "fast"] = "strong", *, max_tokens: Optional[int] = None) -> BedrockModel:
    """Modèle Bedrock d'un agent. `kind` choisit `MODEL_STRONG` ou `MODEL_FAST`; les deux valent Opus 5.5 par défaut.

    Opus 5.5 réfléchit toujours (réflexion adaptative, impossible à désactiver). `MODEL_EFFORT` règle la profondeur
    (low, medium, high, xhigh, max) dans `output_config.effort`, et non dans `thinking`. ENABLE_THINKING=true
    demande en plus le résumé de la réflexion, que le frontend affiche (sans lui, les blocs arrivent vides).
    """
    s = get_settings()
    fields: dict = {"output_config": {"effort": s.effort}}
    if s.thinking:
        fields["thinking"] = {"type": "adaptive", "display": "summarized"}
    return BedrockModel(
        model_id=s.model_strong if kind == "strong" else s.model_fast,
        region_name=s.region,
        max_tokens=max_tokens or s.max_tokens,
        additional_request_fields=fields,
        boto_client_config=Config(read_timeout=300, retries={"max_attempts": 4, "mode": "adaptive"}),
    )
