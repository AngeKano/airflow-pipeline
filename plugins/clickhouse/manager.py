"""
ClickHouseManager - Façade principale pour REPFI
"""
from typing import List, Tuple, Optional
from clickhouse_driver import Client

from clickhouse.config import CLICKHOUSE_CONFIG
from clickhouse.dimensions import DimensionManager
from clickhouse.ple import PLEManager
from clickhouse.grand_livre import GrandLivreManager


class ClickHouseManager:
    """Gestionnaire ClickHouse pour REPFI - Multi-tenant"""

    def __init__(self):
        self.client = Client(**CLICKHOUSE_CONFIG)
        self.dimensions = DimensionManager(self.client)
        self.ple = PLEManager(self.client)
        self.grand_livre = GrandLivreManager(self.client)

    def _get_db_name(self, client_id: str) -> str:
        clean_id = client_id.replace('-', '_').lower()
        return f"repfi_{clean_id}"

    def create_client_database(self, client_id: str):
        """Crée toute l'infrastructure pour un nouveau client."""
        db_name = self._get_db_name(client_id)
        self.client.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        print(f"📁 Database '{db_name}' prête")

        self.dimensions.create_tables(client_id)
        self.grand_livre.create_table(client_id)
        self.ple.create_and_populate(client_id)

    # Méthodes déléguées - Dimensions
    def upsert_dimension(self, client_id: str, table_name: str, data: List[Tuple]):
        return self.dimensions.upsert(client_id, table_name, data)

    def get_dimension_count(self, client_id: str, table_name: str) -> int:
        return self.dimensions.get_count(client_id, table_name)

    def get_intitule_compte(self, client_id: str, compte: str) -> str:
        return self.dimensions.get_intitule_compte(client_id, compte)

    def get_intitule_tiers(self, client_id: str, compte_tiers: str) -> str:
        return self.dimensions.get_intitule_tiers(client_id, compte_tiers)

    def get_type_tiers(self, client_id: str, compte_tiers: str) -> str:
        return self.dimensions.get_type_tiers(client_id, compte_tiers)

    # Méthodes déléguées - PLE
    def get_rubrique(self, client_id: str, compte: str) -> str:
        return self.ple.get_rubrique(client_id, compte)

    # Méthodes déléguées - Grand Livre
    def upsert_grand_livre(self, client_id: str, data: List[Tuple], periode: str, batch_id: str):
        return self.grand_livre.upsert(client_id, data, periode, batch_id)

    def get_grand_livre_stats(self, client_id: str, periode: Optional[str] = None) -> dict:
        return self.grand_livre.get_stats(client_id, periode)

    def get_grand_livre_data(self, client_id: str, batch_id: str) -> List[Tuple]:
        return self.grand_livre.get_data(client_id, batch_id)

    def get_balance_par_rubrique(self, client_id: str, periode: str) -> List[dict]:
        return self.grand_livre.get_balance_par_rubrique(client_id, periode)

    def delete_batch(self, client_id: str, batch_id: str):
        self.grand_livre.delete_batch(client_id, batch_id)

    def close(self):
        self.client.disconnect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
