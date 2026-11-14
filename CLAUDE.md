# Bas de Laine · Datathon 2026

Équipe 20 (Maxime Pierre, Ioannis Nikoloudis, Jorge Velez, Jérémy Langevin). Client : BNCD (Banque Nationale Courtage Direct). Remise le 2026-11-15 au soir ; le jury juge une vidéo et un one-pager, l'UI et le marketing comptent pour 25 %. Hackathon de 34 h : on vise ce qui se voit dans la démo.

## Le produit

Outil agentique qui **propose** trois portefeuilles à un client de courtage direct, sans jamais en imposer un. C'est le client qui choisit.

- **Prudent** : le profil passe avant les préférences.
- **Équilibré** : le juste milieu, portefeuille affiché par défaut (« Point de départ »).
- **Conviction** : les préférences passent avant le profil, dans les limites de sécurité.

Parcours, une URL par écran (`frontend/src/App.tsx`) : accueil → `/profil/:step` → `/transition` → `/preferences/:step` → `/construction` → `/portefeuille`.

- **Profil**, 7 questions : âge, montant, ajouts prévus (fréquence + montant), objectif, horizon, réaction à une baisse de 20 %, aisance 1 à 5. Le questionnaire est la seule entrée : le raccourci « choisir mon niveau de risque » a été retiré.
- **Ajouts prévus** : tranche `contribution` à part dans le store. Elle ne part jamais aux agents et ne sert qu'aux projections du tableau de bord.
- **Préférences** : d'abord « FNB seulement ou FNB et titres individuels » (`constraints.vehicles`, `tous` par défaut). Le véhicule est indépendant des classes : un portefeuille 100 % FNB reste exposé aux actions, obligations, etc. Ensuite, une seule échelle à 5 niveaux (Exclure −2, Moins −1, Neutre 0 par défaut, Plus +1, Imposer +2), appliquée aux classes d'actifs (les sous-jacents) → géographie → thématiques → facteurs. Les facteurs n'apparaissent que si l'aisance est ≥ 4.
- **Garde-fous** : les incohérences profil ↔ préférences ne font qu'avertir (encadré de Pépite après les classes d'actifs, repris par le Vérificateur pendant la construction). Les limites réglementaires restent dures : aucune ligne au-delà de 40 %, pas de levier, jamais 100 % sur un seul placement.
- **Construction** : trois agents affichés avec leur icône et leur statut (À venir / En cours / Terminé). L'**Éclaireur** filtre l'univers, le **Compositeur** construit les 3 portefeuilles, le **Vérificateur** les relit et peut en renvoyer un au Compositeur. **Pépite** (la mascotte) raconte.
- **Tableau de bord** : 3 onglets de portefeuille + sélecteur de niveau Débutant / Intermédiaire / Avancé, par défaut selon l'aisance (1–2 Débutant, 3 Intermédiaire, 4–5 Avancé). La vue Avancé est réduite à 2 onglets (Performance, Risque). Avertissement à accepter à la première visite ; « Ajuster avec Pépite » ouvre un chat d'ajustement (règles scriptées pour l'instant).

## Ton et langue

Tout le texte visible est en français québécois :

- **Tutoiement**, phrases simples, sans jargon : le client débute peut-être.
- Typographie québécoise : pas d'espace avant `?` et `!` (« Quel âge as-tu? »), apostrophe typographique `’` dans les textes, guillemets « ». Les nombres passent par `frontend/src/lib/format.ts` (fr-CA, espaces insécables : « 5,2 % », « 25 000 $ »).
- Vocabulaire canadien générique : on parle de FNB et de placements. Pas d'enveloppes fiscales (CELI, REER, PEA…) ni de vocabulaire réglementaire européen (MiFID).
- On présente des propositions éducatives, jamais un conseil : « proposition, pas une recommandation », « c'est toi qui décides ».

Le code suit la même langue : commentaires et docstrings en français, courts ; identifiants en anglais, identifiants métier en français sans accent (`eclaireur`, `equilibre`, `liquidites`).

## Architecture

**`frontend/`** : React 19 + Vite + TypeScript + Tailwind 4 + Recharts, React Router, Zustand persisté en `sessionStorage` (`store.ts`).

- `api.ts` est le seul point de contact avec le backend. Aujourd'hui il simule tout : `runPipeline` rejoue un script d'événements `PipelineEvent` (même forme que le futur flux SSE), `proposeAdjustment` applique des règles regex.
- `lib/engine.ts` est le moteur d'exemple (score de risque, répartition, indicateurs, séries des graphiques) qui fait tourner l'UI sans backend.
- `data/catalog.ts` contient les libellés, couleurs, explications et l'univers d'exemple (FNB fictifs `ACT-CA`, `THM-TEC`…).

**`backend/`** : agents Strands sur Amazon Bedrock (`us.anthropic.claude-opus-5-5`, us-east-1, `model.py`). Pas encore commité.

- Principe : **les chiffres viennent du code, jamais du modèle**. Le filtre de l'Éclaireur et l'optimiseur sont déterministes ; l'agent lit leur résultat par un outil et l'explique au client en ~40 mots, texte brut.
- `eclaireur.py` puis `compositeur.py`, enchaînés par `pipeline.py`. Chaque agent publie ses étapes via `emit(...)` au format `PipelineEvent`.
- `optimizer.py` est la traduction Python de `engine.ts`, à l'identique (même ordre d'addition, arrondi `floor(x + 0.5)` pour imiter `Math.round`). Le vrai optimiseur et l'univers réel de l'équipe le remplaceront en gardant la signature de `build_portfolio`.
- Cible retenue : déploiement sur Bedrock AgentCore Runtime (Lambda si AgentCore résiste), optimiseur dans le même service, ni base de données ni authentification : l'état reste dans la session du navigateur.

**`deploy/`** : `deploy.sh` build le front et le publie sur une EC2 (`bas-de-laine-front`, t3.micro, nginx). `provision.sh` crée ou réutilise l'instance, la clé SSH (`~/.ssh/bas-de-laine-front.pem`) et le security group. `nginx.conf` garde un `location /api/` commenté pour le backend.

**`assets/mascot/`** : les 15 poses de Pépite (`svg/`), générées par `build.py` à partir de pièces communes. Pour modifier une pose, édite `build.py` puis relance `python3 assets/mascot/build.py`. Le front les importe depuis `../assets` (d'où `server.fs.allow: ['..']` dans `vite.config.ts`).

### À garder synchronisé

Ces paires sont dupliquées à la main ; toute modification touche les deux côtés :

- `frontend/src/types.ts` (`PipelineEvent`, `Portfolio`, `Profile`, `Constraints`) ↔ les dictionnaires émis par le backend.
- `frontend/src/data/catalog.ts` ↔ `backend/bas_de_laine/catalog.py` (libellés, univers, hypothèses par classe).
- `frontend/src/lib/engine.ts` ↔ `backend/bas_de_laine/optimizer.py` (répartition, indicateurs, `PORTFOLIO_META`).
- Les messages de Pépite et des agents scriptés dans `api.ts` ↔ ceux de `pipeline.py` et des agents.

## Design

- Les tokens de `frontend/src/index.css` (couleurs tirées de bnc.ca : marine `#00314d`, rouge `#e41c23`…, Plus Jakarta Sans) font foi. Réutilise les composants de `components/ui.tsx`, `inputs.tsx` et `QuestionShell.tsx` avant d'en créer.
- Référence visuelle de structure : le canvas https://claude.ai/artifact/MSKiguhhEKpwS5rnDiiZh1. Ses couleurs d'origine (crème/pêche) ont été remplacées par celles de BNC, et les décisions de ce fichier l'emportent quand ils divergent (tutoiement, pas d'enveloppes, Pépite = les SVG du repo).
- Animations CSS discrètes uniquement, sous `prefers-reduced-motion: no-preference`.

## Commandes

- Front en local : configuration `frontend` de `.claude/launch.json` (port 5173). Vérification : `npm --prefix frontend run build` et `npm --prefix frontend run lint`.
- Backend : voir `backend/README.md`. Il faut des identifiants AWS valides (`aws sts get-caller-identity`). Le compte est un compte Workshop Studio (`WSParticipantRole`) : on copie le bloc `export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=… AWS_SESSION_TOKEN=…` de la page de l'événement, et il expire ; certains services peuvent y être limités, d'où l'intérêt de tester un déploiement tôt.
- Mise en ligne du front : `./deploy/deploy.sh` (mêmes identifiants AWS).

## Git

Une branche `feat/…` par sujet, PR vers `main`, fusionnée sur GitHub (`maximepierregit/Datathon_pf_2026`).

## État au 2026-11-14

- Front complet sur données d'exemple et en ligne sur l'EC2 : accueil, profil, transition, préférences, construction, tableau de bord aux 3 niveaux, chat d'ajustement scripté, avertissement.
- Backend local : Éclaireur et Compositeur fonctionnent sur Bedrock.
- Reste à faire : expliquer `vehicles` aux agents (`INPUT_LEGEND` de `catalog.py`) et faire écarter les titres individuels par l'Éclaireur quand l'univers réel en contiendra, Vérificateur côté backend, exposer le pipeline en HTTP/SSE et brancher `api.ts` dessus, déployer le backend, intégrer l'univers réel et l'optimiseur de l'équipe, puis vidéo et one-pager.
