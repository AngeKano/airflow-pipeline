"""
Parser pour le Grand Livre Comptable Excel.

Version 2 : détection automatique des colonnes via les labels d'en-tête,
plus de positions hardcodées. Le parser tolère donc différentes configurations
d'export Sage (différents intervalles de colonnes selon la version Sage, les
options d'export, la traduction, etc.).

Structure attendue par le parser :
    - 1 ligne d'en-tête contenant les labels : "Date", "C.j" / "Journal",
      "N° pièce", "Libellé écriture" / "Libellé", "Mouvement débit" / "Débit",
      "Mouvement crédit" / "Crédit", "Solde progressif" / "Solde".
      (Tolère les sauts de ligne et accents dans les labels.)
    - Pour chaque compte : 1 ligne d'en-tête `[compte, intitulé]`, suivie de
      ses transactions, suivie d'une ligne "Total compte ...".
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from etl.parsers.base import (
    is_valid, clean, get_cell, compact_row,
    is_date_iso, is_compte_8_digits, is_code_journal,
    is_numeric_amount, contains_total, is_metadata_row,
    parse_amount, format_date_fr, format_date_iso,
    extract_periode_from_date, extract_file_metadata,
    detect_columns_by_header,
)

# Journaux des À-Nouveaux : exemptés de la validation période (reprise N-1).
RAN_JOURNAUX = {'RAN', 'AN'}


# Alias possibles pour chaque rôle de colonne dans le grand livre Excel.
# Les valeurs sont matchées en sous-chaîne (insensible à la casse / sauts de
# ligne / espaces multiples), donc "Mouvement \ndébit" matche "mouvement debit".
_COLUMN_ALIASES: Dict[str, List[str]] = {
    'date': ['date'],
    'code_journal': ['c.j', 'code journal', 'journal'],
    'numero_piece': ['n° pièce', 'n° piece', 'numero piece', 'piece'],
    'libelle': ['libellé écriture', 'libelle ecriture', 'libellé', 'libelle'],
    'debit': ['mouvement débit', 'mouvement debit', 'débit', 'debit'],
    'credit': ['mouvement crédit', 'mouvement credit', 'crédit', 'credit'],
    'solde': ['solde progressif', 'solde'],
    # Colonnes facultatives — peuvent être absentes selon le format Sage
    'n_tiers': ['n° tiers', 'numero tiers', 'compte tiers'],
    'numero_facture': ['n° facture', 'numero facture', 'facture'],
}


def _to_date(val: Union[None, str, date, datetime]) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return pd.to_datetime(val).date()


def _detect_line_type(row: list, col_map: Dict[str, int]) -> str:
    """
    Détecte le type d'une ligne du grand livre selon le mapping de colonnes :
    - 'compte'      : ligne d'en-tête de compte (compte + intitulé)
    - 'transaction' : ligne d'écriture (date + code journal)
    - 'total'       : ligne de total (à ignorer)
    - 'skip'        : ligne à ignorer (vide, métadonnée, en-tête, etc.)
    """
    if not row:
        return 'skip'
    if contains_total(row):
        return 'total'

    date_col = col_map.get('date')
    journal_col = col_map.get('code_journal')

    if date_col is not None and journal_col is not None:
        date_val = get_cell(row, date_col)
        journal_val = get_cell(row, journal_col)
        if is_date_iso(date_val) and journal_val and 2 <= len(journal_val) <= 5:
            return 'transaction'

    # Ligne de compte : col 0 = numéro de compte (1 à 8 chiffres), pas un code
    # journal en col 1 (sinon ça serait une transaction).
    col0 = get_cell(row, 0)
    col1 = get_cell(row, 1)
    if is_compte_8_digits(col0) and not is_date_iso(col0) and not is_code_journal(col1):
        return 'compte'

    return 'skip'


def _extract_compte(row: list) -> Dict[str, str]:
    """Extrait (numéro, intitulé) depuis une ligne d'en-tête de compte."""
    values = compact_row(row)
    numero = ""
    intitule = ""

    for val in values:
        if is_compte_8_digits(val):
            numero = val
            break

    found_numero = False
    for val in values:
        if is_compte_8_digits(val):
            found_numero = True
            continue
        if found_numero and val and not is_numeric_amount(val):
            intitule = val
            break

    return {'numero': numero, 'intitule': intitule}


def _cell_near(row: list, target_col: Optional[int], max_offset: int = 2) -> str:
    """
    Récupère la 1ère valeur non-vide dans une fenêtre [target - max_offset,
    target + max_offset]. Utile pour les exports Sage Excel où les cellules
    fusionnées créent un décalage entre la col du header et la col de la
    valeur effective.
    """
    if target_col is None or target_col < 0:
        return ""
    # On essaie la position exacte d'abord, puis -1, +1, -2, +2 (élargissement
    # progressif). Le 1er hit gagne.
    for offset in range(max_offset + 1):
        for sign in (0,) if offset == 0 else (-1, 1):
            col = target_col + sign * offset
            if 0 <= col < len(row):
                val = get_cell(row, col)
                if val:
                    return val
    return ""


def _attribute_amounts(
    row: list,
    col_map: Dict[str, int],
) -> Tuple[float, float, float]:
    """
    Attribue les valeurs numériques de la ligne à debit/credit/solde selon
    la proximité de leur colonne aux positions détectées dans le header.

    Gère les exports Sage où les montants sont décalés par rapport aux labels
    d'en-tête à cause des cellules fusionnées.
    """
    debit_col = col_map.get('debit', -1)
    credit_col = col_map.get('credit', -1)
    solde_col = col_map.get('solde', -1)

    # Bornes pour ignorer les nombres avant la zone des montants (date, n° pièce
    # qui peut être numérique, etc.)
    min_amount_col = min(c for c in (debit_col, credit_col, solde_col) if c >= 0) - 2 \
        if any(c >= 0 for c in (debit_col, credit_col, solde_col)) else 0

    debit = 0.0
    credit = 0.0
    solde = 0.0

    for col, val in enumerate(row):
        if col < min_amount_col:
            continue
        if not is_valid(val) or not is_numeric_amount(val):
            continue
        amount = parse_amount(val)
        # Distances aux cols connues
        candidates: List[Tuple[int, str]] = []
        if debit_col >= 0:
            candidates.append((abs(col - debit_col), 'debit'))
        if credit_col >= 0:
            candidates.append((abs(col - credit_col), 'credit'))
        if solde_col >= 0:
            candidates.append((abs(col - solde_col), 'solde'))
        if not candidates:
            continue
        candidates.sort()
        best = candidates[0][1]
        # Le solde l'emporte si on est à égalité ou très proche, car il est
        # toujours présent (signé). Sinon premier le plus proche.
        if best == 'debit':
            debit = amount
        elif best == 'credit':
            credit = amount
        else:
            solde = amount

    return debit, credit, solde


def _extract_transaction(row: list, col_map: Dict[str, int]) -> Dict[str, object]:
    """
    Extrait une transaction en se basant sur le mapping de colonnes.

    Stratégie :
    - Date et code journal : position exacte (toujours fiable).
    - Texte (n° pièce, libellé, n° tiers, n° facture) : fenêtre ±2 col autour
      de la position du header pour absorber les décalages dûs aux cellules
      fusionnées.
    - Montants (débit/crédit/solde) : attribution par proximité de colonne,
      gère les décalages variables (cf _attribute_amounts).
    """
    date_raw = get_cell(row, col_map.get('date', 0))
    date_transaction = format_date_fr(date_raw)
    date_iso = format_date_iso(date_raw)

    code_journal = get_cell(row, col_map.get('code_journal', 1))

    numero_piece = _cell_near(row, col_map.get('numero_piece'))
    libelle = _cell_near(row, col_map.get('libelle'), max_offset=2)
    n_tiers = _cell_near(row, col_map.get('n_tiers'))
    numero_facture = _cell_near(row, col_map.get('numero_facture'))

    # Garde-fous : si on a capté une date ou un montant à la place du texte
    if is_date_iso(n_tiers):
        n_tiers = ""
    if is_numeric_amount(numero_piece) and len(numero_piece) > 6:
        # Évite de capter un montant (long nombre) comme pièce
        numero_piece = ""

    debit, credit, solde = _attribute_amounts(row, col_map)

    return {
        'date_transaction': date_transaction,
        'date_iso': date_iso,
        'code_journal': code_journal,
        'numero_piece': numero_piece,
        'numero_facture': numero_facture,
        'libelle': libelle,
        'n_tiers': n_tiers,
        'debit': debit,
        'credit': credit,
        'solde': solde,
    }


def parse_grand_livre(
    file_path: str,
    client_id: str,
    batch_id: str,
    period_start: Union[None, str, date, datetime] = None,
    period_end: Union[None, str, date, datetime] = None,
) -> Dict:
    """
    Parse le Grand Livre Comptable Excel.

    Détecte automatiquement la disposition des colonnes via les labels
    d'en-tête. Si fournis, period_start/period_end activent la validation
    bloquante de période (toute date hors-range hors RAN lève ValueError).

    Returns: {data, entite, periode, date_extraction, stats, metadata}
    """
    print(f"📄 Lecture du Grand Livre: {file_path}")

    period_start_d = _to_date(period_start)
    period_end_d = _to_date(period_end)

    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()

    # Métadonnées (entité, période détectée, etc.)
    metadata = extract_file_metadata(data_list, client_id)
    entite = metadata['entite']
    date_gl = metadata['date_extraction']

    # Détection automatique des colonnes via les labels d'en-tête
    header_idx, col_map = detect_columns_by_header(
        data_list,
        _COLUMN_ALIASES,
        max_rows=20,
        min_matches=4,  # exiger au moins date + code_journal + debit + credit
    )

    if header_idx < 0 or 'date' not in col_map or 'code_journal' not in col_map:
        raise ValueError(
            f"Impossible de détecter les colonnes du grand livre dans {file_path}. "
            f"Vérifier que la ligne d'en-tête contient au moins "
            f"'Date', 'C.j', 'Mouvement débit/crédit'."
        )

    print(f"  📋 Entité: {entite}")
    print(f"  📋 Header détecté ligne {header_idx + 1}, colonnes: {col_map}")

    results: List[Tuple] = []
    stats = {
        'nb_comptes': 0,
        'nb_transactions': 0,
        'nb_avec_tiers': 0,
        'nb_avec_facture': 0,
        'total_debit': 0.0,
        'total_credit': 0.0,
    }

    compte_courant = {'numero': '', 'intitule': ''}
    row_id = 0
    date_min: Optional[date] = None
    date_max: Optional[date] = None

    # On ignore toutes les lignes jusqu'à la ligne d'en-tête (inclus) :
    # le bloc data commence après.
    start_idx = header_idx + 1

    for i in range(start_idx, len(data_list)):
        row = data_list[i]
        line_type = _detect_line_type(row, col_map)

        if line_type == 'compte':
            compte_courant = _extract_compte(row)
            stats['nb_comptes'] += 1

        elif line_type == 'transaction':
            trans = _extract_transaction(row, col_map)

            # Validation période — RAN exempté (reprise N-1)
            if period_start_d and period_end_d and trans['date_iso']:
                code_journal = (trans['code_journal'] or '').upper()
                if code_journal not in RAN_JOURNAUX:
                    try:
                        d_trans = datetime.strptime(trans['date_iso'], '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        d_trans = None
                    if d_trans and (d_trans < period_start_d or d_trans > period_end_d):
                        raise ValueError(
                            f"Ligne {i + 1}: date {d_trans.isoformat()} hors période "
                            f"[{period_start_d.isoformat()}, {period_end_d.isoformat()}] "
                            f"(journal {code_journal}, compte {compte_courant.get('numero', '?')})"
                        )

            row_id += 1

            results.append((
                date_gl,
                entite,
                compte_courant['numero'],
                compte_courant['intitule'],
                trans['date_transaction'],
                trans['code_journal'],
                trans['numero_piece'],
                trans['numero_facture'],
                trans['libelle'],
                trans['n_tiers'],
                trans['debit'],
                trans['credit'],
                trans['solde'],
                '',  # periode, remplie plus bas
                batch_id,
                row_id,
            ))

            stats['nb_transactions'] += 1
            stats['total_debit'] += trans['debit']
            stats['total_credit'] += trans['credit']

            if trans['n_tiers']:
                stats['nb_avec_tiers'] += 1
            if trans['numero_facture']:
                stats['nb_avec_facture'] += 1

            # Tracking min/max date pour la période détectée
            if trans['date_iso']:
                try:
                    d = datetime.strptime(trans['date_iso'], '%Y-%m-%d').date()
                    if date_min is None or d < date_min:
                        date_min = d
                    if date_max is None or d > date_max:
                        date_max = d
                except (ValueError, TypeError):
                    pass

        # 'total' et 'skip' → ignorés

    # Période détectée : YYYYMM de la date max si dispo, sinon métadonnée
    if date_max:
        periode = date_max.strftime('%Y%m')
    else:
        periode = metadata.get('periode') or pd.Timestamp.now().strftime('%Y%m')

    # Réinjection de la période dans chaque tuple (col 13)
    results = [
        row[:13] + (periode,) + row[14:]
        for row in results
    ]

    stats['equilibre'] = abs(stats['total_debit'] - stats['total_credit']) < 0.01

    print(f"  ✓ {stats['nb_comptes']} comptes")
    print(f"  ✓ {stats['nb_transactions']} transactions")
    pct_tiers = 100 * stats['nb_avec_tiers'] / max(1, stats['nb_transactions'])
    pct_fact = 100 * stats['nb_avec_facture'] / max(1, stats['nb_transactions'])
    print(f"  ✓ {stats['nb_avec_tiers']} avec N° tiers ({pct_tiers:.1f}%)")
    print(f"  ✓ {stats['nb_avec_facture']} avec N° facture ({pct_fact:.1f}%)")
    print(f"  ✓ Période: {periode} "
          f"({date_min.isoformat() if date_min else 'n/a'} "
          f"→ {date_max.isoformat() if date_max else 'n/a'})")
    print(f"  ✓ Débit total: {stats['total_debit']:,.2f} | "
          f"Crédit total: {stats['total_credit']:,.2f}")
    print(f"  ✓ Équilibre: {'✅ OK' if stats['equilibre'] else '❌ Déséquilibre'}")

    return {
        'data': results,
        'entite': entite,
        'periode': periode,
        'date_extraction': date_gl,
        'stats': stats,
        'metadata': metadata,
    }
