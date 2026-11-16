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
    EXCLUDE_THEME = "exclude_theme"
    MAX_SECTOR_WEIGHT = "max_sector_weight"
    MIN_SECTOR_WEIGHT = "min_sector_weight"
    MAX_COUNTRY_WEIGHT = "max_country_weight"
    MIN_COUNTRY_WEIGHT = "min_country_weight"
    MAX_ASSET_CLASS_WEIGHT = "max_asset_class_weight"
    MIN_ASSET_CLASS_WEIGHT = "min_asset_class_weight"
    MAX_SYMBOL_WEIGHT = "max_symbol_weight"
    MIN_SYMBOL_WEIGHT = "min_symbol_weight"
    # Parts de la poche actions (et non du portefeuille entier): seules les actions en direct ont un secteur et un pays.
    MIN_SECTOR_SHARE = "min_sector_share"
    MAX_SECTOR_SHARE = "max_sector_share"
    MIN_COUNTRY_SHARE = "min_country_share"
    MAX_COUNTRY_SHARE = "max_country_share"
    # Thématiques étiquetées dans le Parquet (colonne `theme`): seules les actions détenues en direct étiquetées
    # comptent pour la part (un FNB étiqueté est dans la poche actions, jamais dans le groupe).
    MIN_THEME_SHARE = "min_theme_share"
    MAX_THEME_SHARE = "max_theme_share"
    MIN_FACTOR_EXPOSURE = "min_factor_exposure"
    MAX_FACTOR_EXPOSURE = "max_factor_exposure"
    # Questionnaire: pourcentage EXACT du portefeuille total (cash inclus). Classe d'actifs et type d'instrument:
    # tous les instruments admissibles. Pays, secteur, thématique: actions détenues en direct seulement.
    EXACT_ASSET_CLASS_WEIGHT = "exact_asset_class_weight"
    EXACT_INSTRUMENT_TYPE_WEIGHT = "exact_instrument_type_weight"
    EXACT_COUNTRY_WEIGHT = "exact_country_weight"
    EXACT_SECTOR_WEIGHT = "exact_sector_weight"
    EXACT_THEME_WEIGHT = "exact_theme_weight"


class Constraint(BaseModel):
    """Une contrainte structurée, appartenant au catalogue de contraintes."""

    type: ConstraintType
    target: Optional[str] = Field(
        default=None,
        description="Secteur, pays, thématique, classe d'actifs ou symbole visé. Pour les *_share et les "
        "exact_country/sector/theme_weight, un ou plusieurs libellés séparés par « | » (ex.: \"France|Germany\"). "
        "Null si le type n'a pas de cible.",
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
    # Relance avec contraintes assouplies: pourquoi le premier calcul a échoué (None s'il a réussi) et les contraintes
    # dures devenues préférences (libellés `catalog.describe`).
    relaunch_reason: Optional[str] = None
    relaxed: list[str] = Field(default_factory=list)
    # Traçabilité backend du Markowitz global (filtres, Sigma, sélection, A effectif); jamais envoyée au frontend.
    diagnostics: Optional[dict] = None


class JudgeVerdict(BaseModel):
    portfolio_id: str
    compliant: bool
    hard_violations: int
    soft_violations: int
    checks: list[ConstraintCheck]
    fit_score: int  # la note du juge, telle qu'il l'a donnée
    comment: str
    suggested_fixes: list[str] = Field(default_factory=list)
    # Points retirés par le code (profil cohérent, portefeuille relancé avec contraintes assouplies).
    penalty: int = 0

    @property
    def ranked_score(self) -> int:
        """La note qui départage le gagnant: celle du juge, moins la pénalité."""
        return max(0, self.fit_score - self.penalty)


# --------------------------------------------------------------------------- #
# Chief Risk Officer
# --------------------------------------------------------------------------- #
class RiskIssue(BaseModel):
    title: str
    detail: str
    severity: Literal["low", "medium", "high"]
    portfolio_id: Optional[str] = Field(default=None, description="Null si l'enjeu concerne le profil en général")
    sources: list[str] = Field(
        default_factory=list,
        description="1 à 3 identifiants de `preuves` qui prouvent ce point (ex.: pire_baisse, crypto, inflation_ca). "
        "Seulement des identifiants de la liste reçue.",
    )


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
    risk_explanation: str = Field(
        default="",
        description="2 ou 3 phrases tutoyées, sans formule: quelles réponses ont le plus pesé sur ton niveau de risque, "
        "et ce que ton aversion au risque change pour les gestionnaires. Seulement les chiffres de compute_risk_profile.",
    )


class PepiteCheck(ProfileAssessment):
    """Vérification du questionnaire: le texte de Pépite (PepiteReview) et le profil de risque calculé par le code
    (`monport.assess`). Le frontend le renvoie tel quel à la construction, où le code le recalcule."""

    coherent: bool
    issues: list[CoherenceIssue] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    risk_explanation: str = ""
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
    """Décision du juge: avis par portefeuille et gagnant (profil cohérent seulement)."""

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
        description="Toujours vide: les portefeuilles sont calculés par l'optimiseur et ne sont pas reconstruits. "
        "Conservé pour la compatibilité; le code l'ignore.",
    )


class PepiteReply(BaseModel):
    """Ce que Pépite dit au client à la fin d'un tour."""

    message: str = Field(description="Ta réponse au client, tutoyée, en français québécois, sans jargon")
    ready_to_rebuild: bool = Field(
        default=False,
        description="Chat seulement: true quand la demande de changement est claire, que tu as récapitulé les changements "
        "et demandé au client s'il veut relancer tes agents. False sinon.",
    )
    rebuild_request: str = Field(
        default="",
        description="Chat seulement, avec ready_to_rebuild: les changements convenus, précis et complets (portefeuille "
        "visé, classes d'actifs, régions, thématiques, exclusions, FNB seulement, niveau de risque), en 1 à 4 phrases "
        "écrites pour toi. Vide sinon.",
    )
