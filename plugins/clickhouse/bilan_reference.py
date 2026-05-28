"""
Référentiel SYSCOHADA RÉVISÉ du bilan — source de vérité Python.

Version validée 2026-05-21 par l'utilisateur, étendue avec :
- Amortissements (codes XX1)
- Provisions pour dépréciation (codes XX2)
- Subdivisions BS (BSA caisse, BSB banques, BSC autres trésoreries)
- Codes annexes RPCP, RPCF, CCA, PCA
- DK et BS deviennent des compositions pures (sans mapping atomique direct)
- Suppression des filtres soldes (déterministe par racine)

Régénération des constantes dans config.py :
    python tools/generate_bilan_constants.py
"""
from typing import Dict, List, NamedTuple


class BilanRow(NamedTuple):
    """Une ligne du référentiel bilan."""
    code: str
    libelle: str
    expression: str


# ============================================================
# RÉFÉRENTIEL VALIDÉ — 85+ rubriques (validation utilisateur 2026-05-21)
# ============================================================
BILAN_REFERENCE: List[BilanRow] = [
    # ---- Actif immobilisé : Immobilisations incorporelles ----
    BilanRow('AD', 'Immobilisations incorporelles', 'AE+AF+AG+AH'),
    BilanRow('AD1', 'Amortissement des immobilisations incorporelles', 'AE1+AF1+AG1+AH1'),
    BilanRow('AD2', 'Provisions pour dépréciation des immobilisations incorporelles', 'AF2+AG2+AH2'),
    BilanRow('AE', 'Frais développement', '211;2191'),
    BilanRow('AE1', 'Amortissement des frais de recherche et de développement', '2811'),
    BilanRow('AF', 'Brevets licences logiciels', '212;213;2193;214'),
    BilanRow('AF1', 'Amortissement des brevets, licences, concessions et droits similaires, logiciels', '2812;2813;2814'),
    BilanRow('AF2', 'Provisions pour dépréciation des brevets, licences, concessions et droits similaires', '2912;2913;2914'),
    BilanRow('AG', 'Fonds commercial', '215;216'),
    BilanRow('AG1', 'Amortissement du fonds commercial et droit au bail', '2815;2816'),
    BilanRow('AG2', 'Provisions pour dépréciation fonds commercial et droit au bail', '2915;2916'),
    BilanRow('AH', 'Autres incorporelles', '217;218;2198'),
    BilanRow('AH1', 'Amortissement des biens incorporels', '2817;2818'),
    BilanRow('AH2', 'Provisions pour dépréciation autres droits et valeurs', '2917;2918;2919'),

    # ---- Actif immobilisé : Immobilisations corporelles ----
    BilanRow('AI', 'Immobilisations corporelles', 'AJ+AK+AL+AM+AN+AP'),
    BilanRow('AI1', 'Amortissement des immobilisations corporelles', 'AJ1+AKL1+AM1+AN1'),
    BilanRow('AI2', 'Provisions pour dépréciation des immobilisations corporelles', 'AJ2+AKL2+AMN+AP2'),
    BilanRow('AJ', 'Terrains', '22'),
    BilanRow('AJ1', 'Amortissement des terrains', '282'),
    BilanRow('AJ2', 'Provisions pour dépréciation des terrains', '292'),
    BilanRow('AK', 'Bâtiments', '231;232;237;239'),
    BilanRow('AL', 'Installations', '233;235;234;238'),
    BilanRow('AKL1', 'Amortissements des bâtiments, installations techniques et agencements', '283'),
    BilanRow('AKL2', 'Provisions pour dépréciation des bâtiments, installations techniques et agencements', '293'),
    BilanRow('AM', 'Matériel', '241;242;243;244;246;247;248;2491-2494;2496;2497;2498'),
    BilanRow('AM1', 'Amortissement du matériel', '284 sauf 2845'),
    BilanRow('AN', 'Transport', '245;2495'),
    BilanRow('AN1', 'Amortissement du matériel de transport', '2845'),
    BilanRow('AMN', 'Provisions pour dépréciation de matériel', '294'),
    BilanRow('AP', 'Avances immobilisations', '25'),
    BilanRow('AP2', 'Provisions pour dépréciation des avances et acomptes sur immobilisations', '295'),

    # ---- Actif immobilisé : Immobilisations financières ----
    BilanRow('AQ', 'Immobilisations financières', 'AR+AS'),
    BilanRow('AR', 'Titres participation', '26'),
    BilanRow('AR2', 'Provisions pour dépréciation des titres de participation', '296'),
    BilanRow('AS', 'Autres financières', '27'),
    BilanRow('AS2', 'Provisions pour dépréciation des autres immobilisations financières', '297'),

    # ---- Total actif immobilisé ----
    BilanRow('AZ', 'Total actif immobilisé', 'AD+AI+AQ'),

    # ---- Actif circulant ----
    BilanRow('BA', 'Actif Circulant HAO', '485;486;488'),
    BilanRow('BB', 'Stocks et Encours', '31-38;39'),
    BilanRow('BG', 'Créances et Emplois Assimilés', 'BH+BI+BJ'),
    BilanRow('BH', 'Avances fournisseurs', '409'),
    BilanRow('BI', 'Clients', '41 sauf 419'),
    BilanRow('BJ', 'Autres créances', '4711;472;475'),
    BilanRow('BK', 'Total Actif Circulant', 'BA+BB+BG'),

    # ---- Trésorerie actif ----
    BilanRow('BQ', 'Titres placement', '50'),
    BilanRow('BQ2', 'Dépréciation des titres de placement', '590'),
    BilanRow('BR', 'Valeurs à encaisser', '51'),
    BilanRow('BR2', 'Dépréciation des valeurs à encaisser', '591'),
    # BS devient une composition pure : BSA + BSB + BSC
    BilanRow('BS', 'Banques, chèques postaux, caisse et assimilés', 'BSA+BSB+BSC'),
    BilanRow('BS2', 'Dépréciation des comptes banques, établissements financiers et assimilés', '592;593;594'),
    BilanRow('BSA', 'Caisse', '57'),
    BilanRow('BSB', 'Banques', '52'),
    BilanRow('BSC', 'Autres trésoreries', '53;54'),
    BilanRow('RPCF', 'Risques provisionnés à caractère financier', '599'),
    BilanRow('BT', 'Total Trésorerie Actif', 'BQ+BR+BS'),
    BilanRow('BU', 'Écart conversion actif', '478'),
    BilanRow('BZ', 'Total actif', 'AZ+BK+BT+BU'),

    # ---- Capitaux propres ----
    BilanRow('CA', 'Capital', '10 (sauf 105;106;109)'),
    BilanRow('CB', 'Capital non appelé', '109'),
    BilanRow('CD', 'Primes liées au capital', '105'),
    BilanRow('CE', 'Écart réévaluation', '106'),
    BilanRow('CF', 'Réserves indisponibles', '111;112;113'),
    BilanRow('CG', 'Réserves libres', '118'),
    BilanRow('CH', 'Report à nouveau', '12'),
    BilanRow('CJ', 'Résultat', '13'),
    BilanRow('CL', 'Subventions', '14'),
    BilanRow('CM', 'Provisions réglementées', '15'),
    BilanRow('CP', 'Total capitaux propres', 'Somme CA à CM'),

    # ---- Dettes financières ----
    BilanRow('DA', 'Emprunts', '16;18'),
    BilanRow('DB', 'Crédit bail', '17'),
    BilanRow('DC', 'Provisions LT', '19'),
    BilanRow('DD', 'Total Dettes Financières et Ressources assimilées', 'DA + DB + DC'),
    BilanRow('DF', 'Total ressources stables', 'CP+DD'),

    # ---- Passif circulant ----
    BilanRow('DH', 'Dettes circulantes HAO', '481;482;483;484'),
    BilanRow('DI', 'Clients avances reçues', '419'),
    BilanRow('DJ', 'Fournisseurs', '401-408'),
    # DK devient une composition pure : DK1 + DK2 + DK3
    BilanRow('DK', 'Dettes fiscales et sociales', 'DK1+DK2+DK3'),
    BilanRow('DK1', 'Dettes Personnel', '42'),
    BilanRow('DK2', 'Dettes sociales', '43'),
    BilanRow('DK3', 'Dettes fiscales', '44'),
    BilanRow('DM', 'Autres dettes', '45;46;4712'),
    BilanRow('DN', 'Provisions pour risques et charges à court terme', '49'),
    BilanRow('DP', 'Total Passif Circulant', 'Somme DH à DN'),

    # ---- Trésorerie passif ----
    BilanRow('DQ', "Banques, crédits d'escompte", '564;565'),
    BilanRow('DR', 'Banques, établissements financiers et crédits de trésorerie', '561;566'),
    BilanRow('DT', 'Trésorerie passif', 'DQ + DR'),
    BilanRow('DV', 'Écart conversion passif', '479'),

    # ---- Total passif ----
    BilanRow('DZ', 'Total passif', 'CP+DF+DP+DT+DV'),

    # ---- Codes annexes (régularisation) ----
    # Hors composition DZ : ce sont des notes annexes
    BilanRow('RPCP', 'Répartition périodique des charges et produits', '474'),
    BilanRow('CCA', "Charges constatées d'avance", '476'),
    BilanRow('PCA', "Produits constatés d'avance", '477'),
]


# ============================================================
# MÉTADONNÉES DÉRIVÉES
# ============================================================

# Codes qui sont des compositions pures (pas de mapping atomique propre).
# Le lookup d'un compte ne renverra JAMAIS un de ces codes — ils sont
# uniquement utilisés au niveau du reporting via BILAN_COMPOSITION.
COMPOSITE_ONLY_CODES = {
    # Totaux
    'AD', 'AI', 'AQ', 'AZ',
    'AD1', 'AD2', 'AI1', 'AI2',
    'BG', 'BK', 'BT', 'BZ',
    'CP',
    'DD', 'DF', 'DP', 'DT', 'DZ',
    # Subdivisions parent (DK, BS) qui n'ont QUE des sous-rubriques
    'DK', 'BS',
}

# Subdivisions explicites (un parent → sous-rubriques de plein droit).
# Permet au front d'afficher les sous-totaux DK1/2/3 sous DK ou BSA/B/C sous BS.
BILAN_SUBDIVISIONS_REFERENCE: Dict[str, List[str]] = {
    'DK': ['DK1', 'DK2', 'DK3'],
    'BS': ['BSA', 'BSB', 'BSC'],
}

# Codes annexes : hors composition DZ mais documentés comme rubriques bilan.
# Ces codes peuvent être utilisés pour des notes complémentaires aux états.
BILAN_ANNEXES = {
    'RPCP': 'Répartition périodique des charges et produits',
    'CCA': "Charges constatées d'avance",
    'PCA': "Produits constatés d'avance",
    'RPCF': 'Risques provisionnés à caractère financier',
}
