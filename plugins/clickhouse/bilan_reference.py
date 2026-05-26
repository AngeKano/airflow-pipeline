"""
Référentiel SYSCOHADA RÉVISÉ du bilan — source de vérité Python.

Cette source remplace la lecture du fichier Mapping PL DEF 2.xlsx :
- 57 rubriques bilan (codes AD à DZ)
- Subdivisions explicites : DK → DK1/DK2/DK3
- Splits par sub-compte : DC (191-194) vs DN (195-199)
- Filtres soldes pour les comptes mixtes actif/passif (471, 478, 52)
- Compositions de rubriques agrégées

Régénération des constantes dans config.py :
    python tools/generate_bilan_constants.py
"""
from typing import Dict, List, NamedTuple, Tuple


class BilanRow(NamedTuple):
    """Une ligne du référentiel bilan tel que validé par l'utilisateur."""
    code: str
    libelle: str
    expression: str  # Notation DSL : '211', '201,202', '271-275', 'AE+AF', etc.


# ============================================================
# RÉFÉRENTIEL VALIDÉ — 57 lignes (validation utilisateur 2026-05)
# ============================================================
BILAN_REFERENCE: List[BilanRow] = [
    # Actif immobilisé
    BilanRow('AD', 'Immobilisations incorporelles', 'AE+AF+AG+AH'),
    BilanRow('AE', 'Frais développement', '201'),
    BilanRow('AF', 'Brevets licences logiciels', '204'),
    BilanRow('AG', 'Fonds commercial', '206'),
    BilanRow('AH', 'Autres incorporelles', '208'),
    BilanRow('AI', 'Immobilisations corporelles', 'AJ+AK+AL+AM+AN+AP'),
    BilanRow('AJ', 'Terrains', '211'),
    BilanRow('AK', 'Bâtiments', '213'),
    BilanRow('AL', 'Installations', '214'),
    BilanRow('AM', 'Matériel', '215'),
    BilanRow('AN', 'Transport', '218'),
    BilanRow('AP', 'Avances immobilisations', '23'),
    BilanRow('AQ', 'Immobilisations financières', 'AR+AS'),
    BilanRow('AR', 'Titres participation', '261'),
    BilanRow('AS', 'Autres financières', '271-275'),
    BilanRow('AZ', 'Total actif immobilisé', 'AD+AI+AQ'),

    # Actif circulant
    BilanRow('BA', 'Actif Circulant HAO', '471 (solde débiteur),478 (solde débiteur), 488'),
    BilanRow('BB', 'Stocks et Encours', '31-38,39'),
    BilanRow('BG', 'Créances et Emplois Assimilés', 'BH+BI+BJ'),
    BilanRow('BH', 'Avances fournisseurs', '409'),
    BilanRow('BI', 'Clients', '41 sauf 419'),
    # BJ : 42-48 sauf comptes mixtes (471/478/488) ET sauf 42/43/44 qui sont gérés
    # par les sous-rubriques DK1/DK2/DK3 du passif circulant.
    BilanRow('BJ', 'Autres créances', '42-48 (sauf 42, 43, 44, 471, 478 et 488)'),
    BilanRow('BK', 'Total Actif Circulant', 'BA+BB+BG'),

    # Trésorerie actif
    BilanRow('BQ', 'Titres placement', '50'),
    BilanRow('BR', 'Valeurs à encaisser', '512'),
    BilanRow('BS', 'Banques et caisse', '52 (solde débiteur),53,57'),
    BilanRow('BT', 'Total Trésorerie Actif', 'BQ+BR+BS'),
    BilanRow('BU', 'Écart conversion actif', '476'),
    BilanRow('BZ', 'Total actif', 'AZ+BK+BT+BU'),

    # Capitaux propres
    BilanRow('CA', 'Capital', '10'),
    BilanRow('CB', 'Capital non appelé', '109'),
    BilanRow('CD', 'Primes', '11'),
    BilanRow('CE', 'Écart réévaluation', '105'),
    BilanRow('CF', 'Réserves indisponibles', '111'),
    BilanRow('CG', 'Réserves libres', '112'),
    BilanRow('CH', 'Report à nouveau', '12'),
    BilanRow('CJ', 'Résultat', '13'),
    BilanRow('CL', 'Subventions', '14'),
    BilanRow('CM', 'Provisions réglementées', '15'),
    BilanRow('CP', 'Total capitaux propres', 'Somme CA à CM'),

    # Dettes financières
    BilanRow('DA', 'Emprunts', '16 sauf 167'),
    BilanRow('DB', 'Crédit bail', '167'),
    BilanRow('DC', 'Provisions LT', '191-194'),   # Split LT vs CT (cf DN)
    BilanRow('DD', 'Total Dettes Financières et Ressources assimilées', 'DA + DB + DC'),
    BilanRow('DF', 'Total ressources stables', 'CP+DD'),

    # Passif circulant
    BilanRow('DH', 'Dettes circulantes HAO', '471 (solde créditeur),478 (solde créditeur), 485'),
    BilanRow('DI', 'Clients avances reçues', '419'),
    BilanRow('DJ', 'Fournisseurs', '401-408'),
    # DK parent : pas de mapping atomique direct, c'est une composition
    BilanRow('DK', 'Dettes fiscales et sociales', 'DK1+DK2+DK3'),
    BilanRow('DK1', 'Dettes Personnel', '42'),
    BilanRow('DK2', 'Dettes sociales', '43'),
    BilanRow('DK3', 'Dettes fiscales', '44'),
    BilanRow('DM', 'Autres dettes', '45-48 (sauf 471, 478 et 485)'),
    BilanRow('DN', 'Provisions CT', '195-199'),   # Split CT vs LT (cf DC)
    BilanRow('DP', 'Total Passif Circulant', 'Somme DH à DN'),

    # Trésorerie passif
    BilanRow('DQ', 'Banques, crédits d\'escompte', '52 (solde créditeur)'),
    BilanRow('DR', 'Concours bancaires', '519'),
    BilanRow('DT', 'Trésorerie passif', 'DQ + DR'),
    BilanRow('DV', 'Écart conversion passif', '477'),

    # Total passif
    BilanRow('DZ', 'Total passif', 'CP+DF+DP+DT+DV'),
]


# ============================================================
# MÉTADONNÉES DÉRIVÉES
# ============================================================

# Codes parents qui sont des compositions pures (pas de mapping atomique propre).
# Utilisé pour distinguer "rubrique terminale" (avec lookup compte) de "rubrique
# agrégée" (somme de sous-rubriques).
COMPOSITE_ONLY_CODES = {
    'AD', 'AI', 'AQ', 'AZ',          # Totaux actif immobilisé
    'BG', 'BK', 'BT', 'BZ',          # Totaux actif circulant & trésorerie
    'CP',                            # Total capitaux propres
    'DD', 'DF', 'DK', 'DP', 'DT', 'DZ',  # Totaux passif
}

# Subdivisions explicites (un parent → sous-rubriques de plein droit).
# Permet au front d'afficher les sous-totaux DK1/DK2/DK3 sous DK.
BILAN_SUBDIVISIONS_REFERENCE: Dict[str, List[str]] = {
    'DK': ['DK1', 'DK2', 'DK3'],
}
