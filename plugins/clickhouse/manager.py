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
        # ple est un référentiel du client : jamais reconstruit, mapping par
        # défaut chargé uniquement si la table est vide (nouveau client).
        self.ple.ensure_table(client_id)

    def ensure_dimension_tables(self, client_id: str):
        """Crée la base et les référentiels (dimensions + ple) si besoin, sans
        toucher à grand_livre (utilisé par la mise à jour unitaire)."""
        db_name = self._get_db_name(client_id)
        self.client.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        self.dimensions.create_tables(client_id)
        self.ple.ensure_table(client_id)

    # Méthodes déléguées - Dimensions
    def upsert_dimension(self, client_id: str, table_name: str, data: List[Tuple]) -> dict:
        return self.dimensions.merge(client_id, table_name, data)

    def propagate_dimension(self, client_id: str, table_name: str, rows: List[Tuple]) -> int:
        return self.dimensions.propagate_to_grand_livre(client_id, table_name, rows)

    def get_dimension_count(self, client_id: str, table_name: str) -> int:
        return self.dimensions.get_count(client_id, table_name)

    def get_intitule_compte(self, client_id: str, compte: str) -> str:
        return self.dimensions.get_intitule_compte(client_id, compte)

    def get_intitule_tiers(self, client_id: str, compte_tiers: str) -> str:
        return self.dimensions.get_intitule_tiers(client_id, compte_tiers)

    def get_type_tiers(self, client_id: str, compte_tiers: str) -> str:
        return self.dimensions.get_type_tiers(client_id, compte_tiers)

    # Méthodes déléguées - PLE
    def load_ple_index(self, client_id: str):
        """Mapping ple du client en mémoire (PleIndex.classify pour classer un compte)."""
        return self.ple.load_index(client_id)

    def reclassify_grand_livre(self, client_id: str) -> dict:
        """Réapplique le mapping ple actuel à tout le grand livre (colonne rubrique seule)."""
        return self.grand_livre.reclassify(client_id, self.ple.load_index(client_id))

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
