"""
Parser pour le Grand Livre Comptable (GRAND_LIVRE_COMPTABLE.xlsx)
Fichier unique contenant les comptes, transactions, tiers et factures
Extraction robuste par patterns - ignore les colonnes vides
"""
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from etl.parsers.base import (
    is_valid, clean, get_cell, compact_row, get_values_only,
    is_date_iso, is_compte_8_digits, is_code_journal,
    is_numeric_amount, contains_total, is_metadata_row,
    parse_amount, format_date_fr, format_date_iso,
    extract_periode_from_date, extract_file_metadata
)

# Journaux des À-Nouveaux : exemptés de la validation période (reprise N-1).
RAN_JOURNAUX = {'RAN', 'AN'}


def _to_date(val: Union[None, str, date, datetime]) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return pd.to_datetime(val).date()


def detect_line_type(row: list) -> str:
    """
    Détecte le type de ligne:
    - 'compte': Ligne d'en-tête de compte (numéro + intitulé)
    - 'transaction': Ligne de transaction (date + code journal + ...)
    - 'total': Ligne de total
    - 'skip': Ligne à ignorer
    """
    if not row:
        return 'skip'
    
    # Vérifier Total en premier
    if contains_total(row):
        return 'total'
    
    col0 = get_cell(row, 0)
    col1 = get_cell(row, 1)
    col2 = get_cell(row, 2)
    
    # Ligne de compte: Col0 = 6 chiffres, Col1 vide ou pas code journal, Col2 = intitulé
    if is_compte_8_digits(col0) and not is_date_iso(col0):
        if not is_code_journal(col1):
            return 'compte'
    
    # Ligne de transaction: Col0 = date ISO, Col1 = code journal
    if is_date_iso(col0):
        if col1 and len(col1) >= 2 and len(col1) <= 5:
            return 'transaction'
    
    return 'skip'


def extract_compte_from_row(row: list) -> Dict[str, str]:
    """
    Extrait les infos d'une ligne de compte.
    Structure: [numero_compte, ?, intitule, ...]
    """
    values = compact_row(row)
    
    numero = ""
    intitule = ""
    
    # Le premier élément devrait être le numéro de compte
    for val in values:
        if is_compte_8_digits(val):
            numero = val
            break
    
    # L'intitulé est généralement le texte après le numéro
    found_numero = False
    for val in values:
        if is_compte_8_digits(val):
            found_numero = True
            continue
        if found_numero and val and not is_numeric_amount(val):
            intitule = val
            break
    
    return {
        'numero': numero,
        'intitule': intitule
    }


def extract_transaction_from_row(row: list) -> Dict[str, any]:
    """
    Extrait les infos d'une ligne de transaction.
    
    Structure typique des colonnes (positions fixes):
    - Col 0: Date
    - Col 1: Code Journal
    - Col 2: N° pièce
    - Col 4: N° facture
    - Col 9: Libellé
    - Col 12: N° tiers
    - Col 16: Débit
    - Col 18: Crédit
    - Col 20: Solde
    
    Mais on vérifie aussi les valeurs compactées pour la robustesse.
    """
    # Extraction par position fixe (méthode principale)
    date_transaction = format_date_fr(get_cell(row, 0))
    date_iso = format_date_iso(get_cell(row, 0))
    code_journal = get_cell(row, 1)
    numero_piece = get_cell(row, 2)
    numero_facture = get_cell(row, 4)
    libelle = get_cell(row, 9)
    n_tiers = get_cell(row, 12)
    
    # Vérifier que n_tiers n'est pas une date
    if is_date_iso(n_tiers):
        n_tiers = ""
    
    # Extraction des montants (positions fixes)
    debit = parse_amount(get_cell(row, 16))
    credit = parse_amount(get_cell(row, 18))
    solde = parse_amount(get_cell(row, 20))
    
    # Fallback: si les montants sont à 0, chercher dans les dernières colonnes
    if debit == 0 and credit == 0:
        # Chercher les montants dans les valeurs compactées
        values = compact_row(row)
        amounts = []
        for val in reversed(values):
            if is_numeric_amount(val):
                amounts.append(parse_amount(val))
            if len(amounts) >= 3:
                break
        
        # Les 3 derniers nombres sont généralement: débit, crédit, solde
        if len(amounts) >= 3:
            solde = amounts[0]
            credit = amounts[1]
            debit = amounts[2]
        elif len(amounts) == 2:
            solde = amounts[0]
            # Déterminer si c'est débit ou crédit par le signe
            if amounts[1] > 0:
                debit = amounts[1]
            else:
                credit = abs(amounts[1])
    
    # Fallback pour le libellé si vide
    if not libelle:
        values = compact_row(row)
        # Le libellé est généralement le texte le plus long (après date, code journal, pièce)
        for i, val in enumerate(values):
            if i >= 3 and len(val) > 5 and not is_numeric_amount(val) and not is_date_iso(val):
                libelle = val
                break
    
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
    Parse le Grand Livre Comptable unifié.

    Parcourt le fichier et maintient le contexte du compte courant.
    Chaque transaction hérite du compte auquel elle appartient.

    Args:
        file_path / client_id / batch_id : standard.
        period_start / period_end : si fournis, toute transaction (hors journal
            RAN) dont la date sort de [period_start, period_end] lève
            ValueError au premier hors-période détecté.

    Retourne: {
        data: [(date_gl, entite, compte, intitule_compte, date_trans, code_journal,
                numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
                periode, batch_id, row_id)],
        metadata,
        stats
    }
    """
    print(f"📄 Lecture du Grand Livre: {file_path}")

    period_start_d = _to_date(period_start)
    period_end_d = _to_date(period_end)

    df = pd.read_excel(file_path, header=None, dtype=str)
    data_list = df.values.tolist()
    
    # Extraire métadonnées
    metadata = extract_file_metadata(data_list, client_id)
    entite = metadata['entite']
    periode = metadata['periode']
    date_gl = metadata['date_extraction']
    
    print(f"  📋 Entité: {entite}")
    print(f"  📋 Période: {periode}")
    
    results = []
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
    
    for i, row in enumerate(data_list):
        line_type = detect_line_type(row)
        
        if line_type == 'compte':
            compte_courant = extract_compte_from_row(row)
            stats['nb_comptes'] += 1
            
        elif line_type == 'transaction':
            trans = extract_transaction_from_row(row)

            # Validation période — RAN exempté (reprise N-1)
            if period_start_d and period_end_d and trans['date_iso']:
                code_journal = trans.get('code_journal', '').upper()
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

            # Construire le tuple pour ClickHouse
            # (date_gl, entite, compte, intitule_compte, date_trans, code_journal,
            #  numero_piece, numero_facture, libelle, n_tiers, debit, credit, solde,
            #  periode, batch_id, row_id)
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
                periode,
                batch_id,
                row_id
            ))
            
            stats['nb_transactions'] += 1
            stats['total_debit'] += trans['debit']
            stats['total_credit'] += trans['credit']
            
            if trans['n_tiers']:
                stats['nb_avec_tiers'] += 1
            if trans['numero_facture']:
                stats['nb_avec_facture'] += 1
    
    # Vérifier l'équilibre
    stats['equilibre'] = abs(stats['total_debit'] - stats['total_credit']) < 0.01
    
    print(f"  ✓ {stats['nb_comptes']} comptes")
    print(f"  ✓ {stats['nb_transactions']} transactions")
    print(f"  ✓ {stats['nb_avec_tiers']} avec N° tiers ({100*stats['nb_avec_tiers']/max(1,stats['nb_transactions']):.1f}%)")
    print(f"  ✓ {stats['nb_avec_facture']} avec N° facture ({100*stats['nb_avec_facture']/max(1,stats['nb_transactions']):.1f}%)")
    print(f"  ✓ Équilibre: {'✅ OK' if stats['equilibre'] else '❌ Déséquilibre'}")
    
    return {
        'data': results,
        'entite': entite,
        'periode': periode,
        'date_extraction': date_gl,
        'stats': stats,
        'metadata': metadata
    }
