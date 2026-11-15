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
    MAX_STOCK_WEIGHT = "max_stock_weight"
    MIN_POSITIONS = "min_positions"
    MAX_POSITIONS = "max_positions"
    MAX_VOLATILITY = "max_volatility"
    MIN_EXPECTED_RETURN = "min_expected_return"
    EXCLUDE_SECTOR = "exclude_sector"
    EXCLUDE_COUNTRY = "exclude_country"
    EXCLUDE_ASSET_CLASS = "exclude_asset_class"
    EXCLUDE_INSTRUMENT_TYPE = "exclude_instrument_type"
    EXCLUDE_SYMBOL = "exclude_symbol"
    MAX_SECTOR_WEIGHT = "max_sector_weight"
    MIN_SECTOR_WEIGHT = "min_sector_weight"
    MAX_COUNTRY_WEIGHT = "max_country_weight"
    MIN_COUNTRY_WEIGHT = "min_country_weight"
    MAX_ASSET_CLASS_WEIGHT = "max_asset_class_weight"
    MIN_ASSET_CLASS_WEIGHT = "min_asset_class_weight"
    MAX_SYMBOL_WEIGHT = "max_symbol_weight"
    MIN_SYMBOL_WEIGHT = "min_symbol_weight"
    MIN_FACTOR_EXPOSURE = "min_factor_exposure"
    MAX_FACTOR_EXPOSURE = "max_factor_exposure"


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
        "(0.10 = 10 %), nombre entier pour les comptes de positions, score en écarts-types entre -3 et 3 pour "
        "l'exposition à un facteur (0.5 = un demi écart-type au-dessus de la moyenne du secteur). "
        "Null pour les exclusions.",
    )
    hard: bool = Field(
        default=True,
        description="True: contrainte dure appliquée par l'optimiseur. False: préférence, évaluée mais non bloquante.",
    )
    source: Literal["form", "chat", "profile"] = "form"
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


# --------------------------------------------------------------------------- #
# Pépite, l'analyste du frontend MonPort (monport.py)
# --------------------------------------------------------------------------- #
MonPortSlot = Literal["prudent", "equilibre", "conviction"]


class CoherenceIssue(BaseModel):
    title: str = Field(description="L'enjeu en quelques mots, tutoyé, sans jargon")
    detail: str = Field(description="Une ou deux phrases tutoyées: ce qui se contredit et ce que ça risque de te coûter")


class PepiteReview(BaseModel):
    """Sortie de Pépite à la vérification: du texte et la cohérence. Le profil de risque est calculé par le code."""

    summary: str = Field(description="Ce que tu retiens du profil, en 2 à 4 phrases tutoyées")
    key_points: list[str] = Field(default_factory=list, description="Éléments déterminants du profil")
    flags: list[str] = Field(default_factory=list, description="Petites tensions qui ne rendent pas le profil incohérent")
    coherent: bool = Field(description="False si les préférences contredisent nettement le profil de risque")
    issues: list[CoherenceIssue] = Field(
        default_factory=list, description="Les enjeux à montrer au client; liste vide si le profil est cohérent"
    )
    questions: list[str] = Field(
        default_factory=list,
        description="Questions tutoyées à poser au client pour clarifier une incohérence ou une réponse ambiguë. "
        "Liste vide si le profil est cohérent.",
    )


class PepiteCheck(ProfileAssessment):
    """Vérification du questionnaire: le texte de Pépite (PepiteReview) et le profil de risque calculé par le code
    (`monport.assess`). Le frontend le renvoie tel quel à la construction, où le code le recalcule."""

    coherent: bool
    issues: list[CoherenceIssue] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risk_position: float = Field(default=0.5, ge=0, le=1, description="0 très prudent … 1 très audacieux")
    risk_aversion: float = Field(default=7.0, ge=1, le=25, description="Coefficient A: 1 très audacieux … 25 très prudent")


class ConstraintProfile(BaseModel):
    """Un profil de contraintes, envoyé tel quel à un gestionnaire."""

    slot: MonPortSlot
    rationale: str = Field(description="Une ou deux phrases pour le gestionnaire: ce que vise ce profil")
    constraints: list[Constraint]


class ConstraintPlan(BaseModel):
    profiles: list[ConstraintProfile] = Field(description="Exactement 3 profils, un par slot (prudent, equilibre, conviction)")


class SlotOpinion(BaseModel):
    """Avis du juge sur un portefeuille. La conformité n'en fait pas partie: elle est calculée par le code."""

    slot: MonPortSlot
    fit_score: int = Field(ge=0, le=10, description="Adéquation du portefeuille au profil et aux préférences, de 0 à 10")
    comment: str = Field(description="2 à 3 phrases: ce qui va et ce qui ne va pas, rapport de risque compris")
    suggested_fixes: list[str] = Field(default_factory=list, description="Corrections concrètes si des écarts existent")


class ReoptimizeRequest(BaseModel):
    slot: MonPortSlot
    instructions: str = Field(
        description="Ce que le gestionnaire doit corriger, précis et réalisable sans enfreindre les contraintes dures"
    )


class JudgeDecision(BaseModel):
    """Décision du juge: avis par portefeuille, gagnant (profil cohérent seulement) et demandes de réoptimisation."""

    opinions: list[SlotOpinion] = Field(description="Un avis par portefeuille construit")
    winner: Optional[MonPortSlot] = Field(
        default=None, description="Le meilleur portefeuille pour le client. Null si le profil est incohérent."
    )
    justification: str = Field(
        default="",
        description="Deux ou trois phrases tutoyées, sans jargon, qui expliquent le choix au client. Vide sans gagnant.",
    )
    reoptimize: list[ReoptimizeRequest] = Field(
        default_factory=list,
        description="Portefeuilles à reconstruire parce que le rapport de risque ou la conformité l'exige. Vide sinon.",
    )


class PepiteReply(BaseModel):
    """Ce que Pépite dit au client à la fin d'un tour."""

    message: str = Field(description="Ta réponse au client, tutoyée, en français québécois, sans jargon")
