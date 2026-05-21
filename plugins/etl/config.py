"""
Configuration ETL pour REPFI
"""
import os
from datetime import timedelta

# ========================================
# CONFIGURATION AIRFLOW
# ========================================
DEFAULT_ARGS = {
    'owner': 'envol',
    # retries=0 : en cas d'échec d'une tâche, on bascule immédiatement en
    # FAILED sans attendre un retry. L'utilisateur peut relancer manuellement
    # depuis le front via le bouton "Relancer le traitement".
    'retries': 0,
    'retry_delay': timedelta(seconds=30),
}

# ========================================
# CONFIGURATION S3
# ========================================
S3_CONFIG = {
    'bucket_name': os.getenv('S3_BUCKET_NAME', 'repfi'),
    'region': os.getenv('AWS_REGION', 'eu-west-3'),
}

# ========================================
# CONFIGURATION POSTGRESQL
# ========================================
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://postgres:root@host.docker.internal:5432/repfi_db')

# ========================================
# TYPES DE FICHIERS ATTENDUS (format 4 fichiers)
# ========================================
FILE_TYPES = [
    'plan_comptes',
    'code_journal',
    'plan_tiers',
    'grand_livre',  # Fichier unique contenant comptes + tiers
]

# ========================================
# MAPPING DES DOSSIERS S3 → TYPE DE FICHIER
# ========================================
FOLDER_TO_FILE_TYPE = {
    'PLAN_COMPTES': 'plan_comptes',
    'PLAN_COMPTABLE': 'plan_comptes',
    'CODE_JOURNAL': 'code_journal',
    'CODES_JOURNAUX': 'code_journal',
    'PLAN_TIERS': 'plan_tiers',
    'GRAND_LIVRE': 'grand_livre',
    'GRAND_LIVRE_COMPTABLE': 'grand_livre',
    'GRAND_LIVRE_COMPTES': 'grand_livre',
}

# ========================================
# STATUS ETL
# ========================================
class ETLStatus:
    PENDING = 'PENDING'
    VALIDATING = 'VALIDATING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
