"""
Chargement d'un fichier de dimension (Plan Comptable, Codes Journaux, Plan Tiers)
dans sa table ClickHouse.

Utilisé par :
    - le DAG complet (etl_comptable_clickhouse), étape dimensions ;
    - le DAG de mise à jour unitaire (etl_dimensions_clickhouse).

La mise à jour est une fusion non destructive : les nouvelles clés sont ajoutées,
les lignes modifiées sont mises à jour, aucune ligne n'est jamais supprimée.
"""
from typing import Dict, List, Tuple

from etl.parsers import (
    parse_plan_compte,
    parse_code_journal,
    parse_plan_tiers,
    parse_sage_pnc,
    parse_ple,
)
from etl.mapping import detect_plan_source, map_compte


# Type de fichier (vocabulaire S3/front) → table ClickHouse
DIMENSION_TABLES = {
    'plan_comptes': 'plan_compte',
    'code_journal': 'code_journal',
    'plan_tiers': 'plan_tiers',
    'ple': 'ple',  # mapping racine → rubrique
}

# Alias acceptés pour désigner une dimension (noms de dossiers S3, de tables…)
_DIMENSION_ALIASES = {
    'plan_comptes': 'plan_comptes',
    'plan_compte': 'plan_comptes',
    'plan_comptable': 'plan_comptes',
    'code_journal': 'code_journal',
    'codes_journaux': 'code_journal',
    'plan_tiers': 'plan_tiers',
    'ple': 'ple',
    'mapping': 'ple',
    'mapping_ple': 'ple',
}


def normalize_dimension(name: str) -> str:
    """'PLAN_COMPTABLE' / 'plan_compte' / … → 'plan_comptes'. Lève si inconnu."""
    key = (name or '').strip().lower().replace('-', '_').replace(' ', '_')
    dimension = _DIMENSION_ALIASES.get(key)
    if not dimension:
        raise ValueError(
            f"Dimension inconnue: '{name}'. "
            f"Valeurs acceptées : {sorted(DIMENSION_TABLES)}"
        )
    return dimension


def _parse(dimension: str, file_path: str, file_format: str,
           client_id: str) -> Tuple[List[Tuple], Dict]:
    """Parse le fichier et renvoie (lignes prêtes pour la table, infos)."""
    if dimension == 'plan_comptes':
        result = parse_plan_compte(file_path, client_id)
        rows = result['data']  # [(compte, intitule, nature)]

        # Le plan_compte ClickHouse est toujours en référentiel SYSCOHADA :
        # un plan PCG est mappé avant insertion (cohérent avec le grand livre).
        plan_source = detect_plan_source([r[0] for r in rows])
        print(f"  📋 Plan source détecté (plan_compte): {plan_source}")
        if plan_source == 'PCG':
            rows = [(map_compte(c)['compte_syscohada'], i, n) for c, i, n in rows]
            print(f"  🔁 Plan_compte mappé PCG→SYSCO ({len(rows)} comptes)")
        return rows, {'parse_stats': result['stats'], 'plan_source': plan_source}

    if dimension == 'code_journal':
        result = parse_code_journal(file_path, client_id)
        return result['data'], {'parse_stats': result['stats']}

    if dimension == 'plan_tiers':
        if file_format == 'sage_pnc':
            result = parse_sage_pnc(file_path, client_id)
        else:
            result = parse_plan_tiers(file_path, client_id)
        return result['data'], {'parse_stats': result['stats']}

    if dimension == 'ple':
        result = parse_ple(file_path)
        return result['data'], {'parse_stats': result['stats']}

    raise ValueError(f"Dimension non gérée: {dimension}")


def load_dimension(client_id: str, dimension: str, file_path: str,
                   file_format: str, ch, propagate: bool = True,
                   require_rows: bool = True) -> Dict:
    """
    Parse un fichier de dimension et le fusionne dans sa table ClickHouse.

    Args:
        dimension: 'plan_comptes' | 'code_journal' | 'plan_tiers' | 'ple' (ou alias)
        ch: ClickHouseManager ouvert
        propagate: répercuter les intitulés/types modifiés dans grand_livre
        require_rows: lever une erreur si le fichier ne donne aucune ligne

    Returns (sérialisable XCom) :
        {dimension, table, lignes_fichier, ajoutees, modifiees, inchangees,
         ignorees, propagees_grand_livre, parse_stats, [plan_source]}
    """
    dimension = normalize_dimension(dimension)
    table = DIMENSION_TABLES[dimension]

    rows, info = _parse(dimension, file_path, file_format, client_id)
    if not rows and require_rows:
        raise ValueError(
            f"Aucune ligne exploitable dans le fichier {dimension} "
            f"(vérifier le format du fichier)"
        )

    stats = ch.upsert_dimension(client_id, table, rows)
    written = stats.pop('rows_ecrites', [])

    if table == 'ple':
        # Le mapping a changé : on reclasse le grand livre dans le même run.
        # Les compteurs ajoutées/modifiées restent ceux du mapping.
        reclassement = {'lignes_modifiees': 0, 'comptes_modifies': 0}
        if written:
            try:
                reclassement = ch.reclassify_grand_livre(client_id)
            except Exception as e:
                raise RuntimeError(
                    f"Mapping mis à jour ({stats['ajoutees']} ajoutées, "
                    f"{stats['modifiees']} modifiées) mais le reclassement du grand "
                    f"livre a échoué : {e}. Relancez un reclassement."
                ) from e
        return {
            'dimension': dimension,
            'table': table,
            **stats,
            'reclassement': reclassement,
            **info,
        }

    propagated = 0
    if propagate and written:
        # Best-effort : la table de dimension est déjà à jour ; un échec de
        # répercussion ne doit pas faire échouer la mise à jour elle-même.
        try:
            propagated = ch.propagate_dimension(client_id, table, written)
        except Exception as e:
            print(f"  ⚠️ Répercussion grand_livre impossible ({table}): {e}")

    return {
        'dimension': dimension,
        'table': table,
        **stats,
        'propagees_grand_livre': propagated,
        **info,
    }
