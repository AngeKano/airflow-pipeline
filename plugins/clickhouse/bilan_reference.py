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
    BilanRow('AE', 'Frais développement', '211;2191;2181'),
    BilanRow('AE1', 'Amortissement des frais de recherche et de développement', '2811;2818'),
    BilanRow('AE2', 'Dépréciation des frais de recherche et de développement', '2911;2918;2919'),
    BilanRow('AF', 'Brevets licences logiciels', '212;213;2193;214'),
    BilanRow('AF1', 'Amortissement des brevets, licences, concessions et droits similaires, logiciels', '2812;2813;2814'),
    BilanRow('AF2', 'Provisions pour dépréciation des brevets, licences, concessions et droits similaires', '2912;2913;2914'),
    BilanRow('AG', 'Fonds commercial', '215;216'),
    BilanRow('AG1', 'Amortissement du fonds commercial et droit au bail', '2815;2816'),
    BilanRow('AG2', 'Provisions pour dépréciation fonds commercial et droit au bail', '2915;2916'),
    BilanRow('AH', 'Autres incorporelles', '217;2182;2183;2184;2188;2198'),
    BilanRow('AH1', 'Amortissement des biens incorporels', '2817'),
    BilanRow('AH2', 'Provisions pour dépréciation autres droits et valeurs', '2917'),

    # ---- Actif immobilisé : Immobilisations corporelles ----
    # Éclatement des codes fusionnés bâtiments+installations (ex-AKL1/AKL2/AMN)
    # en codes séparés AK1/AK2 (bâtiments) et AL1/AL2 (installations), + AM2/AN2.
    BilanRow('AI', 'Immobilisations corporelles', 'AJ+AK+AL+AM+AN+AP'),
    BilanRow('AI1', 'Amortissement des immobilisations corporelles', 'AJ1+AK1+AL1+AM1+AN1'),
    BilanRow('AI2', 'Provisions pour dépréciation des immobilisations corporelles', 'AJ2+AK2+AL2+AM2+AN2+AP2'),
    BilanRow('AJ', 'Terrains', '22'),
    BilanRow('AJ1', 'Amortissement des terrains', '282'),
    BilanRow('AJ2', 'Provisions pour dépréciation des terrains', '292'),
    BilanRow('AK', 'Bâtiments', '231;232;233;237;2391'),
    BilanRow('AK1', 'Amortissements des bâtiments', '2831;2832;2833;2837'),
    BilanRow('AK2', 'Provisions pour dépréciation des bâtiments', '2931;2932;2933;2937;2939'),
    BilanRow('AL', 'Installations', '235;234;238;2392;2393;2394;2395;2398'),
    BilanRow('AL1', 'Amortissements des installations techniques et agencements', '2835;2834;2838'),
    BilanRow('AL2', 'Provisions pour dépréciation des installations techniques et agencements', '2934;2935;2938'),
    BilanRow('AM', 'Matériel', '241;242;243;244;246;247;248;2491-2494;2496;2497;2498'),
    BilanRow('AM1', 'Amortissement du matériel', '2841;2842;2843;2844;2846;2847;2848'),
    BilanRow('AM2', 'Dépréciation des autres matériels', '2941;2942;2943;2944;2946;2947;2948;2949'),
    BilanRow('AN', 'Transport', '245;2495'),
    BilanRow('AN1', 'Amortissement du matériel de transport', '2845'),
    BilanRow('AN2', 'Dépréciation du matériel de transport', '2945'),
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
    BilanRow('BA', 'Actif Circulant HAO', '485;488'),
    BilanRow('BA1', 'Dépréciations Actif Circulant HAO', '498'),
    BilanRow('BB', 'Stocks et Encours', '31-38'),
    BilanRow('BB1', 'Dépréciations Stocks et Encours', '39'),
    BilanRow('BG', 'Créances et Emplois Assimilés', 'BH+BI+BJ'),
    BilanRow('BH', 'Avances fournisseurs', '409'),
    BilanRow('BH1', 'Dépréciation fournisseurs avances versées', '490'),
    BilanRow('BI', 'Clients', '411;412;413;414;415;416;418'),
    BilanRow('BI1', 'Dépréciations clients', '491'),
    # BJ : autres créances = soldes DÉBITEURS des comptes de tiers à solde variable.
    BilanRow('BJ', 'Autres créances', '(solde débiteur) 185;42;43;44;45;46;471;472;473;474;475;476;477'),
    BilanRow('BJ1', 'Dépréciations autres créances', '492;493;494;495;496;497'),
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
    BilanRow('BSB', 'Banques', '(solde débiteur) 52'),
    BilanRow('BSC', 'Autres trésoreries', '(solde débiteur) 53;54;55;581;582'),
    BilanRow('BT', 'Total Trésorerie Actif', 'BQ+BR+BS'),
    BilanRow('BU', 'Écart conversion actif', '478'),
    BilanRow('BZ', 'Total actif', 'AZ+BK+BT+BU'),

    # ---- Capitaux propres ----
    BilanRow('CA', 'Capital', '101;102;103;104'),
    BilanRow('CB', 'Capital non appelé', '109'),
    BilanRow('CD', 'Primes liées au capital', '105'),
    BilanRow('CE', 'Écart réévaluation', '106'),
    BilanRow('CF', 'Réserves indisponibles', '111;112;113'),
    BilanRow('CG', 'Réserves libres', '118'),
    BilanRow('CH', 'Report à nouveau', '12'),
    BilanRow('CJ', 'Résultat', '131;139'),
    BilanRow('CL', 'Subventions', '14'),
    BilanRow('CM', 'Provisions réglementées', '15'),
    BilanRow('CP', 'Total capitaux propres', 'Somme CA à CM'),

    # ---- Dettes financières ----
    BilanRow('DA', 'Emprunts', '16;181;182;183;184'),
    BilanRow('DB', 'Crédit bail', '17'),
    BilanRow('DC', 'Provisions LT', '19'),
    BilanRow('DD', 'Total Dettes Financières et Ressources assimilées', 'DA + DB + DC'),
    BilanRow('DF', 'Total ressources stables', 'CP+DD'),

    # ---- Passif circulant ----
    BilanRow('DH', 'Dettes circulantes HAO', '481;482;484;4998'),
    BilanRow('DI', 'Clients avances reçues', '419'),
    BilanRow('DJ', 'Fournisseurs', '401-408'),
    # DK devient une composition pure : DK1 + DK2 + DK3
    # DK1/DK2/DK3 : soldes CRÉDITEURS des comptes de tiers à solde variable
    # (le solde débiteur de 42/43/44 est classé en BJ, actif).
    BilanRow('DK', 'Dettes fiscales et sociales', 'DK1+DK2+DK3'),
    BilanRow('DK1', 'Dettes Personnel', '(solde créditeur) 42'),
    BilanRow('DK2', 'Dettes sociales', '(solde créditeur) 43'),
    BilanRow('DK3', 'Dettes fiscales', '(solde créditeur) 44'),
    # DM : autres dettes = soldes CRÉDITEURS des comptes de tiers à solde variable.
    BilanRow('DM', 'Autres dettes', '(solde créditeur) 185;45;46;471;472;473;474;475;476;477'),
    BilanRow('DN', 'Provisions pour risques et charges à court terme', '4991;4997;599'),
    BilanRow('DP', 'Total Passif Circulant', 'Somme DH à DN'),

    # ---- Trésorerie passif ----
    BilanRow('DQ', "Banques, crédits d'escompte", '564;565'),
    BilanRow('DR', 'Banques, établissements financiers et crédits de trésorerie', '(solde créditeur) 52;53;561;566'),
    BilanRow('DT', 'Trésorerie passif', 'DQ + DR'),
    BilanRow('DV', 'Écart conversion passif', '479'),

    # ---- Total passif ----
    # DF contient déjà CP → CP retiré de DZ pour éviter le double comptage.
    BilanRow('DZ', 'Total passif', 'DF+DP+DT+DV'),

    # NB : les ex-codes annexes RPCP (474), CCA (476), PCA (477) et RPCF (599)
    # sont supprimés. 474/475/476/477 sont désormais classés par sens de solde
    # dans BJ (débiteur) / DM (créditeur) ; 599 est repris dans DN.
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
# Vidé après la révision : RPCP/CCA/PCA/RPCF supprimés (comptes reclassés par
# sens de solde dans BJ/DM, et 599 repris dans DN).
BILAN_ANNEXES: Dict[str, str] = {}
