"""
Parser du fichier Mapping PLE (racine de compte → rubrique), format produit par
le bouton « Télécharger » du web.

Première ligne = en-têtes (casse et ordre indifférents) :
    racine, rubrique, nb_racine, type_rubrique, solde_filter, exclusions

Règles :
    racine        : texte obligatoire ; zéros de tête conservés, sans « .0 »
    rubrique      : obligatoire, en majuscules
    type_rubrique : 'PL' ou 'BILAN', obligatoire, en majuscules
    nb_racine     : entier (1-255) ; par défaut len(racine)
    solde_filter  : '', 'debit' ou 'credit' (minuscules)
    exclusions    : racines séparées par des virgules, normalisées en "a,b,c"

Une ligne sans racine est transmise telle quelle (racine vide) : la fusion
l'ignore et la compte. Toute autre valeur invalide fait échouer le chargement
avec les numéros de ligne Excel fautifs (les 10 premiers).
"""
import re
import unicodedata
from typing import Dict, List, Tuple

import openpyxl


_COLUMNS = ('racine', 'rubrique', 'nb_racine', 'type_rubrique', 'solde_filter', 'exclusions')
_REQUIRED = ('racine', 'rubrique', 'type_rubrique')
_TYPES = {'PL', 'BILAN'}
_SOLDES = {'', 'debit', 'credit'}


def _text(value) -> str:
    """Valeur de cellule → texte : entiers sans « .0 », zéros de tête des textes conservés."""
    if value is None:
        return ''
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    text = str(value).strip()
    if re.fullmatch(r'\d+\.0+', text):
        text = text.split('.')[0]
    return text


def _sans_accents(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def parse_ple(file_path: str) -> Dict:
    """
    Returns:
        {'data': [(racine, rubrique, nb_racine:int|'', type_rubrique, solde_filter, exclusions)],
         'stats': {lignes, sans_racine}}
    Raises:
        ValueError si en-têtes manquants ou valeurs invalides.
    """
    print(f"📄 Lecture du mapping PLE: {file_path}")
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        rows = list(wb.worksheets[0].iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        raise ValueError("Fichier PLE vide")

    headers = [_sans_accents(_text(h)).lower().replace(' ', '_') for h in rows[0]]
    col = {name: headers.index(name) for name in _COLUMNS if name in headers}
    missing = [name for name in _REQUIRED if name not in col]
    if missing:
        raise ValueError(
            f"En-têtes manquants dans le fichier PLE : {', '.join(missing)} "
            f"(attendus : {', '.join(_COLUMNS)})"
        )

    def cell(row, name):
        i = col.get(name)
        return _text(row[i]) if i is not None and i < len(row) else ''

    data: List[Tuple] = []
    errors: List[Tuple[int, str]] = []
    sans_racine = 0

    for line_no, row in enumerate(rows[1:], start=2):  # n° de ligne Excel
        values = {name: cell(row, name) for name in _COLUMNS}
        if not any(values.values()):
            continue  # ligne entièrement vide
        racine = values['racine']
        if not racine:
            sans_racine += 1
            data.append(('', values['rubrique'], '', values['type_rubrique'], '', ''))
            continue

        problems = []
        rubrique = values['rubrique'].upper()
        if not rubrique:
            problems.append('rubrique vide')

        type_rubrique = values['type_rubrique'].upper()
        if type_rubrique not in _TYPES:
            problems.append(f"type_rubrique « {values['type_rubrique']} » (attendu PL ou BILAN)")

        nb_raw = values['nb_racine']
        if nb_raw == '':
            nb_racine = len(racine)
        elif re.fullmatch(r'\d+', nb_raw) and 1 <= int(nb_raw) <= 255:
            nb_racine = int(nb_raw)
        else:
            nb_racine = None
            problems.append(f"nb_racine « {nb_raw} » (entier attendu)")

        solde_filter = _sans_accents(values['solde_filter']).lower()
        if solde_filter not in _SOLDES:
            problems.append(f"solde_filter « {values['solde_filter']} » (attendu vide, debit ou credit)")

        exclusions = ','.join(e for e in re.split(r'[,;\s]+', values['exclusions']) if e)

        if problems:
            errors.append((line_no, ', '.join(problems)))
            continue
        data.append((racine, rubrique, nb_racine, type_rubrique, solde_filter, exclusions))

    if errors:
        detail = '; '.join(f"ligne {n} : {msg}" for n, msg in errors[:10])
        more = f" (+{len(errors) - 10} autres)" if len(errors) > 10 else ''
        raise ValueError(f"Fichier PLE invalide — {len(errors)} ligne(s) en erreur : {detail}{more}")

    print(f"  ✓ {len(data)} lignes lues ({sans_racine} sans racine)")
    return {'data': data, 'stats': {'lignes': len(data), 'sans_racine': sans_racine}}
