"""
Processor d'enrichissement pour le Grand Livre
Ajoute les rubriques PLE et enrichit les intitulés
"""
from typing import List, Tuple, Dict

from clickhouse.manager import ClickHouseManager


def enrich_grand_livre(
    client_id: str,
    data: List[Tuple],
    ch_manager: ClickHouseManager = None
) -> List[Tuple]:
    """
    Enrichit les transactions du Grand Livre avec:
    - Rubrique comptable (depuis PLE)
    - Intitulé du tiers (depuis plan_tiers)
    - Type de tiers (depuis plan_tiers)
    
    Format d'entrée (16 colonnes):
    (date_gl, entite, compte, intitule_compte, date_trans, code_journal,
     numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
     periode, batch_id, row_id)
    
    Format de sortie (19 colonnes):
    (date_gl, entite, compte, intitule_compte, rubrique, date_trans, code_journal,
     numero_piece, numero_facture, libelle, n_tiers, intitule_tiers, type_tiers,
     debit, credit, solde, periode, batch_id, row_id)
    """
    print(f"🔄 Enrichissement de {len(data)} transactions...")
    
    if not data:
        return []
    
    # Créer le manager si non fourni
    close_manager = False
    if ch_manager is None:
        ch_manager = ClickHouseManager()
        close_manager = True
    
    enriched = []
    stats = {
        'with_rubrique': 0,
        'with_tiers_info': 0,
    }
    
    # Cache pour éviter les requêtes répétées
    rubrique_cache = {}
    tiers_cache = {}
    
    try:
        for row in data:
            (date_gl, entite, compte, intitule_compte, date_trans, code_journal,
             numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
             periode, batch_id, row_id) = row
            
            # Enrichir avec la rubrique
            if compte not in rubrique_cache:
                rubrique_cache[compte] = ch_manager.get_rubrique(client_id, compte)
            rubrique = rubrique_cache[compte]
            
            if rubrique:
                stats['with_rubrique'] += 1
            
            # Enrichir avec les infos du tiers
            intitule_tiers = ""
            type_tiers = ""
            
            if n_tiers:
                if n_tiers not in tiers_cache:
                    tiers_cache[n_tiers] = {
                        'intitule': ch_manager.get_intitule_tiers(client_id, n_tiers),
                        'type': ch_manager.get_type_tiers(client_id, n_tiers)
                    }
                
                tiers_info = tiers_cache[n_tiers]
                intitule_tiers = tiers_info['intitule']
                type_tiers = tiers_info['type']
                
                if intitule_tiers or type_tiers:
                    stats['with_tiers_info'] += 1
            
            # Construire la ligne enrichie (19 colonnes)
            enriched.append((
                date_gl,
                entite,
                compte,
                intitule_compte,
                rubrique,
                date_trans,
                code_journal,
                numero_piece,
                numero_facture,
                libelle,
                n_tiers,
                intitule_tiers,
                type_tiers,
                debit,
                credit,
                solde,
                periode,
                batch_id,
                row_id
            ))
        
        print(f"  ✓ {stats['with_rubrique']} transactions avec rubrique")
        print(f"  ✓ {stats['with_tiers_info']} transactions avec infos tiers")
        
        return enriched
        
    finally:
        if close_manager:
            ch_manager.close()
