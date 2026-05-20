"""
Parser pour les fichiers Sage .pnc (Plan des comptes auxiliaires / Plan Tiers).

Format texte largeur fixe, CP1252, CRLF. Première ligne = nom société.
Chaque ligne suivante = un tiers (client ou fournisseur).

Positions des champs (validées sur COMEBCI.pnc, 110 tiers) :
    [0:13]    code_tiers (13 chars)
    [13:37]   nom_tiers (24 chars)
    [37:50]   code_tiers (rappel, 13 chars — ignoré, doublon de [0:13])
    [50:62]   compte_general_rattachement (12 chars)

Le type (Client/Fournisseur/Autre) n'est pas dans le fichier. Il est déduit
par la racine du compte général de rattachement :
    - 411x → Client
    - 401x → Fournisseur
    - autre → Autre

Sortie alignée sur parse_plan_tiers Excel : tuples (compte_tiers, type, intitule_tiers).
"""
from typing import Dict, List, Tuple


# ------------------------------------------------------------------
# Déduction du type tiers
# ------------------------------------------------------------------

def _deduire_type_tiers(compte_rattachement: str) -> str:
    """
    Déduit Client/Fournisseur/Autre depuis le compte de rattachement.

    Les racines 401 (Fournisseurs) et 411 (Clients) sont identiques en PCG
    et en SYSCOHADA — l'heuristique est donc plan-agnostique.
    """
    c = (compte_rattachement or '').strip()
    if not c:
        return 'Autre'
    if c.startswith('411'):
        return 'Client'
    if c.startswith('401'):
        return 'Fournisseur'
    return 'Autre'


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

def parse_sage_pnc(file_path: str, client_id: str) -> Dict:
    """
    Parse un fichier .pnc (Plan Tiers Sage).

    Args:
        file_path: chemin local du .pnc
        client_id: ID client (fallback pour l'entité)

    Returns:
        {
          'data':   [(compte_tiers, type, intitule_tiers)],
          'entite': str,
          'stats':  {total, clients, fournisseurs, autres, nb_lignes_ignorees},
        }
    """
    print(f"📄 Lecture Sage PNC: {file_path}")

    with open(file_path, 'r', encoding='cp1252') as f:
        lines = f.read().splitlines()

    if not lines:
        raise ValueError(f"Fichier PNC vide: {file_path}")

    entite = lines[0].strip() or client_id

    results: List[Tuple[str, str, str]] = []
    seen_codes: set = set()  # déduplication sur code_tiers
    stats = {
        'total': 0,
        'clients': 0,
        'fournisseurs': 0,
        'autres': 0,
        'nb_lignes_ignorees': 0,
    }

    for i, ligne in enumerate(lines[1:], start=2):
        if len(ligne) < 62:
            stats['nb_lignes_ignorees'] += 1
            continue

        code_tiers = ligne[0:13].strip()
        nom_tiers = ligne[13:37].strip()
        compte_rattachement = ligne[50:62].strip()

        # Garde-fou : ligne sans code tiers
        if not code_tiers:
            stats['nb_lignes_ignorees'] += 1
            continue

        # Déduplication (le fichier peut contenir des doublons)
        if code_tiers in seen_codes:
            stats['nb_lignes_ignorees'] += 1
            continue
        seen_codes.add(code_tiers)

        type_tiers = _deduire_type_tiers(compte_rattachement)

        results.append((code_tiers, type_tiers, nom_tiers))

        stats['total'] += 1
        if type_tiers == 'Client':
            stats['clients'] += 1
        elif type_tiers == 'Fournisseur':
            stats['fournisseurs'] += 1
        else:
            stats['autres'] += 1

    print(f"  ✓ Entité: {entite}")
    print(f"  ✓ {stats['total']} tiers ({stats['clients']} Clients, "
          f"{stats['fournisseurs']} Fournisseurs, {stats['autres']} Autres)")
    if stats['nb_lignes_ignorees']:
        print(f"  ⚠️ {stats['nb_lignes_ignorees']} lignes ignorées")

    return {
        'data': results,
        'entite': entite,
        'stats': stats,
    }
