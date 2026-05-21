"""
Parser pour le Plan Comptable Excel.

Version 2 : détection automatique des colonnes via la ligne d'en-tête,
plus de positions hardcodées. Tolère les décalages dûs aux cellules fusionnées
des exports Sage 100.

Structure attendue :
    - Ligne d'en-tête avec : "Type", "N°compte", "Intitulé du compte",
      "Nature de compte" (ordre indifférent, tolère les libellés tronqués).
    - Pour chaque compte : 1 ligne avec Type ('Détail' ou 'Total'),
      N° compte, Intitulé, Nature.
"""
from typing import Dict, List

import pandas as pd

from etl.parsers.base import (
    is_valid, clean, compact_row, get_cell,
    is_compte_8_digits, is_metadata_row,
    extract_file_metadata, detect_columns_by_header,
)


# Alias des colonnes du plan comptable.
_COLUMN_ALIASES: Dict[str, List[str]] = {
    'type': ['type'],
    'compte': ['n°compte', 'n° compte', 'numero compte', 'compte'],
    'intitule': ['intitulé du compte', 'intitule du compte', 'intitulé', 'intitule'],
    'nature': ['nature de compte', 'nature'],
}

# Types de compte valides (col Type)
_TYPES_VALIDES = ['Détail', 'Detail', 'Total']

# Natures de compte connues (utilisées pour vérification, pas pour le filtre)
_NATURES_CONNUES = [
    'Capitaux', 'Immobilisation', 'Résultat-Bilan', 'Aucune',
    'Charges', 'Produits', 'Stock', 'Trésorerie',
]


def _cell_in_range(row: list, target_col, low: int, high: int) -> str:
    """
    1ère valeur non-vide dans la plage de colonnes [low, high] (inclus), en
    partant du target_col et en s'éloignant progressivement.

    Utilisé pour absorber les décalages dûs aux cellules fusionnées Sage où
    un label d'en-tête à la col X peut avoir sa valeur effective à X-3 ou X+2.
    Les bornes low/high empêchent de capter la valeur d'une colonne voisine.
    """
    if target_col is None or target_col < 0:
        return ""
    # Élargissement progressif : 0, -1, +1, -2, +2, -3, +3, ...
    max_radius = max(target_col - low, high - target_col)
    for offset in range(max_radius + 1):
        for sign in (0,) if offset == 0 else (-1, 1):
            col = target_col + sign * offset
            if low <= col <= high and 0 <= col < len(row):
                val = get_cell(row, col)
                if val:
                    return val
    return ""


def _col_bounds(col_map: Dict[str, int], role: str) -> tuple:
    """
    Renvoie les bornes (low, high) dans lesquelles chercher la valeur de
    la colonne `role`, en évitant d'empiéter sur les colonnes voisines.
    """
    target = col_map.get(role)
    if target is None or target < 0:
        return 0, 0
    others = sorted(c for r, c in col_map.items() if r != role and c >= 0)
    # Borne basse = précédente col voisine + 1
    low = 0
    for c in others:
        if c < target:
            low = c + 1
    # Borne haute = prochaine col voisine - 1
    high = 100  # large par défaut
    for c in others:
        if c > target:
            high = c - 1
            break
    return low, high


def parse_plan_compte(file_path: str, client_id: str) -> Dict:
    """
    Parse le fichier Plan Comptable Excel.

    Returns: {data: [(compte, type, intitule, nature)], metadata, stats}
    """
    print(f"📄 Lecture du Plan Comptable: {file_path}")

    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()

    metadata = extract_file_metadata(data_list, client_id)

    # Détection automatique des colonnes via le header
    header_idx, col_map = detect_columns_by_header(
        data_list,
        _COLUMN_ALIASES,
        max_rows=15,
        min_matches=3,
    )

    results: List[tuple] = []
    stats = {'total': 0, 'detail': 0, 'autres': 0}

    if header_idx < 0 or 'compte' not in col_map:
        # Fallback : pas de header détecté → on tente l'extraction par patterns
        # (mode rétrocompatibilité avec l'ancien parser).
        print(f"  ⚠️ Header non détecté — fallback pattern matching")
        return _parse_fallback(data_list, metadata, stats)

    print(f"  📋 Header détecté ligne {header_idx + 1}, colonnes: {col_map}")

    type_col = col_map.get('type')
    compte_col = col_map['compte']
    intitule_col = col_map.get('intitule')
    nature_col = col_map.get('nature')

    # Calcul des bornes par colonne pour absorber les décalages sans empiéter
    # sur les colonnes voisines.
    type_lo, type_hi = _col_bounds(col_map, 'type')
    compte_lo, compte_hi = _col_bounds(col_map, 'compte')
    intitule_lo, intitule_hi = _col_bounds(col_map, 'intitule')
    nature_lo, nature_hi = _col_bounds(col_map, 'nature')

    for i in range(header_idx + 1, len(data_list)):
        row = data_list[i]
        if is_metadata_row(row):
            continue

        # Lecture avec fenêtre élargie bornée par les colonnes voisines
        type_compte = _cell_in_range(row, type_col, type_lo, type_hi) if type_col is not None else ""
        compte = _cell_in_range(row, compte_col, compte_lo, compte_hi)
        intitule = _cell_in_range(row, intitule_col, intitule_lo, intitule_hi) if intitule_col is not None else ""
        nature = _cell_in_range(row, nature_col, nature_lo, nature_hi) if nature_col is not None else ""

        # Validation : compte valide + type reconnu
        if not is_compte_8_digits(compte):
            continue
        if type_compte and type_compte not in _TYPES_VALIDES:
            # Si le Type capté n'est pas un type valide, on tente fallback
            # via compact_row (parfois le Type est plus loin)
            values = compact_row(row)
            type_compte = next(
                (v for v in values if v in _TYPES_VALIDES),
                type_compte,
            )

        if not type_compte:
            # Si pas de type identifiable mais on a un compte valide,
            # on suppose "Détail" (le cas le plus courant)
            type_compte = 'Détail'

        results.append((compte, type_compte, intitule or "", nature or ""))
        stats['total'] += 1
        if type_compte in ('Détail', 'Detail'):
            stats['detail'] += 1
        else:
            stats['autres'] += 1

    print(f"  ✓ {stats['total']} comptes extraits ({stats['detail']} Détail)")

    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats,
    }


def _parse_fallback(data_list, metadata, stats) -> Dict:
    """
    Fallback historique : extraction par patterns si le header n'est pas
    détecté. Conserve la compatibilité avec les exports anciens / atypiques.
    """
    results: List[tuple] = []

    for row in data_list:
        if is_metadata_row(row):
            continue

        values = compact_row(row)
        if len(values) < 2:
            continue

        type_compte = ""
        compte = ""
        intitule = ""
        nature = ""

        if values[0] in _TYPES_VALIDES:
            type_compte = values[0]
            for j, val in enumerate(values[1:], start=1):
                if is_compte_8_digits(val):
                    compte = val
                    # L'intitulé est le 1er texte non-numérique et non-nature
                    for k in range(j + 1, len(values)):
                        cand = values[k]
                        if not is_compte_8_digits(cand) and cand not in _NATURES_CONNUES:
                            intitule = cand
                            break
                    # Nature = 1ère valeur connue depuis la fin
                    for v in reversed(values):
                        if v in _NATURES_CONNUES:
                            nature = v
                            break
                    break

        if compte and type_compte:
            results.append((compte, type_compte, intitule or "", nature or ""))
            stats['total'] += 1
            if type_compte in ('Détail', 'Detail'):
                stats['detail'] += 1
            else:
                stats['autres'] += 1

    print(f"  ✓ {stats['total']} comptes extraits (fallback, {stats['detail']} Détail)")

    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats,
    }
