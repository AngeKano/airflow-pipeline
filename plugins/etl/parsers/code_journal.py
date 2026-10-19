"""
Parser pour les Codes Journaux (CODES_JOURNAUX.xlsx)
Extraction robuste - ignore les colonnes vides
"""
import pandas as pd
import re
from typing import Dict, List, Tuple

from etl.parsers.base import (
    is_valid, clean, compact_row, get_values_only,
    is_metadata_row, extract_file_metadata
)


TYPES_JOURNAUX = ['Achats', 'Trésorerie', 'Général', 'Ventes', 'Situation', 'A-nouveaux']


def is_valid_code_journal(val: str, row_values: List[str] = ()) -> bool:
    """
    Vérifie si c'est un code journal valide (2-10 caractères).

    - Code commençant par une lettre (ACH, BQUE, OD…) : accepté.
    - Code numérique (200, 500, 850… — plans Sage à journaux numérotés) :
      accepté seulement s'il est alphanumérique ET que la ligne porte un type
      de journal reconnu, pour ne pas confondre avec un numéro de page/une date.
    """
    if not val:
        return False
    val = val.strip()

    # Codes à ignorer
    invalid_codes = ['=', 'C.L', 'Som', 'Rap', 'Tot', 'Code', 'N°', 'Rglt']
    if val in invalid_codes:
        return False

    # Doit être court
    if len(val) < 2 or len(val) > 10:
        return False

    if val[0].isalpha():
        return True

    return val.isalnum() and any(v in TYPES_JOURNAUX for v in row_values)


def parse_code_journal(file_path: str, client_id: str) -> Dict:
    """
    Parse le fichier Codes Journaux.
    
    Structure attendue (avec décalages possibles):
    - Code (ACH, BQUE, CAIS, OD, etc.)
    - Intitulé (ACHATS, SIB, CAISSE, etc.)
    - Type (Achats, Trésorerie, Général, Ventes)
    
    Retourne: {data: [(code, intitule, type)], metadata, stats}
    """
    print(f"📄 Lecture des Codes Journaux: {file_path}")
    
    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()
    
    # Extraire métadonnées
    metadata = extract_file_metadata(data_list, client_id)
    
    results = []
    types_connus = TYPES_JOURNAUX
    stats = {'total': 0, 'by_type': {}}
    
    for i, row in enumerate(data_list):
        # Ignorer les lignes vides ou de métadonnées
        if is_metadata_row(row):
            continue
        
        # Compacter la ligne
        values = compact_row(row)
        
        if len(values) < 2:
            continue
        
        # Le code journal est généralement le premier élément valide
        code = values[0] if values else ""
        
        if not is_valid_code_journal(code, values[1:]):
            continue
        
        # Chercher l'intitulé (2ème valeur) et le type (valeur connue)
        intitule = values[1] if len(values) > 1 else ""
        type_journal = ""
        
        # Chercher le type dans les valeurs
        for val in values[2:]:
            if val in types_connus:
                type_journal = val
                break
        
        # Vérifier que l'intitulé n'est pas un type
        if intitule in types_connus:
            type_journal = intitule
            intitule = ""
        
        results.append((
            code,
            intitule,
            type_journal
        ))
        
        stats['total'] += 1
        if type_journal:
            stats['by_type'][type_journal] = stats['by_type'].get(type_journal, 0) + 1
    
    print(f"  ✓ {stats['total']} codes journaux extraits")
    if stats['by_type']:
        print(f"    Types: {stats['by_type']}")
    
    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats
    }
