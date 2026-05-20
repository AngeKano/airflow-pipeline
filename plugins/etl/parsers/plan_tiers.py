"""
Parser pour le Plan Tiers.

Supporte 2 formats Sage Excel :

1. **Plan Tiers "pur"** — fichier listant uniquement les tiers, avec en col 0
   le type (Client / Fournisseur / Salarié / Autre), col 1 le compte tiers
   et col 2+ l'intitulé. C'était le format historique.

2. **Grand Livre des Tiers** — fichier export Sage 100 où chaque tiers est
   précédé d'une ligne d'en-tête `[compte_tiers, intitulé]` suivie de ses
   écritures (qu'on ignore ici) et d'un "Total du tiers". C'est le format
   par défaut chez ENVOL.

Dans les deux cas, on extrait `(compte_tiers, type, intitule_tiers)`.
Le type est déduit de la racine du compte (411x = Client, 401x = Fournisseur,
autre = Autre).
"""
import re
from typing import Dict, List, Tuple

import pandas as pd

from etl.parsers.base import (
    is_valid, clean, compact_row,
    is_date_iso, is_metadata_row, contains_total,
    extract_file_metadata,
)


# ----------------------------------------------------------------------
# Déduction du type tiers (cohérent avec sage_pnc.py)
# ----------------------------------------------------------------------

def _deduire_type_tiers(compte_rattachement: str) -> str:
    c = (compte_rattachement or '').strip()
    if not c:
        return 'Autre'
    if c.startswith('411'):
        return 'Client'
    if c.startswith('401'):
        return 'Fournisseur'
    return 'Autre'


def _is_valid_type_tiers(val: str) -> bool:
    return (val or '').strip() in ['Client', 'Fournisseur', 'Salarié', 'Autre']


def _is_tiers_account(val: str) -> bool:
    """
    Vérifie si une valeur ressemble à un compte tiers Sage : commence par 4
    (classe 4 = tiers en SYSCOHADA/PCG) et a entre 3 et 13 caractères
    (le format peut inclure des suffixes alphanumériques comme '401SO').
    """
    s = (val or '').strip()
    if not s or len(s) < 3 or len(s) > 13:
        return False
    if not s[0] == '4':
        return False
    # Le 2e caractère doit être un chiffre (pour exclure les libellés comme "401-...")
    if not s[1].isdigit():
        return False
    return True


# ----------------------------------------------------------------------
# Parser principal
# ----------------------------------------------------------------------

def parse_plan_tiers(file_path: str, client_id: str) -> Dict:
    """
    Parse le fichier Plan Tiers (formats v1 "pur" et v2 "GL des tiers").

    Returns: {data: [(compte_tiers, type, intitule_tiers)], metadata, stats}
    """
    print(f"📄 Lecture du Plan Tiers: {file_path}")

    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()

    metadata = extract_file_metadata(data_list, client_id)

    results: List[Tuple[str, str, str]] = []
    seen_codes: set = set()
    stats = {
        'total': 0,
        'clients': 0,
        'fournisseurs': 0,
        'autres': 0,
        'nb_lignes_ignorees': 0,
    }

    for i, row in enumerate(data_list):
        if is_metadata_row(row):
            continue
        if contains_total(row):
            continue

        values = compact_row(row)
        if len(values) < 2:
            continue

        compte_tiers = ""
        type_tiers = ""
        intitule = ""

        # === Format 1 : Plan Tiers "pur" (col 0 = type explicite) ===
        if _is_valid_type_tiers(values[0]):
            type_tiers = values[0]
            compte_tiers = values[1] if len(values) > 1 else ""
            for val in values[2:]:
                # Premier texte non-numérique = intitulé (skip codes postaux)
                if val and not val.isdigit():
                    intitule = val
                    break

        # === Format 2 : Grand Livre des Tiers (col 0 = compte tiers) ===
        # Ligne d'en-tête tiers : exactement 2 valeurs courtes, dont la 1ère
        # est un compte tiers (4xxx) et la 2ème est l'intitulé.
        # Les lignes d'écritures ont une date ISO en 1er, donc filtrées.
        elif (
            len(values) == 2
            and _is_tiers_account(values[0])
            and not is_date_iso(values[0])
            and not values[1].replace(' ', '').replace(',', '').replace('-', '').isdigit()
        ):
            compte_tiers = values[0]
            intitule = values[1]
            type_tiers = _deduire_type_tiers(compte_tiers)

        # === Format 3 : "compte tiers au milieu" — ligne où le compte tiers
        # est précédé d'autres infos (rare, mais on couvre) ===
        elif len(values) >= 2 and not is_date_iso(values[0]):
            # Cherche un type explicite dans la ligne
            for j, val in enumerate(values):
                if _is_valid_type_tiers(val):
                    type_tiers = val
                    if j > 0 and _is_tiers_account(values[0]):
                        compte_tiers = values[0]
                    elif j + 1 < len(values) and _is_tiers_account(values[j + 1]):
                        compte_tiers = values[j + 1]
                    if j + 1 < len(values):
                        intitule = values[j + 1] if values[j + 1] != compte_tiers else (
                            values[j + 2] if j + 2 < len(values) else ""
                        )
                    break

        # Validation et stockage
        if not compte_tiers or not type_tiers:
            continue
        if compte_tiers in seen_codes:
            stats['nb_lignes_ignorees'] += 1
            continue
        seen_codes.add(compte_tiers)

        results.append((compte_tiers, type_tiers, intitule or ""))
        stats['total'] += 1
        if type_tiers == 'Client':
            stats['clients'] += 1
        elif type_tiers == 'Fournisseur':
            stats['fournisseurs'] += 1
        else:
            stats['autres'] += 1

    print(
        f"  ✓ {stats['total']} tiers extraits "
        f"({stats['clients']} Clients, {stats['fournisseurs']} Fournisseurs, "
        f"{stats['autres']} Autres)"
    )

    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats,
    }


def load_plan_tiers_map(file_path: str) -> Dict[str, Dict]:
    """
    Charge le plan tiers comme dictionnaire pour enrichissement.
    Retourne: {compte_tiers: {type, intitule}}
    """
    result = parse_plan_tiers(file_path, "")
    tiers_map = {}
    for compte, type_tiers, intitule in result['data']:
        tiers_map[compte] = {'type': type_tiers, 'intitule': intitule}
    return tiers_map
