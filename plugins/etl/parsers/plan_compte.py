"""
Parser pour le Plan Comptable Excel (export Sage 100).

Particularités des exports Sage :
    - Les données sont décalées par rapport aux libellés d'en-tête (cellules
      fusionnées) : le N° de compte peut se retrouver dans la colonne du
      libellé "Type", l'intitulé quelques colonnes avant son en-tête, etc.
      On n'exploite donc PAS les positions de l'en-tête pour lire les valeurs.
    - La colonne "Type" (Détail/Total) est vide dans ces exports et n'est
      utilisée nulle part en aval → elle n'est pas extraite.

Extraction par rôle sémantique : chaque ligne de compte contient, de gauche
à droite, le N° de compte (numérique), l'intitulé (texte) puis la nature
(texte, en dernière position).
"""
from typing import Dict, List

import pandas as pd

from etl.parsers.base import (
    compact_row, is_compte_8_digits, is_metadata_row,
    extract_file_metadata, detect_columns_by_header,
)


# Alias des colonnes du plan comptable (sert uniquement à localiser la ligne
# d'en-tête et donc le début des données ; pas à lire les valeurs).
_COLUMN_ALIASES: Dict[str, List[str]] = {
    'type': ['type'],
    'compte': ['n°compte', 'n° compte', 'numero compte', 'compte'],
    'intitule': ['intitulé du compte', 'intitule du compte', 'intitulé', 'intitule'],
    'nature': ['nature de compte', 'nature'],
}

# Natures Sage rencontrées (référence/documentation). L'extraction ne filtre
# PAS sur cette liste : les libellés varient d'un export à l'autre.
_NATURES_CONNUES = [
    'Capitaux', 'Immobilisation', 'Amortis./Provision', 'Résultat-Bilan',
    'Résultat-Gestion', 'Stock', 'Fournisseur', 'Client', 'Salarié',
    'Banque', 'Caisse', 'Charge', 'Produit', 'Aucune',
]


def parse_plan_compte(file_path: str, client_id: str) -> Dict:
    """
    Parse le fichier Plan Comptable Excel.

    Returns: {data: [(compte, intitule, nature)], entite, date_extraction, stats}
    """
    print(f"📄 Lecture du Plan Comptable: {file_path}")

    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()

    metadata = extract_file_metadata(data_list, client_id)

    # Détection de l'en-tête : sert à savoir où commencent les données.
    # min_matches=2 car "Type" et "Raccourci" peuvent manquer/varier.
    header_idx, col_map = detect_columns_by_header(
        data_list, _COLUMN_ALIASES, max_rows=15, min_matches=2,
    )
    start = header_idx + 1 if header_idx >= 0 else 0
    if header_idx >= 0:
        print(f"  📋 Header détecté ligne {header_idx + 1}, colonnes: {col_map}")
    else:
        print("  ⚠️ Header non détecté — extraction sur toutes les lignes")

    results: List[tuple] = []
    stats = {'total': 0, 'detail': 0, 'autres': 0}

    for i in range(start, len(data_list)):
        row = data_list[i]
        if is_metadata_row(row):
            continue

        # Valeurs non vides de la ligne, dans l'ordre des colonnes.
        # Absorbe les décalages : on ne se fie pas aux positions d'en-tête.
        cells = compact_row(row)
        if not cells:
            continue

        # N° de compte = 1ère valeur reconnue comme numéro de compte valide.
        compte = next((v for v in cells if is_compte_8_digits(v)), "")
        if not compte:
            continue

        # Le reste, dans l'ordre : intitulé (1er), nature (dernier).
        rest = [v for v in cells if v != compte]
        intitule = rest[0] if rest else ""
        nature = rest[-1] if len(rest) > 1 else ""

        results.append((compte, intitule, nature))
        stats['total'] += 1
        stats['detail'] += 1

    print(f"  ✓ {stats['total']} comptes extraits")

    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats,
    }
