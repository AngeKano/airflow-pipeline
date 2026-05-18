"""
Parser pour le Plan Comptable (PLAN_COMPTABLE.xlsx)
Extraction robuste - ignore les colonnes vides
"""
import pandas as pd
from typing import Dict, List, Tuple

from etl.parsers.base import (
    is_valid, clean, compact_row, get_values_only,
    is_compte_8_digits, is_metadata_row, extract_file_metadata
)


def parse_plan_compte(file_path: str, client_id: str) -> Dict:
    """
    Parse le fichier Plan Comptable.
    
    Structure attendue (avec décalages possibles):
    - Type (Détail/Total)
    - N° compte (6 chiffres)
    - Intitulé du compte
    - Nature de compte (Capitaux, Immobilisation, etc.)
    
    Retourne: {data: [(compte, type, intitule, nature)], metadata, stats}
    """
    print(f"📄 Lecture du Plan Comptable: {file_path}")
    
    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()
    
    # Extraire métadonnées
    metadata = extract_file_metadata(data_list, client_id)
    
    results = []
    stats = {'total': 0, 'detail': 0, 'autres': 0}
    
    for i, row in enumerate(data_list):
        # Ignorer les lignes vides ou de métadonnées
        if is_metadata_row(row):
            continue
        
        # Compacter la ligne (enlever les nulls)
        values = compact_row(row)
        
        if len(values) < 2:
            continue
        
        # Détecter une ligne de compte valide
        # Pattern: Type (Détail/Total) + Compte 6 chiffres + Intitulé + Nature
        type_compte = ""
        numero_compte = ""
        intitule = ""
        nature = ""
        
        # Chercher le type (Détail ou Total)
        if values[0] in ['Détail', 'Detail', 'Total']:
            type_compte = values[0]
            
            # Chercher le compte 6 chiffres
            for j, val in enumerate(values[1:], start=1):
                if is_compte_8_digits(val):
                    numero_compte = val
                    
                    # L'intitulé est généralement juste après le compte
                    if j + 1 < len(values):
                        # Trouver l'intitulé (texte non numérique)
                        for k in range(j + 1, len(values)):
                            candidate = values[k]
                            # L'intitulé n'est pas un numéro et pas une nature connue
                            if not is_compte_8_digits(candidate):
                                if candidate not in ['Capitaux', 'Immobilisation', 'Résultat-Bilan', 'Aucune', 'Charges', 'Produits', 'Stock', 'Trésorerie']:
                                    intitule = candidate
                                    break
                    
                    # Chercher la nature (dernières valeurs connues)
                    natures_connues = ['Capitaux', 'Immobilisation', 'Résultat-Bilan', 'Aucune', 'Charges', 'Produits', 'Stock', 'Trésorerie']
                    for val in reversed(values):
                        if val in natures_connues:
                            nature = val
                            break
                    
                    break
        
        # Ajouter si compte valide trouvé
        if numero_compte and type_compte:
            results.append((
                numero_compte,
                type_compte,
                intitule or "",
                nature or ""
            ))
            
            if type_compte == 'Détail' or type_compte == 'Detail':
                stats['detail'] += 1
            else:
                stats['autres'] += 1
            stats['total'] += 1
    
    print(f"  ✓ {stats['total']} comptes extraits ({stats['detail']} Détail)")
    
    return {
        'data': results,
        'entite': metadata['entite'],
        'date_extraction': metadata['date_extraction'],
        'stats': stats
    }
