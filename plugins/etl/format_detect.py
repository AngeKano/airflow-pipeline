"""
Détection du format d'un fichier comptable d'après son extension.

Stratégie : extension du fichier S3 / local path.
    .xlsx, .xls  → 'excel'
    .pnm         → 'sage_pnm'  (Grand Livre Sage)
    .pnc         → 'sage_pnc'  (Plan Tiers Sage)
    autre        → 'unknown'

Le mapping file_type → formats autorisés impose les règles métier :
    plan_comptes  : Excel uniquement
    code_journal  : Excel uniquement
    plan_tiers    : Excel OU sage_pnc
    grand_livre   : Excel OU sage_pnm
"""
import os
from typing import Literal

FileFormat = Literal['excel', 'sage_pnm', 'sage_pnc', 'unknown']


# Formats autorisés par type de fichier (consigne métier).
ALLOWED_FORMATS = {
    'plan_comptes': {'excel'},
    'code_journal': {'excel'},
    'plan_tiers':   {'excel', 'sage_pnc'},
    'grand_livre':  {'excel', 'sage_pnm'},
}


def detect_format(path: str) -> FileFormat:
    """Retourne le format d'un fichier d'après son extension."""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.xlsx', '.xls'):
        return 'excel'
    if ext == '.pnm':
        return 'sage_pnm'
    if ext == '.pnc':
        return 'sage_pnc'
    return 'unknown'


def validate_format(file_type: str, file_format: FileFormat) -> None:
    """
    Vérifie que le format détecté est autorisé pour ce type de fichier.

    Raises:
        ValueError: si le format n'est pas autorisé pour ce file_type.
    """
    allowed = ALLOWED_FORMATS.get(file_type)
    if allowed is None:
        raise ValueError(f"Type de fichier inconnu: {file_type}")
    if file_format not in allowed:
        raise ValueError(
            f"Format '{file_format}' non autorisé pour '{file_type}'. "
            f"Formats acceptés : {sorted(allowed)}"
        )
