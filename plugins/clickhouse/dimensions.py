"""
Gestion des tables de dimension ClickHouse
"""
from typing import List, Tuple, Set
from clickhouse.base import ClickHouseBase
from clickhouse.config import DIMENSION_CONFIG


class DimensionManager(ClickHouseBase):
    """Gestion des tables de dimension"""

    def create_tables(self, client_id: str):
        """Crée les tables de dimension pour un client."""
        db_name = self._get_db_name(client_id)

        # Table Code Journal
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.code_journal (
                code_journal String,
                intitule String,
                type String,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (code_journal)
            PRIMARY KEY (code_journal)
        """)
        print(f"  ✓ Table {db_name}.code_journal prête")

        # Table Plan Comptable
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.plan_compte (
                compte String,
                type String,
                intitule_compte String,
                nature_compte String,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (compte)
            PRIMARY KEY (compte)
        """)
        print(f"  ✓ Table {db_name}.plan_compte prête")

        # Table Plan Tiers (simplifiée - 3 colonnes)
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.plan_tiers (
                compte_tiers String,
                type String,
                intitule_tiers String,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (compte_tiers)
            PRIMARY KEY (compte_tiers)
        """)
        print(f"  ✓ Table {db_name}.plan_tiers prête")

    def upsert(self, client_id: str, table_name: str, data: List[Tuple]):
        """Insère ou met à jour les données de dimension."""
        if not data:
            print(f"⚠️ Aucune donnée à insérer dans {table_name}")
            return

        db_name = self._get_db_name(client_id)

        config = DIMENSION_CONFIG.get(table_name)
        if not config:
            raise ValueError(f"Table inconnue: {table_name}")

        columns = config['columns']
        pk_column = config['pk_column']
        pk_index = config['pk_index']

        keys = [row[pk_index] for row in data]

        self._execute(f"""
            ALTER TABLE {db_name}.{table_name}
            DELETE WHERE {pk_column} IN %(keys)s
        """, {'keys': keys})

        query = f"INSERT INTO {db_name}.{table_name} {columns} VALUES"
        self._execute(query, data)

        self._execute(f"OPTIMIZE TABLE {db_name}.{table_name} FINAL")
        print(f"  → {len(data)} lignes upsert dans {db_name}.{table_name}")

    def get_count(self, client_id: str, table_name: str) -> int:
        db_name = self._get_db_name(client_id)
        result = self._execute(f"SELECT count() FROM {db_name}.{table_name}")
        return result[0][0]

    def get_intitule_compte(self, client_id: str, compte: str) -> str:
        """Récupère l'intitulé d'un compte."""
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT intitule_compte FROM {db_name}.plan_compte
            WHERE compte = %(compte)s
        """, {'compte': compte})
        return result[0][0] if result else ""

    def get_intitule_tiers(self, client_id: str, compte_tiers: str) -> str:
        """Récupère l'intitulé d'un tiers."""
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT intitule_tiers FROM {db_name}.plan_tiers
            WHERE compte_tiers = %(compte_tiers)s
        """, {'compte_tiers': compte_tiers})
        return result[0][0] if result else ""

    def get_type_tiers(self, client_id: str, compte_tiers: str) -> str:
        """Récupère le type d'un tiers (Client/Fournisseur)."""
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT type FROM {db_name}.plan_tiers
            WHERE compte_tiers = %(compte_tiers)s
        """, {'compte_tiers': compte_tiers})
        return result[0][0] if result else ""
