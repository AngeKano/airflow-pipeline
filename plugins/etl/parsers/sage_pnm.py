"""
Parser pour les fichiers Sage .pnm (Format Trésorerie / Grand Livre Sage 100).

Format texte largeur fixe, CP1252, CRLF. Première ligne = nom société.
Chaque ligne suivante = une écriture comptable.

Positions des champs (validées sur ENVOL_T.pnm, 2333 écritures) :
    [0:3]     code_journal
    [3:9]     date_ecriture (JJMMAA)
    [9:11]    type_piece
    [11:24]   compte_general (PCG, 13 chars)
    [24:25]   marqueur_tiers ('X' ou ' ')
    [25:38]   compte_tiers (13 chars, peut être vide)
    [38:50]   reference_piece (12 chars)
    [51:76]   libelle (25 chars)
    [77:83]   date_echeance (JJMMAA ou vide)
    [83:84]   sens ('D' ou 'C')
    [84:104]  montant (20 chars, right-aligned, unités entières en XOF)
    [104:105] type_ecriture ('N' = normale)
    [105:110] num_ligne_sage (5 chars)

Sortie alignée sur parse_grand_livre Excel (16 colonnes) afin de pouvoir
réutiliser enrich_grand_livre et upsert_grand_livre tels quels.
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd


# ------------------------------------------------------------------
# Helpers de parsing bas niveau
# ------------------------------------------------------------------

def _parse_date_jjmmaa(raw: str) -> Optional[date]:
    """JJMMAA Sage → date Python. Retourne None si vide ou invalide."""
    s = (raw or '').strip()
    if len(s) != 6 or not s.isdigit():
        return None
    jj, mm, aa = s[:2], s[2:4], s[4:6]
    try:
        return date(2000 + int(aa), int(mm), int(jj))
    except ValueError:
        return None


def _format_date_fr(d: Optional[date]) -> str:
    return d.strftime('%d/%m/%Y') if d else ''


def _parse_montant(raw: str) -> int:
    """Montant Sage (unités entières XOF). Retourne 0 si invalide."""
    s = (raw or '').strip()
    if not s:
        return 0
    try:
        return int(s)
    except ValueError:
        return 0


def _to_date(val: Union[None, str, date, datetime]) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return pd.to_datetime(val).date()


# ------------------------------------------------------------------
# Parser
# ------------------------------------------------------------------

# Journal des À-Nouveaux : reprise des soldes de l'exercice précédent.
# Sage utilise 'RAN' ; certaines variantes utilisent 'AN'. On exempte les deux.
RAN_JOURNAUX = {'RAN', 'AN'}


def parse_sage_pnm(
    file_path: str,
    client_id: str,
    batch_id: str,
    period_start: Union[None, str, date, datetime] = None,
    period_end: Union[None, str, date, datetime] = None,
) -> Dict:
    """
    Parse un fichier .pnm (Grand Livre Sage).

    Args:
        file_path: chemin local du .pnm
        client_id: ID client (utilisé comme fallback pour l'entité)
        batch_id: ID batch (injecté dans chaque ligne)
        period_start / period_end: dates de la période comptable.
            Si fournies, toute écriture (hors journal RAN) dont la date_ecriture
            sort de [period_start, period_end] lève ValueError au 1er détecté.

    Returns:
        {
          'data':    [tuple à 16 colonnes alignées sur parse_grand_livre Excel],
          'entite':  str,
          'periode': str (YYYYMM),
          'stats':   {...},
          'metadata': {...},
          'comptes_pcg': List[str] (utilisé pour detect_plan_source),
        }

    Raises:
        ValueError: si une transaction est hors période (hors RAN).
    """
    print(f"📄 Lecture Sage PNM: {file_path}")

    period_start_d = _to_date(period_start)
    period_end_d = _to_date(period_end)

    with open(file_path, 'r', encoding='cp1252') as f:
        lines = f.read().splitlines()

    if not lines:
        raise ValueError(f"Fichier PNM vide: {file_path}")

    entite = lines[0].strip() or client_id

    results: List[Tuple] = []
    comptes_pcg_set: set = set()
    stats = {
        'nb_lignes_lues': 0,
        'nb_lignes_ignorees': 0,
        'nb_transactions': 0,
        'nb_avec_tiers': 0,
        'nb_ran': 0,
        'total_debit': 0,
        'total_credit': 0,
        'date_min': None,
        'date_max': None,
    }

    row_id = 0

    for i, ligne in enumerate(lines[1:], start=2):
        stats['nb_lignes_lues'] += 1

        if len(ligne) < 110:
            stats['nb_lignes_ignorees'] += 1
            continue

        code_journal = ligne[0:3].strip()
        date_raw = ligne[3:9]
        compte_general = ligne[11:24].strip()
        compte_tiers = ligne[25:38].strip()
        reference = ligne[38:50].strip()
        libelle = ligne[51:76].strip()
        sens = ligne[83:84].strip()
        montant_raw = ligne[84:104]

        date_ecriture = _parse_date_jjmmaa(date_raw)

        # Garde-fou : ligne incomplète (pas de date ou pas de compte)
        if date_ecriture is None or not compte_general:
            stats['nb_lignes_ignorees'] += 1
            continue

        # Validation période — RAN exempté
        is_ran = code_journal in RAN_JOURNAUX
        if is_ran:
            stats['nb_ran'] += 1
        elif period_start_d and period_end_d:
            if date_ecriture < period_start_d or date_ecriture > period_end_d:
                raise ValueError(
                    f"Ligne {i}: date {date_ecriture.isoformat()} hors période "
                    f"[{period_start_d.isoformat()}, {period_end_d.isoformat()}] "
                    f"(journal {code_journal}, compte {compte_general})"
                )

        montant = _parse_montant(montant_raw)
        debit = montant if sens == 'D' else 0
        credit = montant if sens == 'C' else 0

        row_id += 1
        comptes_pcg_set.add(compte_general)

        # Tuple aligné sur parse_grand_livre Excel (16 colonnes) :
        # (date_gl, entite, compte, intitule_compte, date_trans, code_journal,
        #  numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
        #  periode, batch_id, row_id)
        # - date_gl : date d'extraction (non disponible en PNM → date du jour)
        # - intitule_compte : sera enrichi par enrich_grand_livre
        # - numero_facture : non distingué de numero_piece en PNM → ''
        # - solde : 0 (le pipeline existant ne calcule pas le solde par ligne)
        # - periode : injectée plus bas (après détection min/max)
        results.append((
            datetime.now().strftime('%d/%m/%Y'),  # date_gl
            entite,
            compte_general,
            '',                                    # intitule_compte
            _format_date_fr(date_ecriture),       # date_trans
            code_journal,
            reference,                             # numero_piece
            '',                                    # numero_facture
            libelle,
            compte_tiers,                          # n_tiers
            float(debit),
            float(credit),
            0.0,                                   # solde
            '',                                    # periode (rempli après)
            batch_id,
            row_id,
        ))

        stats['nb_transactions'] += 1
        stats['total_debit'] += debit
        stats['total_credit'] += credit
        if compte_tiers:
            stats['nb_avec_tiers'] += 1

        if stats['date_min'] is None or date_ecriture < stats['date_min']:
            stats['date_min'] = date_ecriture
        if stats['date_max'] is None or date_ecriture > stats['date_max']:
            stats['date_max'] = date_ecriture

    # Période : YYYYMM de la date max (fin d'exercice). Cohérent avec
    # extract_periode_from_date côté Excel.
    if stats['date_max']:
        periode = stats['date_max'].strftime('%Y%m')
    else:
        periode = datetime.now().strftime('%Y%m')

    # Réinjection de la période dans les tuples (col 13)
    results = [
        row[:13] + (periode,) + row[14:]
        for row in results
    ]

    stats['equilibre'] = stats['total_debit'] == stats['total_credit']

    print(f"  ✓ Entité: {entite}")
    print(f"  ✓ {stats['nb_transactions']} transactions ({stats['nb_lignes_ignorees']} lignes ignorées)")
    print(f"  ✓ {stats['nb_avec_tiers']} avec tiers, {stats['nb_ran']} en RAN")
    print(f"  ✓ Période détectée: {periode} "
          f"({stats['date_min'].isoformat() if stats['date_min'] else 'n/a'} "
          f"→ {stats['date_max'].isoformat() if stats['date_max'] else 'n/a'})")
    print(f"  ✓ Débit total: {stats['total_debit']:,} | Crédit total: {stats['total_credit']:,}")
    print(f"  ✓ Équilibre: {'✅' if stats['equilibre'] else '❌'}")

    return {
        'data': results,
        'entite': entite,
        'periode': periode,
        'stats': stats,
        'comptes_pcg': sorted(comptes_pcg_set),
        'metadata': {
            'entite': entite,
            'periode': periode,
            'date_min': stats['date_min'].isoformat() if stats['date_min'] else None,
            'date_max': stats['date_max'].isoformat() if stats['date_max'] else None,
            'source_format': 'sage_pnm',
        },
    }
