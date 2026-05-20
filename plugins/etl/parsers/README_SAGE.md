# Pipeline ETL REPFI — support des formats Sage (.pnm / .pnc)

Cette documentation décrit l'extension du DAG `etl_comptable_clickhouse` pour
supporter les exports texte largeur fixe de **Sage 100 Compta** en complément
des fichiers Excel.

---

## 1. Vue d'ensemble

Le pipeline REPFI ingère **4 fichiers obligatoires** par batch. Deux d'entre
eux acceptent désormais un format alternatif :

| Fichier         | Formats acceptés          | Détection                |
| --------------- | ------------------------- | ------------------------ |
| `plan_comptes`  | Excel (`.xlsx`/`.xls`)    | extension                |
| `code_journal`  | Excel (`.xlsx`/`.xls`)    | extension                |
| `plan_tiers`    | Excel **OU** `.pnc` Sage  | extension                |
| `grand_livre`   | Excel **OU** `.pnm` Sage  | extension                |

La détection est purement basée sur l'extension du fichier déposé dans S3.
Toute combinaison non autorisée (ex: `.pnm` placé dans le dossier
`PLAN_COMPTES`) fait échouer le DAG dès la phase de validation, avant tout
traitement.

Implémentation : [`plugins/etl/format_detect.py`](../format_detect.py).

---

## 2. Format `.pnm` — Grand Livre Sage

Fichier texte à **largeur fixe**, encodage **CP1252**, terminateur **CRLF**.
La première ligne contient le nom de la société (entité). Chaque ligne
suivante représente une écriture comptable.

### Positions des champs (validées sur fichier réel 2 333 écritures)

| Slice       | Largeur | Champ            | Exemple                  |
| ----------- | ------- | ---------------- | ------------------------ |
| `[0:3]`     | 3       | code_journal     | `ACH`                    |
| `[3:9]`     | 6       | date (JJMMAA)    | `110125`                 |
| `[9:11]`    | 2       | type_piece       | `FF`                     |
| `[11:24]`   | 13      | compte_général   | `401100       `          |
| `[24:25]`   | 1       | marqueur_tiers   | `X` ou ` `               |
| `[25:38]`   | 13      | compte_tiers     | `40100SO      `          |
| `[38:50]`   | 12      | référence_pièce  | `590         `           |
| `[51:76]`   | 25      | libellé          | `CONST FRAIS GESTION ...`|
| `[77:83]`   | 6       | date_échéance    | `110125` ou vide         |
| `[83:84]`   | 1       | sens             | `D` ou `C`               |
| `[84:104]`  | 20      | montant          | `              120000`   |
| `[104:105]` | 1       | type_écriture    | `N`                      |
| `[105:110]` | 5       | num_ligne_sage   | `   33`                  |

### Montants

Les montants sont stockés en **unités entières** (le FCFA n'a pas de
sous-unité). Pour des devises avec décimales implicites (EUR/USD), il faudra
diviser par 100 — non géré dans la V1 (le pipeline est codé pour XOF).

### Parser

[`plugins/etl/parsers/sage_pnm.py`](sage_pnm.py) — `parse_sage_pnm(file_path,
client_id, batch_id, period_start=None, period_end=None)`.

Sortie alignée sur `parse_grand_livre` Excel (tuple à 16 colonnes), ce qui
permet de réutiliser `enrich_grand_livre` et `upsert_grand_livre` sans
changement.

---

## 3. Format `.pnc` — Plan Tiers Sage

Texte largeur fixe, CP1252, CRLF. Première ligne = nom de société.

| Slice     | Largeur | Champ                       |
| --------- | ------- | --------------------------- |
| `[0:13]`  | 13      | code_tiers                  |
| `[13:37]` | 24      | nom_tiers                   |
| `[37:50]` | 13      | code_tiers (rappel, ignoré) |
| `[50:62]` | 12      | compte_général_rattachement |

### Déduction du type (Client / Fournisseur / Autre)

Le `.pnc` ne contient pas explicitement le type. Il est déduit de la racine
du compte de rattachement (identique en PCG et SYSCOHADA) :

- `411x...` → **Client**
- `401x...` → **Fournisseur**
- toute autre racine → **Autre**

Les doublons sur `code_tiers` sont automatiquement ignorés.

Parser : [`plugins/etl/parsers/sage_pnc.py`](sage_pnc.py).

---

## 4. Procédure d'export depuis Sage 100 Compta

### Grand Livre (`.pnm`)

1. Menu **Fichier** → **Exporter**
2. Choisir le format **Trésorerie Sage**
3. Sélectionner la période souhaitée
4. Sage génère un fichier `.pnm` (par défaut le nom commence par les
   initiales de la société)
5. Déposer ce fichier dans le dossier S3 `GRAND_LIVRE/` du batch

### Plan Tiers (`.pnc`)

1. Menu **Fichier** → **Exporter**
2. Choisir le format **Plan tiers auxiliaire**
3. Sage génère un fichier `.pnc`
4. Déposer dans `PLAN_TIERS/`

### Les 2 autres fichiers (toujours Excel)

- `PLAN_COMPTES/` : export Excel standard depuis Sage
- `CODE_JOURNAL/` : export Excel standard depuis Sage

---

## 5. Mapping PCG français → SYSCOHADA

Sage peut être paramétré sur le **Plan Comptable Général français (PCG)** ou
sur le **SYSCOHADA Révisé** (Afrique francophone). REPFI travaille en
SYSCOHADA — le pipeline applique donc un **mapping automatique** si la source
est en PCG.

### Détection automatique du plan source

Heuristique basée sur les comptes financiers (très discriminants) :

- Présence de `512` (banque PCG) ou `531` (caisse PCG) → **PCG**
- Présence de `521` (banque SYSCO) ou `571` (caisse SYSCO) → **SYSCOHADA**
- Aucun marqueur ou marqueurs mixtes → **UNKNOWN** (mapping non appliqué)

Implémentation : `detect_plan_source()` dans
[`plugins/etl/mapping/pcg_syscohada.py`](../mapping/pcg_syscohada.py).

### Table de mapping (en dur)

~37 mappings critiques sont définis dans
[`plugins/clickhouse/config.py`](../../clickhouse/config.py) sous
`PCG_SYSCOHADA_MAPPING` : trésorerie, achats, ventes, personnel, TVA, capital,
immobilisations, charges/produits financiers, HAO, tiers, stocks, dotations.

### Stratégie de lookup

Pour chaque compte PCG, dans l'ordre :

1. **Lookup exact** sur le numéro complet (`mapping_status = 'mapped'`)
2. **Fallback racine 3 chiffres**, suffixe conservé (`'fallback_racine'`)
   - Exemple : `512100` (PCG) → racine `512` → `521` + suffixe `100` = `521100`
3. **Fallback racine 2 chiffres**
4. Sinon : compte PCG conservé tel quel (`mapping_status = 'unmapped'` —
   warning loggé, batch non rejeté)

### Cohérence inter-fichiers

Si le `grand_livre` est détecté en PCG mais que le `plan_comptes` est en
SYSCOHADA (ou inverse), le DAG fail explicitement avant insertion :

```
ValueError: Incohérence de plan comptable détectée:
plan_compte = SYSCOHADA, grand_livre = PCG.
Tous les fichiers d'un même batch doivent être dans le même plan.
```

### Traçabilité dans ClickHouse

3 colonnes ajoutées à la table `grand_livre` :

| Colonne              | Type   | Sens                                                |
| -------------------- | ------ | --------------------------------------------------- |
| `compte_pcg_origine` | String | Compte PCG d'origine (vide si source SYSCOHADA)     |
| `is_hao`             | UInt8  | 1 si Hors Activités Ordinaires (classe 8 SYSCO)     |
| `mapping_status`     | String | `none`/`mapped`/`fallback_racine`/`unmapped`        |

Les valeurs par défaut s'appliquent automatiquement aux batchs en SYSCOHADA
natif (aucun mapping).

---

## 6. Validations bloquantes

Le DAG échoue avant toute insertion ClickHouse si l'une des règles suivantes
est violée :

### 6.1 Format autorisé par type de fichier

`plan_comptes` et `code_journal` doivent obligatoirement être en Excel. Un
`.pnm` ou `.pnc` mal rangé déclenche un fail dès la phase `download_files`.

### 6.2 Équilibre comptable

`sum(debit) == sum(credit)` au niveau du grand livre complet. Sinon :

```
ValueError: Grand Livre déséquilibré: Débit=X.XX ≠ Crédit=Y.YY (écart=Z.ZZ)
```

### 6.3 Période

Toute transaction dont la `date_ecriture` sort de
`[comptable_periods.periodStart, comptable_periods.periodEnd]` fait échouer
le DAG **au premier hors-période détecté**, avec un message normé identique
pour les deux formats :

```
Ligne 2: date 2025-01-11 hors période [2025-06-01, 2025-06-30]
(journal ACH, compte 401100)
```

**Exception** : les journaux des À-Nouveaux (`RAN`, `AN`) sont exemptés —
leurs dates correspondent à la reprise du bilan N-1, normalement antérieures
à la période courante.

### 6.4 Cohérence de plan inter-fichiers

Voir section 5 ci-dessus.

---

## 7. Architecture du pipeline (résumé)

```
┌────────────────────────────────────────────────────────────────────┐
│  Trigger : app Next.js (REPFI) → Airflow API                       │
│  Params  : client_id, batch_id, s3_prefix                          │
└─────────────────────────────┬──────────────────────────────────────┘
                              ▼
                ┌─────────────────────────────┐
                │   task_download_files       │
                │   - DL depuis S3            │
                │   - validate présence       │
                │   - detect_format / valider │
                │   - création DB ClickHouse  │
                └──────────────┬──────────────┘
                               ▼
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ process_plan_    │  │ process_code_    │  │ process_plan_    │
│ compte           │  │ journal          │  │ tiers            │
│ - détecte plan   │  │  (Excel)         │  │  (Excel ou .pnc) │
│ - mappe si PCG   │  │                  │  │                  │
└────────┬─────────┘  └────────┬─────────┘  └────────┬─────────┘
         └──────────────────────┼──────────────────────┘
                                ▼
                ┌─────────────────────────────────┐
                │   task_process_grand_livre      │
                │   - Excel ou .pnm Sage          │
                │   - valide période + équilibre  │
                │   - valide cohérence vs plan    │
                │   - enrichit + mappe si PCG     │
                │   - upsert grand_livre          │
                └──────────────┬──────────────────┘
                               ▼
                ┌──────────────────────────────┐
                │   task_export_excel          │
                │   - Excel enrichi → S3       │
                │   - enregistrement Postgres  │
                └──────────────┬───────────────┘
                               ▼
                ┌──────────────────────────────┐
                │   task_finalize / status      │
                └───────────────────────────────┘
```

---

## 8. Tests

Suite pytest dans [`tests/`](../../../tests/). 70 tests couvrent les parsers,
le mapping, la détection de format, et l'enrichissement (avec mock du
ClickHouseManager).

```bash
pip install pytest pandas openpyxl
python -m pytest
```

Les fichiers `.pnm` / `.pnc` de test sont **générés à la volée** dans
`tmp_path` (pas de fixtures binaires commitées).

---

## 9. Limites connues / V2

- **Devise** : XOF (FCFA) en dur. Pour EUR/USD il faudra diviser les montants
  par 100 et ajouter une colonne `devise` côté ClickHouse.
- **Idempotence** : assurée via le pattern `ALTER DELETE WHERE batch_id` puis
  `INSERT` (pas de hash de fichier en base). Re-run = overwrite propre.
- **Lecture en mémoire** : suffisante jusqu'à ~100 Mo. Au-delà, prévoir un
  parsing en streaming.
- **Migration `comptable_periods.error_message`** : pas encore faite. Pour
  l'instant les erreurs ne remontent qu'en `status='FAILED'` + logs Airflow.
- **Mapping PCG→SYSCO** : 37 entrées critiques. À enrichir selon les cas
  réels rencontrés.
- **Tests d'intégration** : pas de test ClickHouse réel (idempotence DAG,
  upserts) — couverts implicitement par le pattern existant.
