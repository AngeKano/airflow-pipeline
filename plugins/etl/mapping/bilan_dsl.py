"""
Parser du DSL utilisé dans le sheet Bilan SYSCOHADA.

Conventions de la colonne "Comptes SYSCOHADA" :
    - "211"                          → racine 3 chiffres
    - "201,202"                      → union : comptes 201 ET 202
    - "271-275"                      → plage 271, 272, 273, 274, 275
    - "AE+AF+AG+AH"                  → somme de rubriques bilan (composition)
    - "Somme CA à CM"                → plage de rubriques bilan (composition)
    - "41 sauf 419"                  → racine avec exclusion
    - "42-48 (sauf 471, 478)"        → plage avec exclusions
    - "52 (solde débiteur)"          → racine avec filtre solde positif
    - "52 (solde créditeur)"         → racine avec filtre solde négatif
    - "471 (solde débiteur), 478"    → liste mixte avec filtres
"""
import re
from typing import Dict, List, NamedTuple, Optional, Tuple


class BilanMapping(NamedTuple):
    """Une entrée atomique du mapping bilan : un compte/racine → un code bilan."""
    racine: str
    code_bilan: str
    nb_racine: int
    solde_filter: str  # '' (aucun), 'debit', 'credit'
    exclusions: Tuple[str, ...]  # racines à exclure (ex: ('419',))


# Codes bilan de référence : 2 lettres majuscules, suivies optionnellement
# d'un chiffre pour les subdivisions (DK1, DK2, DK3, etc.).
_RE_CODE_BILAN = re.compile(r'^[A-Z]{2}\d?$')

# Filtre solde dans une expression
_RE_SOLDE = re.compile(r'\(solde\s+(débiteur|crediteur|créditeur|debiteur)\)', re.IGNORECASE)

# Exclusions globales ("sauf X, Y, Z")
_RE_SAUF = re.compile(r'\(?sauf\s+([^)]+?)\)?(?:$|,(?!\s*(?:\d|et\s)))', re.IGNORECASE)
_RE_INLINE_SAUF = re.compile(r'sauf\s+([\d\s,et]+)', re.IGNORECASE)


def _is_code_bilan(token: str) -> bool:
    """Détecte si un token est un code bilan (ex: AE, AF, BZ)."""
    return bool(_RE_CODE_BILAN.match(token.strip()))


def _expand_range(start: str, end: str) -> List[str]:
    """Étend une plage numérique '271'-'275' en ['271','272','273','274','275']."""
    s = start.strip()
    e = end.strip()
    if not s.isdigit() or not e.isdigit():
        return [s, e]  # plage non numérique : on garde les bornes
    si, ei = int(s), int(e)
    if ei < si:
        return [s]
    return [str(i) for i in range(si, ei + 1)]


def _detect_solde_filter(expr: str) -> str:
    """Renvoie 'debit', 'credit' ou ''."""
    m = _RE_SOLDE.search(expr)
    if not m:
        return ''
    word = m.group(1).lower()
    # Suppression des accents pour matching robuste
    word = word.replace('é', 'e').replace('è', 'e')
    if 'debit' in word:
        return 'debit'
    if 'credit' in word:
        return 'credit'
    return ''


def _extract_exclusions(expr: str) -> List[str]:
    """
    Extrait les codes/racines à exclure d'une expression du type
    "41 sauf 419" ou "42-48 (sauf 471, 478 et 488)".
    """
    exclusions: List[str] = []
    # 1. Pattern principal (sauf ...) entre parenthèses ou en fin
    m = _RE_INLINE_SAUF.search(expr)
    if m:
        raw = m.group(1)
        # Nettoyer "471, 478 et 488" → ['471','478','488']
        raw = raw.replace(' et ', ',').replace(' ET ', ',')
        for tok in raw.split(','):
            t = tok.strip().strip('()')
            if t.isdigit():
                exclusions.append(t)
    return exclusions


def _clean_expression(expr: str) -> str:
    """Retire les parenthèses, filtres solde et clauses sauf — garde le core des comptes."""
    s = expr
    s = _RE_SOLDE.sub('', s)        # retirer (solde ...)
    s = _RE_INLINE_SAUF.sub('', s)  # retirer "sauf ..."
    s = re.sub(r'\([^)]*\)', '', s) # retirer parenthèses résiduelles
    return s.strip(' ,;')


# ----------------------------------------------------------------------
# API publique
# ----------------------------------------------------------------------

class ParsedBilanLine(NamedTuple):
    """Résultat d'un parse d'une ligne Bilan."""
    code_bilan: str
    is_composition: bool          # True si l'expression est une somme de rubriques bilan
    composition_children: Tuple[str, ...]   # ('AE', 'AF', 'AG', 'AH') si is_composition
    atomic_mappings: Tuple[BilanMapping, ...]  # mappings atomiques compte→rubrique


def parse_bilan_expression(code_bilan: str, expression: str) -> ParsedBilanLine:
    """
    Parse une ligne du sheet Bilan en :
    - Composition de rubriques (somme de codes bilan) : composition_children
    - Mappings atomiques (compte/racine → code_bilan) : atomic_mappings

    Args:
        code_bilan: code de la rubrique (ex: 'AE', 'BZ')
        expression: contenu de la colonne "Comptes SYSCOHADA"

    Returns:
        ParsedBilanLine
    """
    expr = (expression or '').strip()

    # --- 1. Composition de rubriques ("AE+AF+AG+AH" ou "Somme CA à CM") ---
    # Pattern Somme X à Y
    m_somme = re.match(
        r'^somme\s+([A-Z]{2})\s+(?:à|a)\s+([A-Z]{2})$',
        expr,
        re.IGNORECASE,
    )
    if m_somme:
        start, end = m_somme.group(1).upper(), m_somme.group(2).upper()
        # Générer la liste des codes alphabétiques entre start et end (ex: CA, CB, ..., CM)
        # Suppose même 1er caractère
        if start[0] == end[0]:
            children = tuple(
                f'{start[0]}{chr(c)}'
                for c in range(ord(start[1]), ord(end[1]) + 1)
            )
            return ParsedBilanLine(
                code_bilan=code_bilan,
                is_composition=True,
                composition_children=children,
                atomic_mappings=(),
            )

    # Pattern "AE+AF+..." ou "AE + AF + ..."
    if '+' in expr and not any(c.isdigit() for c in expr):
        tokens = [t.strip() for t in expr.split('+')]
        if all(_is_code_bilan(t) for t in tokens):
            return ParsedBilanLine(
                code_bilan=code_bilan,
                is_composition=True,
                composition_children=tuple(tokens),
                atomic_mappings=(),
            )

    # Pattern "DA + DB + DC" (avec mélange digits possibles dans le code) - safer check
    if '+' in expr:
        tokens = [t.strip() for t in expr.split('+')]
        if all(_is_code_bilan(t) for t in tokens):
            return ParsedBilanLine(
                code_bilan=code_bilan,
                is_composition=True,
                composition_children=tuple(tokens),
                atomic_mappings=(),
            )

    # --- 2. Mapping atomique ---
    # Étape A : extraire filtre solde et exclusions globales
    global_exclusions = _extract_exclusions(expr)

    # Étape B : nettoyer pour ne garder que les comptes
    # Mais attention : un filtre solde peut être attaché à UN compte spécifique
    # dans une liste (ex: "471 (solde débiteur), 478"), donc on parse token par token
    mappings: List[BilanMapping] = []

    # Découper sur la virgule (séparateur union)
    # On découpe d'abord en gardant les parenthèses associées au token précédent
    tokens = _smart_split(expr, ',')
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        # Détecter filtre solde local à ce token
        local_solde = _detect_solde_filter(tok)
        # Nettoyer le token
        clean = _clean_expression(tok)
        # Reste plage ou compte ?
        if '-' in clean:
            parts = clean.split('-', 1)
            racines = _expand_range(parts[0], parts[1])
        else:
            racines = [clean] if clean else []

        for r in racines:
            r = r.strip()
            if not r.isdigit():
                continue
            mappings.append(BilanMapping(
                racine=r,
                code_bilan=code_bilan,
                nb_racine=len(r),
                solde_filter=local_solde,
                exclusions=tuple(global_exclusions),
            ))

    return ParsedBilanLine(
        code_bilan=code_bilan,
        is_composition=False,
        composition_children=(),
        atomic_mappings=tuple(mappings),
    )


def _smart_split(s: str, sep: str) -> List[str]:
    """Découpe sur sep en ignorant les parenthèses (ne coupe pas à l'intérieur de '()')."""
    parts: List[str] = []
    depth = 0
    cur = []
    for ch in s:
        if ch == '(':
            depth += 1
            cur.append(ch)
        elif ch == ')':
            depth -= 1
            cur.append(ch)
        elif ch == sep and depth == 0:
            parts.append(''.join(cur))
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append(''.join(cur))
    return parts
