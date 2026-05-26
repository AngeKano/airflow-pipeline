"""
Gestion de la table PLE (Plan Liasse Export) - Mapping Racine → Rubrique.

Cette table couvre désormais deux référentiels SYSCOHADA dans la même
structure (différenciés par type_rubrique) :
    - 'PL'    : rubriques compte de résultat (RA-RS, TA-TO)
    - 'BILAN' : rubriques bilan (AD-DZ)

Filtres et exclusions :
    - solde_filter ∈ {'', 'debit', 'credit'} : pour les comptes mixtes
      (ex: classe 52 — incluse en BS si solde débiteur, en DQ si créditeur).
    - exclusions : liste de racines à exclure (ex: BI inclut "41" sauf "419").
"""
from typing import List, Tuple

from clickhouse.base import ClickHouseBase
from clickhouse.config import (
    PLE_MAPPING_DATA,
    BILAN_MAPPING_DATA,
    BILAN_COMPOSITION,
    BILAN_LABELS,
    BILAN_SUBDIVISIONS,
)


class PLEManager(ClickHouseBase):
    """Gestion de la table PLE (P&L + Bilan) pour le mapping des rubriques."""

    def create_table(self, client_id: str):
        db_name = self._get_db_name(client_id)

        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.ple (
                racine String,
                rubrique String,
                nb_racine UInt8,
                type_rubrique LowCardinality(String) DEFAULT 'PL',
                solde_filter LowCardinality(String) DEFAULT '',
                exclusions String DEFAULT '',
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (type_rubrique, racine, nb_racine)
            PRIMARY KEY (type_rubrique, racine, nb_racine)
        """)
        # Auto-migration pour les bases existantes (avant l'ajout de type_rubrique)
        self._migrate_schema(db_name)
        print(f"  ✓ Table {db_name}.ple prête")

    def _migrate_schema(self, db_name: str):
        """Ajoute les colonnes manquantes aux tables ple créées avant l'évolution Bilan."""
        required = [
            ('type_rubrique', "LowCardinality(String) DEFAULT 'PL'"),
            ('solde_filter', "LowCardinality(String) DEFAULT ''"),
            ('exclusions', "String DEFAULT ''"),
        ]
        try:
            existing = self._execute(f"""
                SELECT name FROM system.columns
                WHERE database = '{db_name}' AND table = 'ple'
            """)
            existing_cols = {row[0] for row in existing}
        except Exception:
            existing_cols = set()

        for col_name, col_def in required:
            if col_name not in existing_cols:
                try:
                    self._execute(
                        f"ALTER TABLE {db_name}.ple ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
                    )
                    print(f"    + Colonne 'ple.{col_name}' ajoutée")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"    ⚠️ Erreur ajout colonne {col_name}: {e}")

    def populate(self, client_id: str):
        """Repopule la table ple avec P&L + Bilan."""
        db_name = self._get_db_name(client_id)

        # Construction des tuples enrichis
        # Format final : (racine, rubrique, nb_racine, type_rubrique, solde_filter, exclusions_csv)
        rows: List[Tuple] = []

        # P&L : 876 entrées atomiques
        for racine, rubrique, nb_racine in PLE_MAPPING_DATA:
            rows.append((racine, rubrique, nb_racine, 'PL', '', ''))

        # Bilan : mapping atomique
        for racine, code_bilan, nb_racine, solde_filter, exclusions in BILAN_MAPPING_DATA:
            exclusions_csv = ','.join(exclusions) if exclusions else ''
            rows.append((racine, code_bilan, nb_racine, 'BILAN', solde_filter, exclusions_csv))

        self._execute(f"TRUNCATE TABLE {db_name}.ple")
        self._execute(
            f"""INSERT INTO {db_name}.ple
                (racine, rubrique, nb_racine, type_rubrique, solde_filter, exclusions)
                VALUES""",
            rows,
        )
        self._execute(f"OPTIMIZE TABLE {db_name}.ple FINAL")

        nb_pl = len(PLE_MAPPING_DATA)
        nb_bilan = len(BILAN_MAPPING_DATA)
        print(f"  ✓ Table {db_name}.ple alimentée ({nb_pl} PL + {nb_bilan} Bilan = {len(rows)} lignes)")

    def create_and_populate(self, client_id: str):
        self.create_table(client_id)
        self.populate(client_id)

    # ------------------------------------------------------------------
    # Lookup P&L (rubrique compte de résultat)
    # ------------------------------------------------------------------
    def get_rubrique(self, client_id: str, compte: str) -> str:
        """
        Retourne la rubrique P&L pour un compte.
        Lookup hiérarchique : compte exact (6) → racine 4 → racine 3.
        """
        return self._lookup_rubrique(client_id, compte, type_rubrique='PL')

    # ------------------------------------------------------------------
    # Lookup Bilan (avec filtres soldes + exclusions)
    # ------------------------------------------------------------------
    def get_bilan_rubrique(
        self,
        client_id: str,
        compte: str,
        solde_signed: float = 0.0,
    ) -> str:
        """
        Retourne la rubrique Bilan pour un compte.

        Args:
            compte : numéro de compte (ex: '521100').
            solde_signed : solde signé du compte (>0 = débiteur, <0 = créditeur).
                Nécessaire pour les rubriques avec filtre solde (ex: BS = 52 si solde débiteur).

        Stratégie :
        1. Cherche compte / racine en hiérarchique (6 → 4 → 3 → 2)
        2. Filtre par solde_filter (debit/credit) si présent
        3. Vérifie que le compte n'est pas dans les exclusions de la rubrique
        4. Renvoie le 1er match qui passe tous les filtres
        """
        return self._lookup_rubrique(
            client_id, compte, type_rubrique='BILAN', solde_signed=solde_signed,
        )

    # ------------------------------------------------------------------
    # Helper privé pour le lookup unifié
    # ------------------------------------------------------------------
    def _lookup_rubrique(
        self,
        client_id: str,
        compte: str,
        type_rubrique: str,
        solde_signed: float = 0.0,
    ) -> str:
        db_name = self._get_db_name(client_id)
        compte = (compte or '').strip()
        if not compte:
            return ''

        # Lookup hiérarchique du plus précis au plus large
        # Bilan ajoute le niveau 2 (ex: '41', '42') par rapport au P&L qui s'arrête à 3.
        levels = [6, 5, 4, 3, 2] if type_rubrique == 'BILAN' else [6, 4, 3]

        for nb_chars in levels:
            if len(compte) < nb_chars:
                continue
            racine = compte[:nb_chars]

            result = self._execute(f"""
                SELECT rubrique, solde_filter, exclusions
                FROM {db_name}.ple
                WHERE type_rubrique = %(type)s
                  AND racine = %(racine)s
                  AND nb_racine = %(nb)s
            """, {'type': type_rubrique, 'racine': racine, 'nb': nb_chars})

            for rubrique, solde_filter, exclusions_csv in result:
                # Vérifier les exclusions
                exclusions = [e.strip() for e in (exclusions_csv or '').split(',') if e.strip()]
                if any(compte.startswith(exc) for exc in exclusions):
                    continue
                # Vérifier le filtre solde
                if solde_filter == 'debit' and solde_signed < 0:
                    continue
                if solde_filter == 'credit' and solde_signed > 0:
                    continue
                return rubrique
        return ''

    def get_count(self, client_id: str) -> int:
        db_name = self._get_db_name(client_id)
        result = self._execute(f"SELECT count() FROM {db_name}.ple")
        return result[0][0]
