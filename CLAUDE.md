# MonPort · Datathon 2026

Équipe 20 (Maxime Pierre, Ioannis Nikoloudis, Jorge Velez, Jérémy Langevin). Client : BNCD (Banque Nationale Courtage Direct). Remise le 2026-11-15 au soir ; le jury juge une vidéo et un one-pager, l'UI et le marketing comptent pour 25 %. Hackathon de 34 h : on vise ce qui se voit dans la démo.

## Le produit

Outil agentique qui **propose** des portefeuilles à un client de courtage direct, sans jamais en imposer un. C'est le client qui choisit.

Le produit s'appelle **MonPort** (signature « BNCD | MonPort »). Il s'appelait Bas de Laine : les identifiants internes (`bas-de-laine`, `bas_de_laine`, ressources AWS) gardent l'ancien nom.

**Pépite** (la mascotte) est l'analyste : elle reçoit les réponses au questionnaire en JSON, juge leur cohérence, puis écrit les 3 profils de contraintes (JSON) envoyés aux 3 gestionnaires. Ce qu'on présente dépend de son verdict :

- **Profil incohérent** : 3 portefeuilles. **Tes contraintes** (ce que le client a demandé, affiché par défaut, « Point de départ »), **Profil d'abord (80/20)** et **Préférences d'abord (80/20)**. Les deux derniers sont des mélanges du capital calculés par le code : 80 % du portefeuille « Ton profil » + 20 % du portefeuille « Tes préférences », et l'inverse. Ids internes : `equilibre`, `prudent`, `conviction`.
- **Profil cohérent** : les 3 gestionnaires se font concurrence sur 3 variantes (prudente, fidèle, audacieuse) ; le **juge final** garde le meilleur, présenté seul (« Ton portefeuille »).

Parcours, une URL par écran (`frontend/src/App.tsx`) : accueil → `/profil/:step` → `/transition` → `/preferences/:step` → `/verification` → `/construction` → `/portefeuille`.

- **Profil**, 7 questions : âge, montant, ajouts prévus (fréquence + montant), objectif, horizon, réaction à une baisse de 20 %, aisance 1 à 5. Le questionnaire est la seule entrée : le raccourci « choisir mon niveau de risque » a été retiré.
- **Ajouts prévus** : tranche `contribution` à part dans le store. Elle ne part jamais aux agents et ne sert qu'aux projections du tableau de bord.
- **Préférences** : d'abord « FNB seulement ou FNB et titres individuels » (`constraints.vehicles`, `tous` par défaut). Le véhicule est indépendant des classes : un portefeuille 100 % FNB reste exposé aux actions, obligations, etc. Ensuite, une seule échelle à 5 niveaux (Exclure −2, Moins −1, Neutre 0 par défaut, Plus +1, Imposer +2), appliquée aux classes d'actifs (les sous-jacents) → géographie → thématiques → facteurs. Les facteurs n'apparaissent que si l'aisance est ≥ 4.
- **Vérification** : Pépite relit le questionnaire avant tout envoi. Incohérent : elle montre les enjeux et propose de recommencer (réponses gardées), ou de continuer avec 3 propositions. Cohérent : une boîte de texte permet un ajustement libre, intégré par Pépite aux 3 profils.
- **Garde-fous** : les incohérences profil ↔ préférences ne bloquent jamais (encadré de Pépite après les classes d'actifs, puis l'écran de vérification). Les exclusions du client s'appliquent aux 3 profils. Les limites réglementaires restent dures : aucune ligne au-delà de 40 %, pas de levier, jamais 100 % sur un seul placement.
- **Construction** : une carte par agent, avec son icône et son statut (À venir / En cours / Terminé), sous des noms en clair : **Pépite** (écrit les profils de contraintes), 3 **gestionnaires** en parallèle, 3 **juges**, le **juge final** (profil cohérent seulement), le **responsable des risques** (le CRO du backend). Pas de sigle (PM, CRO) à l'écran. Pépite raconte en haut de page.
- **Tableau de bord** : 3 onglets (profil incohérent) ou un seul portefeuille sans onglets (profil cohérent), + sélecteur de niveau Débutant / Intermédiaire / Avancé, par défaut selon l'aisance (1–2 Débutant, 3 Intermédiaire, 4–5 Avancé). La vue Avancé est réduite à 2 onglets (Performance, Risque). Avertissement à accepter à la première visite ; « Ajuster avec Pépite » ouvre un chat d'ajustement (règles scriptées pour l'instant).

## Ton et langue

Tout le texte visible est en français québécois :

- **Tutoiement**, phrases simples, sans jargon : le client débute peut-être.
- Typographie québécoise : pas d'espace avant `?` et `!` (« Quel âge as-tu? »), apostrophe typographique `’` dans les textes, guillemets « ». Les nombres passent par `frontend/src/lib/format.ts` (fr-CA, espaces insécables : « 5,2 % », « 25 000 $ »).
- Vocabulaire canadien générique : on parle de FNB et de placements. Pas d'enveloppes fiscales (CELI, REER, PEA…) ni de vocabulaire réglementaire européen (MiFID).
- On présente des propositions éducatives, jamais un conseil : « proposition, pas une recommandation », « c'est toi qui décides ».

Le code suit la même langue : commentaires et docstrings en français, courts ; identifiants en anglais, identifiants métier en français sans accent (`eclaireur`, `equilibre`, `liquidites`).

## Architecture

**`frontend/`** : React 19 + Vite + TypeScript + Tailwind 4 + Recharts, React Router, Zustand persisté en `sessionStorage` (`store.ts`).

- `api.ts` est le seul point de contact avec le backend. `runPipeline` lit le flux SSE de `/api/invocations` (proxy Vite vers le port 8091 en local) et rejoue un script d'exemple si le backend ne répond pas. `proposeAdjustment` applique encore des règles regex.
- `lib/engine.ts` est le moteur d'exemple (score de risque, répartition, indicateurs, séries des graphiques) qui fait tourner l'UI sans backend.
- `data/catalog.ts` contient les libellés, couleurs, explications et l'univers d'exemple (FNB fictifs `ACT-CA`, `THM-TEC`…).

**`backend/`** : pipeline multi-agents `invest_agents`, Strands sur Bedrock (Sonnet 5.5 et Haiku 5.5, us-east-1). `backend/CLAUDE.md` fait foi pour l'intérieur du pipeline.

- Principe : **les chiffres viennent du code, jamais du modèle** (optimiseur SLSQP, `constraints.evaluate`).
- Flux : Profil → 3 gestionnaires (Défensif, Équilibré, Croissance) → 3 Juges → CRO. Dataset réel (`data-prep/build_universe.py`, 801 actifs) publié sur S3 et lu par l'EC2 (`MONPORT_UNIVERSE_PARQUET_URI` dans `deploy/monport-backend.service`) ; en local, `MONPORT_UNIVERSE_PARQUET_URI` vaut par défaut le chemin de `config.DEFAULT_PARQUET_PATH` (réel ou synthétique via `scripts/make_sample_dataset.py`).
- `monport.py` orchestre le parcours MonPort avec les agents de Jérémy (sans passer par `orchestrator.py`) : `monport_check` (Pépite, `agents/pepite.py`) puis `monport` (profils de contraintes → gestionnaires → juges → mélanges 80/20 ou juge final `agents/final_judge.py` → CRO). Le code garantit : catalogue, exclusions, limite de 40 % par ligne (`max_position_weight`) et plafond par titre détenu en direct (`max_stock_weight`, un FNB n'y est pas soumis) ; répartition du profil pour les portefeuilles qui le suivent (`follow_profile` : plancher d'obligations de 80 % conservateur à 0 % agressif, pas de crypto pour un profil prudent) ; « Moins » / « Plus » rendus durs ailleurs (`promote_preferences`) ; un objectif par gestionnaire (`objective_for` : variations minimales / meilleur rendement pour le risque / rendement maximal) ; un plafond de volatilité inatteignable relevé (`ensure_feasible`) ; un profil inutilisable remplacé par `fallback_plan`. Les facteurs, quelques thématiques et les régions de plusieurs pays (sauf « Exclure ») n'ont pas d'équivalent dans le catalogue de contraintes.
- Déploiement : sur l'EC2 du front (`deploy/deploy-backend.sh`, service systemd `monport-backend` sur 127.0.0.1:8091, publié par nginx sous `/api/`). Le compte Workshop interdit de créer un rôle IAM, donc ni AgentCore Runtime ni Lambda : l'EC2 appelle Bedrock et lit le dataset (`s3://monport-datasets-381491955506/universe/universe.parquet`) avec le profil d'instance du participant. Ni base de données ni authentification : l'état reste dans la session du navigateur.
- **Aversion au risque** (`risk_position`, `risk_aversion` de `monport.py`) : capacité C = 0,6 × horizon + 0,4 × âge, tolérance T = 0,5 × réaction à la baisse + 0,3 × objectif + 0,2 × aisance, chacun ramené entre 0 et 1. S = min((C + T) / 2, C + 0,125) : la capacité limite la tolérance. A est interpolé en log entre les bornes des 5 profils (S = 0 → 25, 0,2 → 14, 0,4 → 7, 0,6 → 3,5, 0,8 → 1,5, 1 → 1). Pépite ne produit aucun chiffre de risque ; à la construction, si le client a écrit un ajustement qui parle de risque, elle peut décaler S de ±2 crans de 0,05 (`ConstraintPlan.risk_adjustment`). Cohérent : les variantes prudente, fidèle et audacieuse suivent S − 0,1, S et S + 0,1. Incohérent : « Ton profil » et « Tes contraintes » suivent S ; « Tes préférences » vise le meilleur rendement pour le risque (`max_sharpe`).

**`deploy/`** : `deploy.sh` build le front et le publie sur une EC2 (`bas-de-laine-front`, t3.small, nginx ; IP publique non fixe, elle change à chaque arrêt). `provision.sh` crée ou réutilise l'instance, la clé SSH (`~/.ssh/bas-de-laine-front.pem`) et le security group. `deploy-backend.sh` installe le backend sur la même instance (fichier d'échange de 2 Go, Python 3.12, venv dans `/opt/monport-backend`, `monport-backend.service`). `nginx.conf` publie `/api/` vers le backend : SSE sans tampon, 6 requêtes par minute et par IP. Sans backend, nginx répond 502 et le front rejoue son script d'exemple.

**`assets/mascot/`** : les 15 poses de Pépite (`svg/`), générées par `build.py` à partir de pièces communes. Pour modifier une pose, édite `build.py` puis relance `python3 assets/mascot/build.py`. Le front les importe depuis `../assets` (d'où `server.fs.allow: ['..']` dans `vite.config.ts`).

**`assets/intro/`** : l'intro de 3 s « BNCD | MonPort », jouée en écran de chargement par `components/Splash.tsx` une fois par session. `intro.html` est la source ; après l'avoir modifiée, relance `npm --prefix assets/intro run render` pour régénérer `intro.mp4`.

### À garder synchronisé

Ces paires sont dupliquées à la main ; toute modification touche les deux côtés :

- `frontend/src/types.ts` (`PipelineEvent`, `Portfolio`, `Profile`, `Constraints`) ↔ `backend/src/invest_agents/monport.py`.
- Les identifiants de `frontend/src/data/catalog.ts` (classes, régions, thématiques) ↔ les tables `CLASS_TARGETS`, `REGION_COUNTRIES`, `THEME_SECTORS` de `monport.py`.
- `metricsOf()` de `frontend/src/lib/engine.ts` ↔ `to_portfolio()` de `monport.py` (pire année, VaR, ES).
- Les messages de Pépite et des agents : script d'exemple de `api.ts` ↔ `Translator` et `build_portfolios` de `monport.py`.
- `riskPosition()`, `riskScore()`, `riskLabel()` et `coherenceWarnings()` de `engine.ts` ↔ `risk_position()`, `risk_score()`, `risk_label()` et `coherence_facts()` de `monport.py` ; `PORTFOLIO_META` ↔ `TRIO` ; noms des cartes de `Pipeline.tsx` ↔ `VARIANT_NAMES` et `BASE_NAMES`.

## Design

- Les tokens de `frontend/src/index.css` (couleurs tirées de bnc.ca : marine `#00314d`, rouge `#e41c23`…, Plus Jakarta Sans) font foi. Réutilise les composants de `components/ui.tsx`, `inputs.tsx` et `QuestionShell.tsx` avant d'en créer.
- Référence visuelle de structure : le canvas https://claude.ai/artifact/MSKiguhhEKpwS5rnDiiZh1. Ses couleurs d'origine (crème/pêche) ont été remplacées par celles de BNC, et les décisions de ce fichier l'emportent quand ils divergent (tutoiement, pas d'enveloppes, Pépite = les SVG du repo).
- Animations CSS discrètes uniquement, sous `prefers-reduced-motion: no-preference`.

## Commandes

- Front en local : configuration `frontend` de `.claude/launch.json` (port 5173). Vérification : `npm --prefix frontend run build` et `npm --prefix frontend run lint`.
- Backend : voir `backend/README.md`. En local : `python3.13 -m venv backend/.venv && backend/.venv/bin/pip install -e backend`, puis `backend/.venv/bin/python backend/scripts/make_sample_dataset.py`, puis configuration `backend` de `.claude/launch.json` (port 8091). Il faut des identifiants AWS valides (`aws sts get-caller-identity`). Le compte est un compte Workshop Studio (`WSParticipantRole`) : on copie le bloc `export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_SESSION_TOKEN=…` de la page de l'événement, et il expire ; certains services peuvent y être limités, d'où l'intérêt de tester un déploiement tôt.
- Mise en ligne du front : `./deploy/deploy.sh` (mêmes identifiants AWS).
- Mise en ligne du backend : `./deploy/deploy-backend.sh`, puis `./deploy/deploy.sh` si `nginx.conf` a changé. Le script exige que l'instance porte un profil IAM et ne l'attache jamais lui-même. Maxime a attaché à la main le profil `kiro-ide-browser-ParticipantInstanceProfile-ZPuZkruAoiE7` le 2026-11-14 : l'EC2, exposée sur Internet, a donc tous les droits de `WSParticipantRole`. À détacher après l'événement : `aws ec2 disassociate-iam-instance-profile --association-id iip-assoc-017cfabc74f52c8f0`.

## Git

Une branche `feat/…` par sujet, PR vers `main`, fusionnée sur GitHub (`maximepierregit/Datathon_pf_2026`).

## État au 2026-11-14

- Front complet sur données d'exemple et en ligne sur l'EC2 : accueil, profil, transition, préférences, construction, tableau de bord aux 3 niveaux, chat d'ajustement scripté, avertissement.
- Backend `invest_agents` en ligne sur l'EC2 (http://44.199.217.243 depuis le passage en t3.small le 2026-11-15), avec Pépite analyste : vérification en ~8 s, construction en ~80 s sur Bedrock, sur le dataset synthétique.
- Reste à faire : tutoyer les textes du CRO et des gestionnaires (encore écrits pour un conseiller, avec du jargon), brancher le chat d'ajustement sur le mode `refine` (un ajustement recalcule aujourd'hui avec le moteur d'exemple), détacher le profil IAM de l'EC2 après l'événement, puis vidéo et one-pager.
