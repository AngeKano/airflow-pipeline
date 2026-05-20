"""
Mapping Plan Comptable Général français (PCG) → SYSCOHADA Révisé.

Stratégie:
1. Lookup exact sur le numéro de compte
2. Fallback sur la racine 3 chiffres
3. Fallback sur la racine 2 chiffres
4. Si rien ne matche : mapping_status='unmapped', compte_pcg conservé
"""
from typing import Dict, List, Literal, Optional, Tuple

from clickhouse.config import PCG_SYSCOHADA_MAPPING


PlanSource = Literal['PCG', 'SYSCOHADA', 'UNKNOWN']
MappingStatus = Literal['none', 'mapped', 'fallback_racine', 'unmapped']


# Index par compte exact pour lookup O(1)
_EXACT_INDEX: Dict[str, Tuple[str, bool, str]] = {
    pcg: (sysco, is_hao, libelle)
    for pcg, sysco, is_hao, libelle in PCG_SYSCOHADA_MAPPING
}

# Index par racine (premiers N chiffres) — utilisé en fallback
_RACINE_INDEX: Dict[str, Tuple[str, bool, str]] = {}
for pcg, sysco, is_hao, libelle in PCG_SYSCOHADA_MAPPING:
    # Si la clé du mapping est elle-même une racine (≤ 3 chars), elle alimente _RACINE_INDEX
    if len(pcg) <= 3:
        _RACINE_INDEX.setdefault(pcg, (sysco, is_hao, libelle))


def map_compte(compte_pcg: str) -> Dict[str, object]:
    """
    Mappe un numéro de compte PCG vers SYSCOHADA.

    Returns:
        {
          'compte_syscohada': str,        # compte cible (ou compte_pcg si unmapped)
          'is_hao': bool,
          'mapping_status': MappingStatus,
          'libelle': str,                  # libellé du mapping (vide si unmapped)
        }
    """
    compte = (compte_pcg or '').strip()
    if not compte:
        return {
            'compte_syscohada': '',
            'is_hao': False,
            'mapping_status': 'unmapped',
            'libelle': '',
        }

    # 1. Lookup exact
    hit = _EXACT_INDEX.get(compte)
    if hit:
        sysco, is_hao, libelle = hit
        return {
            'compte_syscohada': _reconstruire_compte(compte, compte, sysco),
            'is_hao': is_hao,
            'mapping_status': 'mapped',
            'libelle': libelle,
        }

    # 2. Fallback racine 3 chiffres
    racine3 = compte[:3]
    hit = _RACINE_INDEX.get(racine3)
    if hit:
        sysco, is_hao, libelle = hit
        return {
            'compte_syscohada': _reconstruire_compte(compte, racine3, sysco),
            'is_hao': is_hao,
            'mapping_status': 'fallback_racine',
            'libelle': libelle,
        }

    # 3. Fallback racine 2 chiffres
    racine2 = compte[:2]
    hit = _RACINE_INDEX.get(racine2)
    if hit:
        sysco, is_hao, libelle = hit
        return {
            'compte_syscohada': _reconstruire_compte(compte, racine2, sysco),
            'is_hao': is_hao,
            'mapping_status': 'fallback_racine',
            'libelle': libelle,
        }

    # 4. Non mappé : conserver le compte PCG d'origine
    return {
        'compte_syscohada': compte,
        'is_hao': False,
        'mapping_status': 'unmapped',
        'libelle': '',
    }


def _reconstruire_compte(compte_pcg: str, racine_pcg: str, racine_sysco: str) -> str:
    """
    Reconstruit le compte SYSCOHADA en remplaçant la racine PCG par la racine SYSCOHADA
    et en conservant la sous-classification du compte d'origine.

    Exemple: compte_pcg='607100', racine_pcg='607', racine_sysco='601' → '601100'
             compte_pcg='51210000', racine_pcg='512', racine_sysco='521' → '52110000'
    """
    if len(compte_pcg) <= len(racine_pcg):
        return racine_sysco
    suffix = compte_pcg[len(racine_pcg):]
    return racine_sysco + suffix


def detect_plan_source(comptes: List[str]) -> PlanSource:
    """
    Détecte le plan comptable source à partir d'une liste de comptes.

    Heuristique basée sur les comptes financiers (très discriminants entre PCG et SYSCOHADA):
    - PCG       : présence de 512* (banque) ou 531* (caisse), absence de 521*/571*
    - SYSCOHADA : présence de 521* (banque) ou 571* (caisse), absence de 512*/531*
    - UNKNOWN   : aucun compte financier identifiable, ou les deux présents (incohérent)

    Args:
        comptes: liste de numéros de comptes (peut contenir doublons, ordre indifférent)

    Returns:
        'PCG' | 'SYSCOHADA' | 'UNKNOWN'
    """
    has_pcg_markers = False
    has_sysco_markers = False

    for c in comptes:
        c = (c or '').strip()
        if not c:
            continue
        if c.startswith('512') or c.startswith('531'):
            has_pcg_markers = True
        if c.startswith('521') or c.startswith('571'):
            has_sysco_markers = True

    if has_pcg_markers and not has_sysco_markers:
        return 'PCG'
    if has_sysco_markers and not has_pcg_markers:
        return 'SYSCOHADA'
    return 'UNKNOWN'
