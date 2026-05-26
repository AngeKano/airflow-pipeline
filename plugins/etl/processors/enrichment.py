"""
Processor d'enrichissement pour le Grand Livre.

Enrichit chaque transaction avec :
    - Rubrique comptable (depuis PLE)
    - Intitulé du tiers (depuis plan_tiers)
    - Type de tiers (depuis plan_tiers)
    - Traçabilité du mapping PCG → SYSCOHADA si plan source = PCG :
        * compte_pcg_origine
        * is_hao
        * mapping_status

Le mapping comptable n'est appliqué que si plan_source == 'PCG'. Dans tous les
autres cas (SYSCOHADA, UNKNOWN) les comptes sont conservés tels quels et les
colonnes de traçabilité prennent leurs défauts ('', 0, 'none').
"""
from typing import Dict, List, Tuple

from clickhouse.manager import ClickHouseManager
from etl.mapping import map_compte


def enrich_grand_livre(
    client_id: str,
    data: List[Tuple],
    ch_manager: ClickHouseManager = None,
    plan_source: str = 'SYSCOHADA',
) -> List[Tuple]:
    """
    Enrichit les transactions du Grand Livre.

    Format d'entrée (16 colonnes — sortie des parsers):
        (date_gl, entite, compte, intitule_compte, date_trans, code_journal,
         numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
         periode, batch_id, row_id)

    Format de sortie (23 colonnes — aligné sur la table ClickHouse grand_livre,
    rubrique P&L et bilan_rubrique côte à côte après intitule_compte) :
        (date_gl, entite, compte, intitule_compte, rubrique, bilan_rubrique,
         date_trans, code_journal, numero_piece, numero_facture, libelle,
         n_tiers, intitule_tiers, type_tiers, debit, credit, solde,
         periode, batch_id, row_id,
         compte_pcg_origine, is_hao, mapping_status)

    Args:
        plan_source: 'PCG' | 'SYSCOHADA' | 'UNKNOWN'. Seul 'PCG' déclenche le mapping.
    """
    apply_mapping = plan_source == 'PCG'
    print(f"🔄 Enrichissement de {len(data)} transactions "
          f"(plan_source={plan_source}, mapping={'appliqué' if apply_mapping else 'non appliqué'})...")

    if not data:
        return []

    close_manager = False
    if ch_manager is None:
        ch_manager = ClickHouseManager()
        close_manager = True

    enriched: List[Tuple] = []
    stats = {
        'with_rubrique': 0,
        'with_tiers_info': 0,
        'mapped': 0,
        'fallback_racine': 0,
        'unmapped': 0,
    }

    # Caches (les lookups ClickHouse sont coûteux)
    rubrique_cache: Dict[str, str] = {}
    bilan_rubrique_cache: Dict[tuple, str] = {}  # (compte, solde_sign) → bilan_rubrique
    tiers_cache: Dict[str, Dict[str, str]] = {}
    mapping_cache: Dict[str, Dict[str, object]] = {}

    try:
        for row in data:
            (date_gl, entite, compte, intitule_compte, date_trans, code_journal,
             numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
             periode, batch_id, row_id) = row

            # --- Mapping PCG → SYSCOHADA (si applicable) ---
            if apply_mapping:
                if compte not in mapping_cache:
                    mapping_cache[compte] = map_compte(compte)
                m = mapping_cache[compte]
                compte_pcg_origine = compte
                compte_final = m['compte_syscohada']
                is_hao = 1 if m['is_hao'] else 0
                mapping_status = m['mapping_status']
                stats[mapping_status] = stats.get(mapping_status, 0) + 1
            else:
                compte_pcg_origine = ''
                compte_final = compte
                is_hao = 0
                mapping_status = 'none'

            # --- Rubrique P&L (lookup PLE basé sur le compte final SYSCOHADA) ---
            if compte_final not in rubrique_cache:
                rubrique_cache[compte_final] = ch_manager.get_rubrique(client_id, compte_final)
            rubrique = rubrique_cache[compte_final]
            if rubrique:
                stats['with_rubrique'] += 1

            # --- Rubrique Bilan (lookup avec filtre solde) ---
            # Le solde signé (debit - credit) détermine si on tombe dans les
            # filtres "solde débiteur" ou "solde créditeur" du référentiel.
            solde_signed = float(debit) - float(credit)
            solde_sign = 1 if solde_signed > 0 else (-1 if solde_signed < 0 else 0)
            cache_key = (compte_final, solde_sign)
            if cache_key not in bilan_rubrique_cache:
                bilan_rubrique_cache[cache_key] = ch_manager.get_bilan_rubrique(
                    client_id, compte_final, solde_signed,
                )
            bilan_rubrique = bilan_rubrique_cache[cache_key]
            if bilan_rubrique:
                stats['with_bilan'] = stats.get('with_bilan', 0) + 1

            # --- Tiers (intitulé + type) ---
            intitule_tiers = ""
            type_tiers = ""
            if n_tiers:
                if n_tiers not in tiers_cache:
                    tiers_cache[n_tiers] = {
                        'intitule': ch_manager.get_intitule_tiers(client_id, n_tiers),
                        'type': ch_manager.get_type_tiers(client_id, n_tiers),
                    }
                tiers_info = tiers_cache[n_tiers]
                intitule_tiers = tiers_info['intitule']
                type_tiers = tiers_info['type']
                if intitule_tiers or type_tiers:
                    stats['with_tiers_info'] += 1

            enriched.append((
                date_gl,
                entite,
                compte_final,
                intitule_compte,
                rubrique,
                bilan_rubrique,
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
                row_id,
                compte_pcg_origine,
                is_hao,
                mapping_status,
            ))

        print(f"  ✓ {stats['with_rubrique']} transactions avec rubrique P&L")
        print(f"  ✓ {stats.get('with_bilan', 0)} transactions avec rubrique Bilan")
        print(f"  ✓ {stats['with_tiers_info']} transactions avec infos tiers")
        if apply_mapping:
            print(f"  ✓ Mapping PCG→SYSCO: "
                  f"{stats.get('mapped', 0)} mapped, "
                  f"{stats.get('fallback_racine', 0)} fallback_racine, "
                  f"{stats.get('unmapped', 0)} unmapped")

        return enriched

    finally:
        if close_manager:
            ch_manager.close()
