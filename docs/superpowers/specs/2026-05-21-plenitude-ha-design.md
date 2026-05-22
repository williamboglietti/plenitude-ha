# Spec — Intégration Home Assistant Plenitude

**Date** : 2026-05-21
**Statut** : Design validé, prêt pour planification d'implémentation
**Format de livraison** : Custom component Home Assistant distribué via HACS

---

## 1. Contexte

Plenitude (anciennement Eni Gas e Luce France, racheté par Octopus Energy) fournit un espace client web à `espace-client.eniplenitude.fr` permettant de consulter sa consommation électrique (semi-horaire pour les compteurs Linky communicants) et son contrat (offre, tarifs HP/HC, abonnement).

L'API interne est utilisée par le frontend mais n'est pas documentée publiquement. L'objectif est de la consommer pour exposer ces données dans Home Assistant en tant qu'entités natives (sensors), avec intégration au **tableau énergie HA**.

## 2. Découvertes techniques (phase d'investigation)

### 2.1 Architecture Plenitude

| Couche | Domaine | Techno |
|---|---|---|
| Portail frontend | `espace-client.eniplenitude.fr` | Next.js 13+ App Router |
| Auth portail | Même domaine | `better-auth` (cookie HttpOnly `__Secure-better-auth.session_token`, TTL 24h) |
| API métier (BFF tRPC) | `portal-api.eniplenitude.fr` | tRPC, auth via JWT Bearer |
| Backend métier | `api.plenitudefr-kraken.energy/v1/graphql/` | **Kraken Tech** (plateforme SaaS Octopus Energy), GraphQL, JWT RS256 |

### 2.2 Authentification

Deux systèmes coexistent, alimentés par les mêmes credentials email + mot de passe :

**Kraken** (pour la conso) :
- `POST https://api.plenitudefr-kraken.energy/v1/graphql/`
- Mutation `obtainKrakenToken(input: {email, password})` → `{ token, refreshToken, refreshExpiresIn, payload }`
- TTL access token : 1h (`exp` dans le JWT)
- **Refresh** : la même mutation accepte `obtainKrakenToken(input: {refreshToken})` → nouveau couple `{token, refreshToken, refreshExpiresIn}`. Pattern OAuth2 standard. Le `refreshExpiresIn` est observable (TTL probablement long, à confirmer à l'impl).
- **Révocation** : mutation `invalidateRefreshToken(input)` disponible (à appeler au unload du `ConfigEntry`).
- CORS ouvert : appel direct possible depuis n'importe quelle origine.
- Format JWT : `sub: "krakenaccount-user:<id>"`, `gty: "EMAIL-AND-PASSWORD"`, `origIat` (login initial) reste constant après refresh.

**Portail better-auth** (pour les tarifs) :
- `POST https://espace-client.eniplenitude.fr/auth/connexion`
- Form `multipart/form-data` avec `_1_email` et `_1_password`
- Réponse : `Set-Cookie: __Secure-better-auth.session_token=...` (TTL 24h)
- Pas de captcha, pas de bot protection bloquante

### 2.3 Données disponibles

**Conso (kWh, HP/HC)** : `GET https://portal-api.eniplenitude.fr/api/trpc/b2c.consumptions.getBySiteIds?input=<encoded JSON>` avec header `Authorization: Bearer <JWT Kraken>`. Granularités supportées via `groupBy` : `HALF_HOUR`, `day`, `month`. Renvoie kWh totaux + breakdown HP/HC par interval.

**Tarifs unitaires (€/kWh HP/HC, abonnement)** :
- Pas exposés en JSON structuré côté Kraken (le champ `tariffGrid` ne renvoie qu'une URL S3 signée vers un PDF).
- **Exposés en JSON dans le HTML de `/contrat`** (payload React Server Component). Structure observée :
```json
{
  "agreedFrom": "2025-04-09T07:16:39Z",
  "endAt": "2027-05-24T22:00:00Z",
  "standingRate": {
    "pricePerUnit": 16176,
    "pricePerUnitWithTaxes": 21201.48
  },
  "consumptionRates": [
    {
      "energyUseTimeSlot": "PEAK",
      "timeSlots": [{"startAt": "07:30:00", "endAt": "23:30:00"}],
      "pricePerUnit": 14.51,
      "pricePerUnitWithTaxes": 21.114
    },
    {"energyUseTimeSlot": "OFF_PEAK", "timeSlots": [...], ...}
  ]
}
```

**Coûts (€) par interval** : champs `usageCost`/`netAmount` existent au schéma GraphQL Kraken mais **non observés peuplés** dans les réponses. Le coût sera donc **calculé côté HA** (kWh × tarif).

## 3. Approche retenue

**Principe directeur : pragmatisme avec source unique.** Le backend de vérité est Kraken Tech ; tout passe par lui in fine. Le portail Plenitude (Next.js + BFF tRPC) est un wrapper de présentation maintenu par Plenitude pour son frontend. On peut consommer Kraken via deux voies : directement (GraphQL pur) ou via le BFF (JSON simplifié). Le choix se fait par cas d'usage.

- **Conso** récupérée via **BFF tRPC** `portal-api.eniplenitude.fr/api/trpc/b2c.consumptions.getBySiteIds`, authentifié avec le JWT Kraken (`obtainKrakenToken`).
  - *Pivot vs design initial* : la query Kraken directe `detailedMeasures` exige `customerFirstName`, `customerLastName`, `prmId`, et 4 enums (`measureType`, `physicalQuantity`, `accessLevel`, `measureInterval`) parce qu'elle est conçue pour formaliser des demandes d'accès Enedis officielles. Le BFF Plenitude encapsule cette complexité et expose la conso semi-horaire HP/HC en JSON propre. Le BFF reste alimenté par Kraken — c'est juste une couche de présentation.
  - *Format observé* : `{siteId, electricity: {consumptions: [{value, readAt, unit, details: [{type: "HP"|"HC", value}]}], totalBase, totalHP, totalHC}}`.
  - *Fallback documenté* : si Plenitude change le format du BFF, migration possible vers `detailedMeasures` direct (plus de code, schéma Kraken stable).
- **Tarifs** récupérés via parsing du JSON RSC embarqué dans le HTML de `/contrat` (auth cookie portail).
- **Login portail** : Plenitude n'expose PAS un endpoint better-auth standard (`/api/auth/sign-in/email` répond `EMAIL_AND_PASSWORD_IS_NOT_ENABLED`). On reproduit le **Next.js Server Action** observé au login natif : `POST /auth/connexion` multipart avec header `next-action: <hash>`. Le hash change à chaque déploiement Plenitude, donc on le **scrape depuis le HTML de `/auth/connexion` à chaque login** (pas de hash hard-codé).
- **Coûts** calculés côté HA à partir des deux.

Approches écartées :
- Docker / scraping browser : auth trop simple pour le justifier.
- Parsing PDF de `tariffGrid` : fragile.
- Saisie manuelle des tarifs uniquement : moins bonne UX (fallback en mode dégradé seulement).

## 4. Architecture cible

### 4.1 Arborescence

```
custom_components/plenitude/
├── __init__.py              # setup/unload de l'integration
├── manifest.json            # version, dependencies, codeowners, iot_class
├── const.py                 # DOMAIN, URLs, défauts
├── api/
│   ├── __init__.py
│   ├── kraken.py            # PlenitudeKrakenClient (login, refresh, getConsumptions)
│   └── portal.py            # PlenitudePortalClient (login better-auth, fetch /contrat, parse RSC)
├── coordinator.py           # PlenitudeCoordinator (DataUpdateCoordinator)
├── config_flow.py           # UI HA: credentials → test → preview tarifs → save
├── sensor.py                # SensorEntity definitions
├── strings.json             # textes UI (fr de base, en aussi)
└── translations/
    ├── fr.json
    └── en.json
```

### 4.2 Principes de découplage

- `api/kraken.py` et `api/portal.py` n'importent rien de `homeassistant.*` — pur Python + `aiohttp`. Permet réutilisation hors HA (CLI, tests unitaires standalone).
- `coordinator.py` orchestre les deux clients et gère le cycle de vie des tokens.
- `sensor.py` ne contient que le mapping coordinator → entités HA.

## 5. Flow d'authentification

### Login initial (config flow)

1. UI HA demande email + mot de passe (champs `vol.Required(CONF_EMAIL)`, `vol.Required(CONF_PASSWORD)` avec `selector` de type password).
2. Test en parallèle des deux logins :
   - `PlenitudeKrakenClient.login(email, password)` → mutation `obtainKrakenToken` → récupère `{token, refreshToken, refreshExpiresIn}`
   - `PlenitudePortalClient.login(email, password)` → cookie session better-auth
3. Si l'un des deux échoue → afficher erreur explicite (`invalid_auth` / `cannot_connect`).
4. Si OK, appel `PlenitudePortalClient.fetch_contract()` → parse JSON RSC → extraction tarifs HP TTC, HC TTC, abo TTC, plages HP/HC, `site_id`, PDL.
5. Affichage à l'utilisateur d'un step de confirmation avec les tarifs détectés (éditables).
6. Création du `ConfigEntry` avec : **uniquement `refreshToken` + cookie better-auth + tarifs + site_id + intervalle de polling (default 1h)**. **Le mot de passe est jeté immédiatement après ce step**, jamais persisté.

### Refresh tokens (runtime)

- **JWT Kraken (access token)** : refresh proactif 5 min avant l'`exp` (lu depuis le JWT). Le coordinator appelle `obtainKrakenToken(input: {refreshToken})` qui renvoie un nouveau `{token, refreshToken, refreshExpiresIn}`. Le refresh token retourné remplace l'ancien (rotation côté Kraken probable, à observer à l'impl).
- **Refresh token Kraken** : durée observable via `refreshExpiresIn`. Quand il approche de l'expiration → notification HA "ré-authentification Plenitude requise". L'utilisateur ouvre l'options flow et re-saisit son mot de passe une fois.
- **Cookie better-auth (portail)** : refresh à J-1 avant expiration (TTL 24h observé). Refresh au démarrage de HA ou lors d'un fetch tarifs si cookie absent/expiré. **Sans mot de passe en stock**, le refresh nécessite un re-login. Solution : on appelle `PlenitudePortalClient.login(email, password)` uniquement au config flow / options flow ; entre les deux on étend la durée de vie du cookie en faisant des appels périodiques au portail (touch session). Si le cookie tombe → fallback gracieux : tarifs gardés en cache, prompt l'utilisateur quand on a besoin de re-fetch.

Stratégie en cas d'échec :
- 401 sur Kraken (access token expiré + refresh raté) → invalidation refresh token + notification HA persistante "ré-authentification requise". 3 retries du refresh avec backoff avant déclenchement.
- 401 sur portail → tentative de refresh cookie (touch session). Si échec → tarifs stale en cache, conso continue d'être fetchée. Notification non-bloquante.
- Au `async_unload_entry` du `ConfigEntry` : appel `invalidateRefreshToken` côté Kraken pour cleanup propre.

## 6. Flow de polling

Coordinator interval : configurable, default **1h**.

À chaque tick :

1. `_refresh_kraken_token_if_needed()` (refresh JWT proactif si < 5 min avant expiration)
2. `_fetch_consumption(group_by="HALF_HOUR")` via BFF tRPC (`GET portal-api.eniplenitude.fr/api/trpc/b2c.consumptions.getBySiteIds?input=<encoded>` avec header `Authorization: Bearer <JWT Kraken>`)
3. Mise à jour des sensors conso (kWh totaux, HP, HC, dernière relève)
4. Recalcul du coût : `cout_total = HP × tarif_HP + HC × tarif_HC + (abo_mensuel × jours_du_mois_écoulés / jours_du_mois)`
5. Tarifs eux-mêmes : refresh **1×/jour** (pas à chaque tick). Logique : `if last_tariff_refresh > 24h ago: portal.fetch_contract()`.

## 7. Entités HA exposées

Toutes ont `unique_id` basé sur `f"plenitude_{site_id}_{nom}"` pour multi-comptes.

### Conso

| `entity_id` (suffixe site_id omis) | unit | device_class | state_class | description |
|---|---|---|---|---|
| `sensor.plenitude_conso_totale_kwh` | kWh | energy | total_increasing | Conso totale cumulée (alimente tableau énergie HA) |
| `sensor.plenitude_conso_hp_kwh` | kWh | energy | total_increasing | Conso HP cumulée |
| `sensor.plenitude_conso_hc_kwh` | kWh | energy | total_increasing | Conso HC cumulée |
| `sensor.plenitude_derniere_releve` | — | timestamp | — | Date du dernier relevé compteur disponible |

### Coût (calculé côté HA)

| `entity_id` | unit | device_class | state_class | description |
|---|---|---|---|---|
| `sensor.plenitude_cout_total_eur` | EUR | monetary | total_increasing | Coût total cumulé (conso × tarif + abo prorata) |
| `sensor.plenitude_cout_hp_eur` | EUR | monetary | total_increasing | Coût HP cumulé |
| `sensor.plenitude_cout_hc_eur` | EUR | monetary | total_increasing | Coût HC cumulé |

### Tarifs (informationnels, peu de changement)

| `entity_id` | unit | device_class | description |
|---|---|---|---|
| `sensor.plenitude_tarif_hp_eur_kwh` | EUR/kWh | — | Tarif HP TTC |
| `sensor.plenitude_tarif_hc_eur_kwh` | EUR/kWh | — | Tarif HC TTC |
| `sensor.plenitude_abonnement_eur_mois` | EUR | monetary | Abonnement TTC mensuel |

## 8. Résilience et gestion d'erreurs

| Scénario | Comportement |
|---|---|
| Kraken renvoie 5xx | Backoff exponentiel (3 retries: 5s, 30s, 2min) puis statut `unavailable` sur les sensors conso |
| Cookie portail expiré | Re-login transparent, tarifs gardés en cache pendant le refresh |
| Parsing JSON RSC échoue | Garde les tarifs actuels en cache, log warning, retry au refresh suivant (1×/jour). Si jamais résolu : fallback sur saisie manuelle via options flow HA |
| Credentials invalides (les deux échec) | Notification HA persistante "Ré-authentification Plenitude requise", `ConfigEntry` passé en `state=SETUP_ERROR` |
| Compteur sans relève récente | `last_reset` non mis à jour, sensors gardent dernière valeur, pas de crash |
| Plenitude change le format RSC | Parsing fail → log warning + tarifs stale. Doit être détecté par des **tests unitaires sur fixtures HTML** (CI) |

## 9. Sécurité

### Stockage credentials

- **Mot de passe jamais persisté** après le config flow. Utilisé uniquement pour obtenir le `refreshToken` Kraken et le cookie better-auth.
- **Refresh token Kraken** stocké dans `ConfigEntry.data` (chiffré au repos si HA storage encryption activée).
- **Cookie better-auth** stocké en mémoire process uniquement, jamais sur disque (re-login automatique si tombé).
- JWT access tokens jamais persistés, mémoire process uniquement.

### Posture Kraken (validée en investigation)

- Test de **pen-test passif IDOR** effectué avec accountNumbers/agreementIds fictifs (`A-00000000`, `A-FFFFFFFF`, `A-DEADBEEF`, IDs entiers arbitraires). **Tous bloqués** par `KT-CT-1111 "Unauthorized"` côté Kraken.
- Le composant ne peut **pas** accéder aux données d'un autre utilisateur, même en cas de bug : Kraken impose la vérification côté serveur.
- Message d'erreur identique pour "compte inexistant" et "compte existant non autorisé" → pas d'énumération possible.

### Autres

- Aucun log de credentials, refresh tokens, JWT, ou cookies (logs structurés avec scrub explicite).
- HTTPS strict via `aiohttp.ClientSession` (pas de `verify_ssl=False`).
- En cas de bug critique nécessitant un dump, log au niveau `DEBUG` uniquement et avec tokens redacted.
- **User-Agent identifiable** dans tous les appels : `plenitude-ha/<version> (+<repo-url>)`. Permet à Plenitude de nous identifier proprement plutôt qu'imiter un navigateur.
- Mutation `invalidateRefreshToken` appelée au `async_unload_entry` pour cleanup côté Kraken.

## 10. Tests

### Tests unitaires (pytest, lancés en CI)

- `api/kraken.py` : login mock, refresh JWT, parsing réponses conso (fixtures JSON figées)
- `api/portal.py` : login mock, fetch HTML mock, **parsing JSON RSC sur fixtures HTML** (verrouille la robustesse face à un éventuel changement Plenitude)
- `coordinator.py` : orchestration des refresh tokens, calcul des coûts, gestion d'erreurs
- `sensor.py` : mapping coordinator data → SensorEntity attributes

### Test d'intégration manuel

- Install dans une instance HA dev → config flow complet → vérif des entités → vérif tableau énergie HA après quelques heures de polling.

## 11. Hors scope V1

- Gaz (Plenitude propose aussi le gaz : `gas` dans la réponse tRPC est `null` pour ce compte mais à ajouter si demande).
- Multi-compte (1 seul `ConfigEntry` par instance HA en V1, mais le code est prévu pour le supporter via `unique_id` par site).
- Modification du contrat depuis HA (lecture seule).
- Notifications proactives (dépassement de consommation, etc.).
- Tarifs variables type Tempo (l'offre actuelle est fixe ; à étudier si offre concernée).

## 12. Risques connus

| Risque | Impact | Mitigation |
|---|---|---|
| Plenitude change le format JSON RSC | Tarifs deviennent stale, sensors coût figés | Tests sur fixtures + fallback saisie manuelle |
| Plenitude renforce l'auth (captcha, MFA) | Login casse | Diagnostic Sentry, communication utilisateurs, fallback documentation |
| Rate limiting Kraken (vu `x-ratelimit-limit: 100`) | Polling trop agressif bloqué | Default polling 1h largement sous la limite ; minimum configurable 15 min |
| Kraken rotation des endpoints / domaines | Connexion casse | Config domaine externalisée dans `const.py`, possible config avancée |

## 13. Critères d'acceptance V1

0. La conso est récupérée via le BFF tRPC `portal-api.eniplenitude.fr` (authentifié avec le JWT Kraken). Le code reste structuré pour permettre une migration vers Kraken `detailedMeasures` direct si nécessaire.
1. À l'install, un utilisateur Plenitude FR avec compteur Linky communicant peut s'authentifier en saisissant email + mot de passe.
2. Les tarifs HP/HC et abonnement sont auto-détectés et affichés (éditables) avant validation.
3. Après install, au moins les sensors `conso_totale_kwh`, `cout_total_eur`, `derniere_releve` apparaissent et se mettent à jour.
4. Le sensor `conso_totale_kwh` est utilisable dans le tableau énergie HA (graphe quotidien correct).
5. Le sensor `cout_total_eur` est utilisable dans le tableau énergie HA en mode coût.
6. Le composant survit à un redémarrage HA sans perte de données ni re-authentification.
7. Si le mot de passe change côté Plenitude, l'utilisateur reçoit une notification HA actionnable.
8. La documentation HACS (`README.md`) explique l'install, les variables d'env optionnelles, et limitations connues.

## 14. Stack technique

- Python 3.12+ (aligné HA 2024.x+)
- `aiohttp` (déjà disponible dans HA core)
- `voluptuous` pour config flow (standard HA)
- Pas de dépendance externe additionnelle (Kraken GraphQL en JSON brut, parsing HTML via regex/`json` natif sur le payload RSC isolé)
- `pytest` + `pytest-asyncio` + `aioresponses` pour tests
