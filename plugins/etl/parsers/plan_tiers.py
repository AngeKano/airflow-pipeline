"""
Parser pour le Plan Tiers (PLAN_TIERS.xlsx)
Extraction robuste - ignore les colonnes vides
"""
import pandas as pd
from typing import Dict, List, Tuple, Optional

from etl.parsers.base import (
    is_valid, clean, compact_row, get_values_only,
    is_metadata_row, extract_file_metadata
)


def is_valid_type_tiers(val: str) -> bool:
    """Vérifie si c'est un type de tiers valide."""
    if not val:
        return False
    return val.strip() in ['Client', 'Fournisseur', 'Salarié', 'Autre']


def parse_plan_tiers(file_path: str, client_id: str) -> Dict:
    """
    Parse le fichier Plan Tiers.
    
    Structure attendue (avec décalages possibles):
    - Type (Client/Fournisseur)
    - Compte tiers (code alphanumérique)
    - Intitulé du tiers
    
    Retourne: {data: [(compte_tiers, type, intitule_tiers)], metadata, stats}
    """
    print(f"📄 Lecture du Plan Tiers: {file_path}")
    
    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()
    
    # Extraire métadonnées
    metadata = extract_file_metadata(data_list, client_id)
    
    results = []
    stats = {'total': 0, 'clients': 0, 'fournisseurs': 0, 'autres': 0}
    
    for i, row in enumerate(data_list):
        # Ignorer les lignes vides ou de métadonnées
        if is_metadata_row(row):
            continue
        
        # Compacter la ligne
        values = compact_row(row)
        
        if len(values) < 2:
            continue
        
        # Détecter si c'est une ligne de tiers valide
        type_tiers = ""
        compte_tiers = ""
        intitule = ""
        
        # Le type est généralement en première position
        if is_valid_type_tiers(values[0]):
            type_tiers = values[0]
            
            # Le compte tiers est juste après
            if len(values) > 1:
                compte_tiers = values[1]
            
            # L'intitulé est la valeur suivante (non vide, pas un code postal)
            if len(values) > 2:
                # Trouver l'intitulé (au moins 1 caractère, non numérique)
                for val in values[2:]:
                    # Ignorer les codes postaux (numériques purs), mais prendre toute valeur de longueur ≥ 1
                    if len(val) >= 1 and not val.isdigit():
                        intitule = val
                        break

        # Alternative: parfois le compte est en premier
        elif len(values) >= 2:
            # Vérifier si le deuxième élément est un type
            for j, val in enumerate(values):
                if is_valid_type_tiers(val):
                    type_tiers = val
                    # Le compte est avant le type
                    if j > 0:
                        compte_tiers = values[0]
                    # L'intitulé est après le type
                    if j + 1 < len(values):
                        intitule = values[j + 1]
                    break
        
        # Ajouter si compte tiers valide trouvé
        if compte_tiers and type_tiers:
            results.append((
                compte_tiers,
                type_tiers,
                intitule or ""
            ))
            
            stats['total'] += 1
            if type_tiers == 'Client':
                stats['clients'] += 1
            elif type_tiers == 'Fournisseur':
                stats['fournisseurs'] += 1
            else:
                stats['autres'] += 1
    
    print(f"  ✓ {stats['total']} tiers extraits ({stats['clients']} Clients, {stats['fournisseurs']} Fournisseurs)")
    
    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats
    }


def load_plan_tiers_map(file_path: str) -> Dict[str, Dict]:
    """
    Charge le plan tiers comme dictionnaire pour enrichissement.
    Retourne: {compte_tiers: {type, intitule}}
    """
    result = parse_plan_tiers(file_path, "")
    
    tiers_map = {}
    for compte, type_tiers, intitule in result['data']:
        tiers_map[compte] = {
            'type': type_tiers,
            'intitule': intitule
        }
    
    return tiers_map
