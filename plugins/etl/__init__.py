"""
Package ETL pour REPFI
Version 3.0 - Format 4 fichiers avec Grand Livre unifié
"""
from etl.config import (
    DEFAULT_ARGS,
    S3_CONFIG,
    DATABASE_URL,
    FILE_TYPES,
    ETLStatus,
)
from etl.postgres import (
    get_postgres_connection,
    update_etl_status,
    get_batch_info,
)
from etl.s3 import (
    get_s3_client,
    download_files_from_s3,
    validate_files,
    upload_file_to_s3,
    cleanup_local_files,
)
from etl.parsers import (
    parse_plan_compte,
    parse_code_journal,
    parse_plan_tiers,
    parse_grand_livre,
    parse_sage_pnm,
    parse_sage_pnc,
)
from etl.processors import (
    enrich_grand_livre,
    export_grand_livre_excel,
)
from etl.format_detect import (
    detect_format,
    validate_format,
    ALLOWED_FORMATS,
)
from etl.mapping import (
    map_compte,
    detect_plan_source,
)

__all__ = [
    # Config
    'DEFAULT_ARGS',
    'S3_CONFIG',
    'DATABASE_URL',
    'FILE_TYPES',
    'ETLStatus',
    # PostgreSQL
    'get_postgres_connection',
    'update_etl_status',
    'get_batch_info',
    # S3
    'get_s3_client',
    'download_files_from_s3',
    'validate_files',
    'upload_file_to_s3',
    'cleanup_local_files',
    # Parsers
    'parse_plan_compte',
    'parse_code_journal',
    'parse_plan_tiers',
    'parse_grand_livre',
    'parse_sage_pnm',
    'parse_sage_pnc',
    # Processors
    'enrich_grand_livre',
    'export_grand_livre_excel',
    # Format detection
    'detect_format',
    'validate_format',
    'ALLOWED_FORMATS',
    # Mapping comptable
    'map_compte',
    'detect_plan_source',
]

__version__ = '3.0.0'
