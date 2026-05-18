"""
Gestion de la table PLE (Plan Liasse Export) - Mapping Racine → Rubrique
"""
from clickhouse.base import ClickHouseBase
from clickhouse.config import PLE_MAPPING_DATA


class PLEManager(ClickHouseBase):
    """Gestion de la table PLE pour le mapping des rubriques comptables"""

    def create_table(self, client_id: str):
        db_name = self._get_db_name(client_id)

        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.ple (
                racine String,
                rubrique String,
                nb_racine UInt8,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (racine)
            PRIMARY KEY (racine)
        """)
        print(f"  ✓ Table {db_name}.ple prête")

    def populate(self, client_id: str):
        db_name = self._get_db_name(client_id)

        self._execute(f"TRUNCATE TABLE {db_name}.ple")
        self._execute(
            f"INSERT INTO {db_name}.ple (racine, rubrique, nb_racine) VALUES",
            PLE_MAPPING_DATA
        )
        self._execute(f"OPTIMIZE TABLE {db_name}.ple FINAL")
        print(f"  ✓ Table {db_name}.ple alimentée ({len(PLE_MAPPING_DATA)} lignes)")

    def create_and_populate(self, client_id: str):
        self.create_table(client_id)
        self.populate(client_id)

    def get_rubrique(self, client_id: str, compte: str) -> str:
        """Retourne la rubrique pour un compte donné."""
        db_name = self._get_db_name(client_id)

        for nb_chars in [4, 3]:
            racine = compte[:nb_chars]
            result = self._execute(f"""
                SELECT rubrique FROM {db_name}.ple 
                WHERE racine = %(racine)s AND nb_racine = %(nb)s
            """, {'racine': racine, 'nb': nb_chars})
            if result:
                return result[0][0]
        return ''

    def get_count(self, client_id: str) -> int:
        db_name = self._get_db_name(client_id)
        result = self._execute(f"SELECT count() FROM {db_name}.ple")
        return result[0][0]
