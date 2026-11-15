"""Contrats de données du pipeline (entrées, sorties d'agents, résultat final).

Ces modèles servent aussi de schémas de sortie structurée pour les agents Strands.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Contraintes
# --------------------------------------------------------------------------- #
class ConstraintType(str, Enum):
    MAX_POSITION_WEIGHT = "max_position_weight"
    MIN_POSITIONS = "min_positions"
    MAX_POSITIONS = "max_positions"
    MAX_VOLATILITY = "max_volatility"
    MIN_EXPECTED_RETURN = "min_expected_return"
    EXCLUDE_SECTOR = "exclude_sector"
    EXCLUDE_COUNTRY = "exclude_country"
    EXCLUDE_ASSET_CLASS = "exclude_asset_class"
    EXCLUDE_SYMBOL = "exclude_symbol"
    MAX_SECTOR_WEIGHT = "max_sector_weight"
    MIN_SECTOR_WEIGHT = "min_sector_weight"
    MAX_COUNTRY_WEIGHT = "max_country_weight"
    MIN_COUNTRY_WEIGHT = "min_country_weight"
    MAX_ASSET_CLASS_WEIGHT = "max_asset_class_weight"
    MIN_ASSET_CLASS_WEIGHT = "min_asset_class_weight"
    MAX_SYMBOL_WEIGHT = "max_symbol_weight"
    MIN_SYMBOL_WEIGHT = "min_symbol_weight"
    EXCLUDE_REGION = "exclude_region"
    MAX_REGION_WEIGHT = "max_region_weight"
    MIN_REGION_WEIGHT = "min_region_weight"
    EXCLUDE_THEME = "exclude_theme"
    MAX_THEME_WEIGHT = "max_theme_weight"
    MIN_THEME_WEIGHT = "min_theme_weight"
    EXCLUDE_FACTOR = "exclude_factor"
    MAX_FACTOR_WEIGHT = "max_factor_weight"
    MIN_FACTOR_WEIGHT = "min_factor_weight"
    EXCLUDE_INSTRUMENT_TYPE = "exclude_instrument_type"
    MAX_INSTRUMENT_LINE_WEIGHT = "max_instrument_line_weight"


class Constraint(BaseModel):
    """Une contrainte structurée, appartenant au catalogue de contraintes."""

    type: ConstraintType
    target: Optional[str] = Field(
        default=None,
        description="Secteur, pays, classe d'actifs ou symbole visé. Null si le type n'a pas de cible.",
    )
    value: Optional[float] = Field(
        default=None,
        description="Valeur numérique: fraction entre 0 et 1 pour les poids, la volatilité et le rendement "
        "(0.10 = 10 %), nombre entier pour les comptes de positions. Null pour les exclusions.",
    )
    hard: bool = Field(
        default=True,
        description="True: contrainte dure appliquée par l'optimiseur. False: préférence, évaluée mais non bloquante.",
    )
    source: Literal["form", "chat", "profile", "preference", "safety", "mandate"] = "form"
    note: Optional[str] = Field(default=None, description="Phrase de l'utilisateur à l'origine de la contrainte.")


class ConstraintRef(BaseModel):
    """Référence à une contrainte existante (pour la retirer)."""

    type: ConstraintType
    target: Optional[str] = None


# --------------------------------------------------------------------------- #
# Entrée: formulaire (structuré, sans champ libre)
# --------------------------------------------------------------------------- #
class InvestorForm(BaseModel):
    """Formulaire envoyé par le frontend. Les champs sont une proposition à aligner avec le frontend."""

    model_config = ConfigDict(extra="ignore")

    age: Optional[int] = Field(default=None, ge=18, le=110)
    investment_amount_cad: float = Field(gt=0)
    horizon_years: int = Field(ge=1, le=60)
    risk_tolerance: int = Field(ge=1, le=5, description="Auto-évaluation: 1 très prudent, 5 très agressif")
    max_acceptable_loss_pct: Optional[float] = Field(
        default=None, ge=0, le=100, description="Perte annuelle maximale acceptée, en %"
    )
    loss_reaction: Optional[Literal["vend_tout", "vend_une_partie", "attend", "investit_plus"]] = Field(
        default=None, description="Réaction déclarée à une baisse de 20 % en un mois"
    )
    objective: Literal["preservation", "income", "balanced", "growth", "aggressive_growth"] = "balanced"
    experience: Literal["none", "basic", "intermediate", "advanced"] = "basic"
    liquidity_needs: Literal["low", "medium", "high"] = "medium"
    constraints: list[Constraint] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent Extraction (relance conversationnelle)
# --------------------------------------------------------------------------- #
class ExtractionResult(BaseModel):
    """Contraintes extraites d'un message libre, rapprochées du catalogue."""

    constraints: list[Constraint] = Field(
        default_factory=list, description="Nouvelles contraintes reconnues et rattachées au catalogue."
    )
    removals: list[ConstraintRef] = Field(
        default_factory=list, description="Contraintes existantes que l'utilisateur demande de retirer."
    )
    unmatched: list[str] = Field(
        default_factory=list,
        description="Passages du message qui ne correspondent à aucune contrainte du catalogue ou sont ambigus.",
    )
    clarification_questions: list[str] = Field(
        default_factory=list, description="Questions à poser à l'utilisateur pour lever les ambiguïtés."
    )


# --------------------------------------------------------------------------- #
# Agent Profil
# --------------------------------------------------------------------------- #
class ProfileAssessment(BaseModel):
    """Sortie de l'agent Profil (jugement qualitatif). Le code assemble ensuite le profil complet."""

    risk_score: int = Field(ge=1, le=10, description="Score de risque global: 1 très prudent, 10 très agressif")
    risk_label: Literal["conservateur", "modere", "equilibre", "dynamique", "agressif"]
    suggested_max_volatility: float = Field(
        gt=0.02, le=0.60, description="Volatilité annualisée maximale raisonnable pour ce profil (0.12 = 12 %)"
    )
    suggested_max_position_weight: float = Field(
        gt=0.02, le=1.0, description="Poids maximal raisonnable d'un titre (0.10 = 10 %)"
    )
    summary: str = Field(description="Résumé du profil en 3 à 5 phrases, en français")
    key_points: list[str] = Field(default_factory=list, description="Éléments déterminants du profil")
    flags: list[str] = Field(
        default_factory=list, description="Tensions ou incohérences observées dès l'entrée (ex.: horizon court et objectif agressif)"
    )


class InvestorProfile(BaseModel):
    form: InvestorForm
    assessment: ProfileAssessment
    constraints: list[Constraint]


# --------------------------------------------------------------------------- #
# Portefeuilles
# --------------------------------------------------------------------------- #
class PortfolioMetrics(BaseModel):
    expected_return: float
    volatility: float
    sharpe: float
    max_drawdown: float
    n_positions: int
    hhi: float
    effective_n: float
    sector_weights: dict[str, float]
    country_weights: dict[str, float]
    asset_class_weights: dict[str, float]
    region_weights: dict[str, float] = Field(default_factory=dict)
    fees: float = 0.0


class Position(BaseModel):
    symbol: str
    name: str
    weight: float
    sector: str
    country: str
    asset_class: str
    rationale: Optional[str] = None


class PositionNote(BaseModel):
    symbol: str
    rationale: str = Field(description="Une phrase expliquant le rôle de ce titre dans le portefeuille")


class PMNarrative(BaseModel):
    """Sortie structurée du gestionnaire de portefeuille: le texte seulement, jamais les chiffres."""

    summary: str = Field(description="Stratégie du portefeuille en 3 à 5 phrases, en français")
    position_notes: list[PositionNote] = Field(default_factory=list)
    tradeoffs: str = Field(description="Compromis et limites de ce portefeuille, en français")


class ConstraintCheck(BaseModel):
    constraint: Constraint
    label: str
    passed: bool
    actual: Optional[float] = None
    limit: Optional[float] = None
    message: str


class Portfolio(BaseModel):
    id: str
    mandate: str
    mandate_description: str
    status: Literal["ok", "failed"] = "ok"
    positions: list[Position] = Field(default_factory=list)
    metrics: Optional[PortfolioMetrics] = None
    summary: str = ""
    tradeoffs: str = ""
    failure_reason: Optional[str] = None


class JudgeOpinion(BaseModel):
    """Sortie structurée de l'agent Juge (avis qualitatif). La conformité vient du code."""

    fit_score: int = Field(ge=0, le=10, description="Adéquation globale du portefeuille au profil, de 0 à 10")
    comment: str = Field(description="Évaluation en 2 à 4 phrases, en français")
    suggested_fixes: list[str] = Field(default_factory=list, description="Corrections concrètes si des écarts existent")


class JudgeVerdict(BaseModel):
    portfolio_id: str
    compliant: bool
    hard_violations: int
    soft_violations: int
    checks: list[ConstraintCheck]
    fit_score: int
    comment: str
    suggested_fixes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Chief Risk Officer
# --------------------------------------------------------------------------- #
class RiskIssue(BaseModel):
    title: str
    detail: str
    severity: Literal["low", "medium", "high"]
    portfolio_id: Optional[str] = Field(default=None, description="Null si l'enjeu concerne le profil en général")


class RiskReport(BaseModel):
    profile_inconsistencies: list[RiskIssue] = Field(
        default_factory=list, description="Incohérences internes du profil de l'investisseur"
    )
    warnings: list[RiskIssue] = Field(
        default_factory=list, description="Mises en garde sur les portefeuilles présentés"
    )
    summary: str = Field(description="Synthèse du CRO en 3 à 5 phrases, en français")
