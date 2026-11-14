"""Fabrique de modèles Bedrock pour Strands."""

from __future__ import annotations

from typing import Literal

from botocore.config import Config
from strands.models import BedrockModel

from .config import get_settings


def build_model(kind: Literal["strong", "fast"], *, max_tokens: int = 8000) -> BedrockModel:
    """`strong` pour les PM et le CRO, `fast` pour le Profil, l'Extraction et le Juge.

    La réflexion (streamée au frontend) est activée si ENABLE_THINKING=true.
    """
    s = get_settings()
    fields = {"thinking": {"type": "adaptive", "display": "summarized"}} if s.thinking else None
    return BedrockModel(
        model_id=s.model_strong if kind == "strong" else s.model_fast,
        region_name=s.region,
        max_tokens=max_tokens,
        additional_request_fields=fields,
        boto_client_config=Config(read_timeout=300, retries={"max_attempts": 4, "mode": "adaptive"}),
    )
