"""
Classe de base pour la connexion ClickHouse
"""
from clickhouse_driver import Client
from clickhouse.config import CLICKHOUSE_CONFIG


class ClickHouseBase:
    """Classe de base avec connexion et utilitaires communs"""

    def __init__(self, client: Client = None):
        if client:
            self.client = client
            self._owns_client = False
        else:
            self.client = Client(**CLICKHOUSE_CONFIG)
            self._owns_client = True

    def _get_db_name(self, client_id: str) -> str:
        clean_id = client_id.replace('-', '_').lower()
        return f"repfi_{clean_id}"

    def _execute(self, query: str, params: dict = None, settings: dict = None):
        if params:
            return self.client.execute(query, params, settings=settings)
        return self.client.execute(query, settings=settings)

    def _table_exists(self, db_name: str, table: str) -> bool:
        result = self._execute(
            "SELECT count() FROM system.tables WHERE database = %(db)s AND name = %(t)s",
            {'db': db_name, 't': table},
        )
        return bool(result and result[0][0])

    def close(self):
        if self._owns_client:
            self.client.disconnect()
