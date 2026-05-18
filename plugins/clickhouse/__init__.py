"""
Package ClickHouse pour REPFI
"""
from clickhouse.manager import ClickHouseManager
from clickhouse.config import CLICKHOUSE_CONFIG, PLE_MAPPING_DATA

__all__ = [
    'ClickHouseManager',
    'CLICKHOUSE_CONFIG',
    'PLE_MAPPING_DATA',
]

__version__ = '3.0.0'
