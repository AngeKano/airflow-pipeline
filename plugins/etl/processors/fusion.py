"""
Processor pour la fusion du Grand Livre
GL Comptes + GL Tiers + Rubriques PLE → Grand Livre unifié
"""
import pandas as pd
from typing import Optional

from clickhouse.manager import ClickHouseManager


def fusionner_grand_livre(
    client_id: str,
    batch_id: str,
    periode: str,
    gl_compte_result: Optional[dict],
    gl_tiers_result: Optional[dict]
) -> Optional[dict]:
    """
    Fusionne les Grand Livres Comptes et Tiers avec les rubriques PLE.
    
    Args:
        client_id: Identifiant du client
        batch_id: Identifiant du batch
        periode: Période comptable
        gl_compte_result: Résultat du parsing GL Comptes
        gl_tiers_result: Résultat du parsing GL Tiers
        
    Returns:
        Statistiques de fusion ou None si échec
    """
    print("\n" + "="*70)
    print("📊 FUSION GRAND LIVRE (GL Comptes + GL Tiers + Rubriques PLE)")
    print("="*70)
    print(f"Client: {client_id}")
    print(f"Batch: {batch_id}")
    print(f"Période: {periode}")

    if not gl_compte_result:
        print("⚠️ GL Comptes non traité - fusion impossible")
        return None

    if not gl_tiers_result:
        print("⚠️ GL Tiers non traité - fusion partielle (sans enrichissement tiers)")

    ch = ClickHouseManager()

    print("\n🔄 Fusion en cours...")
    stats = ch.fusionner_grand_livres(client_id, periode, batch_id)

    print(f"\n✅ Fusion terminée!")
    print(f"  📊 Statistiques:")
    print(f"     - Total transactions: {stats['total_transactions']}")
    
    total = max(1, stats['total_transactions'])
    print(f"     - Avec tiers: {stats['transactions_avec_tiers']} ({100*stats['transactions_avec_tiers']/total:.1f}%)")
    print(f"     - Sans tiers: {stats['transactions_sans_tiers']} ({100*stats['transactions_sans_tiers']/total:.1f}%)")
    print(f"     - Avec rubrique: {stats['transactions_avec_rubrique']} ({100*stats['transactions_avec_rubrique']/total:.1f}%)")
    print(f"     - Sans rubrique: {stats['transactions_sans_rubrique']} ({100*stats['transactions_sans_rubrique']/total:.1f}%)")
    print(f"     - Comptes distincts: {stats['nb_comptes']}")
    print(f"     - Rubriques utilisées: {stats['nb_rubriques']}")
    print(f"     - Total Débit: {stats['total_debit']:,.2f}")
    print(f"     - Total Crédit: {stats['total_credit']:,.2f}")
    print(f"     - Équilibré: {'✅' if stats['equilibre'] else '❌'}")
    print("="*70)

    return {
        'periode': periode,
        'batch_id': batch_id,
        **stats
    }


def get_fusion_periode(gl_compte_result: Optional[dict], gl_tiers_result: Optional[dict]) -> str:
    """
    Détermine la période à partir des résultats de parsing.
    
    Args:
        gl_compte_result: Résultat du parsing GL Comptes
        gl_tiers_result: Résultat du parsing GL Tiers
        
    Returns:
        Période au format YYYYMM
    """
    if gl_compte_result and 'periode' in gl_compte_result:
        return gl_compte_result['periode']
    elif gl_tiers_result and 'periode' in gl_tiers_result:
        return gl_tiers_result['periode']
    else:
        return pd.Timestamp.now().strftime("%Y%m")
