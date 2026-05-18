"""
Helpers de parsing robuste pour REPFI ETL
Travaille uniquement avec les valeurs non-null, ignore les décalages de colonnes
"""
import re
import pandas as pd
from typing import Any, List, Tuple, Optional, Dict


# ========================================
# VALIDATION ET NETTOYAGE
# ========================================

def is_valid(val: Any) -> bool:
    """Vérifie si une valeur est valide (non vide, non NaN)."""
    if val is None:
        return False
    if pd.isna(val):
        return False
    val_str = str(val).strip().lower()
    return val_str != "" and val_str != "nan" and val_str != "none"


def clean(val: Any) -> str:
    """Nettoie une valeur."""
    if not is_valid(val):
        return ""
    return str(val).strip()


def get_cell(row: list, idx: int) -> str:
    """Accès sécurisé à une cellule."""
    if idx < 0 or idx >= len(row):
        return ""
    return clean(row[idx])


# ========================================
# EXTRACTION CELLULES NON VIDES
# ========================================

def extract_non_empty_cells(row: list) -> List[Tuple[int, str]]:
    """
    Extrait uniquement les cellules non vides d'une ligne.
    Retourne une liste de tuples (index_colonne, valeur).
    C'est LA FONCTION CLÉ pour gérer les décalages.
    """
    cells = []
    for i, val in enumerate(row):
        if is_valid(val):
            cells.append((i, clean(val)))
    return cells


def get_values_only(row: list) -> List[str]:
    """Retourne uniquement les valeurs non vides (sans les index)."""
    return [clean(val) for val in row if is_valid(val)]


def compact_row(row: list) -> List[str]:
    """
    Compacte une ligne en enlevant les valeurs nulles.
    [None, 'A', None, None, 'B', None, 'C'] → ['A', 'B', 'C']
    """
    return [clean(val) for val in row if is_valid(val)]


# ========================================
# DÉTECTION DES TYPES DE LIGNES
# ========================================

def is_date_iso(val: Any) -> bool:
    """Vérifie si une valeur est une date ISO (YYYY-MM-DD)."""
    if not is_valid(val):
        return False
    return bool(re.match(r'^\d{4}-\d{2}-\d{2}', str(val)))


def is_compte_8_digits(val: Any) -> bool:
    """Vérifie si une valeur est un numéro de compte à 8 chiffres max (1 à 8 chiffres), et ne commence pas par 0."""
    if not is_valid(val):
        return False
    val_str = str(val).strip()
    return bool(re.match(r'^[1-9]\d{0,7}$', val_str))


def is_compte_number(val: Any) -> bool:
    """Vérifie si une valeur est un numéro de compte (chiffres uniquement)."""
    if not is_valid(val):
        return False
    return str(val).strip().isdigit()


def is_compte_tiers(val: Any) -> bool:
    """Vérifie si c'est un compte tiers (commence par 4)."""
    if not is_valid(val):
        return False
    val_str = str(val).strip()
    return val_str.isdigit() and val_str.startswith("4")


def is_code_journal(val: Any) -> bool:
    """Vérifie si une valeur est un code journal (2-5 lettres majuscules)."""
    if not is_valid(val):
        return False
    return bool(re.match(r'^[A-Z]{2,5}$', str(val).strip()))


def is_numeric_amount(val: Any) -> bool:
    """Vérifie si une valeur est un montant numérique."""
    if not is_valid(val):
        return False
    try:
        clean_val = str(val).replace(" ", "").replace(",", ".").replace("\xa0", "")
        clean_val = re.sub(r'[^\d.\-]', '', clean_val)
        if clean_val and clean_val not in ['-', '.']:
            float(clean_val)
            return True
    except:
        pass
    return False


def contains_total(row: list) -> bool:
    """Vérifie si la ligne contient 'Total compte' ou 'Total'."""
    for val in row:
        if is_valid(val):
            val_str = str(val)
            if "Total compte" in val_str or "Total" == val_str.strip():
                return True
    return False


def is_header_row(row: list, keywords: List[str]) -> bool:
    """Vérifie si c'est une ligne d'en-tête basée sur des mots-clés."""
    row_text = " ".join([str(v).lower() for v in row if is_valid(v)])
    matches = sum(1 for kw in keywords if kw.lower() in row_text)
    return matches >= 2


def is_metadata_row(row: list) -> bool:
    """Vérifie si c'est une ligne de métadonnées (à ignorer)."""
    values = get_values_only(row)
    if not values:
        return True
    
    first_val = values[0].lower() if values else ""
    
    # Lignes à ignorer
    ignore_patterns = [
        "© sage", "sage 100", "date de tirage", "impression",
        "page :", "période du", "complet", "tenue de compte"
    ]
    
    for pattern in ignore_patterns:
        if pattern in first_val:
            return True
    
    return False


# ========================================
# PARSING DES MONTANTS ET DATES
# ========================================

def parse_amount(val: Any) -> float:
    """Parse un montant numérique."""
    if not is_valid(val):
        return 0.0
    try:
        clean_val = str(val).replace(" ", "").replace(",", ".").replace("\xa0", "")
        clean_val = re.sub(r'[^\d.\-]', '', clean_val)
        return float(clean_val) if clean_val and clean_val not in ['-', '.'] else 0.0
    except:
        return 0.0


def format_date_fr(date_str: str) -> str:
    """Convertit une date ISO en format français DD/MM/YYYY."""
    if not date_str:
        return ""
    try:
        match = re.match(r'(\d{4})-(\d{2})-(\d{2})', str(date_str))
        if match:
            return f"{match.group(3)}/{match.group(2)}/{match.group(1)}"
    except:
        pass
    return str(date_str)


def format_date_iso(date_str: str) -> str:
    """Extrait la date ISO (YYYY-MM-DD) d'une chaîne."""
    if not date_str:
        return ""
    match = re.match(r'(\d{4}-\d{2}-\d{2})', str(date_str))
    if match:
        return match.group(1)
    return ""


def extract_periode_from_date(date_str: str) -> str:
    """Extrait la période YYYYMM d'une date."""
    if not date_str:
        return ""
    match = re.match(r'(\d{4})-(\d{2})', str(date_str))
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return ""


# ========================================
# EXTRACTION MÉTADONNÉES FICHIER
# ========================================

def extract_file_metadata(data: list, client_id: str) -> Dict[str, str]:
    """
    Extrait les métadonnées d'un fichier Excel (entité, date, période).
    Parcourt les 15 premières lignes.
    """
    entite = ""
    date_extraction = ""
    periode_debut = ""
    periode_fin = ""
    
    for i in range(min(15, len(data))):
        row = data[i]
        if not row:
            continue
        
        for j, val in enumerate(row):
            if not is_valid(val):
                continue
            
            val_str = str(val)
            
            # Chercher l'entité (premier texte significatif sans ©)
            if not entite and j == 0:
                if (val_str 
                    and "©" not in val_str 
                    and "Sage" not in val_str
                    and "Date" not in val_str
                    and "Impression" not in val_str
                    and "Liste" not in val_str
                    and len(val_str) < 50
                    and not is_date_iso(val_str)):
                    entite = val_str.strip()
            
            # Chercher la date de tirage
            if "Date de tirage" in val_str:
                for k in range(j + 1, min(j + 5, len(row))):
                    if k < len(row) and is_date_iso(row[k]):
                        date_extraction = format_date_fr(str(row[k]))
                        break
            
            # Chercher la période
            if "Période du" in val_str:
                for k in range(j + 1, min(j + 5, len(row))):
                    if k < len(row) and is_date_iso(row[k]):
                        if not periode_debut:
                            periode_debut = format_date_iso(str(row[k]))
                        elif not periode_fin:
                            periode_fin = format_date_iso(str(row[k]))
                        break
            
            # Date après "au"
            if "au" == val_str.strip().lower():
                for k in range(j + 1, min(j + 3, len(row))):
                    if k < len(row) and is_date_iso(row[k]):
                        periode_fin = format_date_iso(str(row[k]))
                        break
    
    # Valeurs par défaut
    if not entite:
        entite = client_id
    if not date_extraction:
        date_extraction = pd.Timestamp.now().strftime("%d/%m/%Y")
    if not periode_debut:
        periode_debut = pd.Timestamp.now().strftime("%Y-%m-01")
    
    # Calculer la période au format YYYYMM
    periode = extract_periode_from_date(periode_fin if periode_fin else periode_debut)
    if not periode:
        periode = pd.Timestamp.now().strftime("%Y%m")
    
    return {
        'entite': entite,
        'date_extraction': date_extraction,
        'periode_debut': periode_debut,
        'periode_fin': periode_fin,
        'periode': periode,
    }


def find_header_row(data: list, search_terms: List[str], max_rows: int = 15) -> int:
    """
    Recherche la ligne d'en-tête contenant certains termes.
    Retourne l'index ou -1 si non trouvé.
    """
    for i in range(min(max_rows, len(data))):
        row = data[i]
        if not row:
            continue
        
        row_text = " ".join([str(v).lower() for v in row if is_valid(v)])
        
        matches = sum(1 for term in search_terms if term.lower() in row_text)
        if matches >= len(search_terms) * 0.5:
            return i
    
    return -1