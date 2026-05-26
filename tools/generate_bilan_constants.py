"""
Génère les constantes BILAN_* à partir du référentiel Python validé
(bilan_reference.py).

C'est la NOUVELLE source de vérité — l'Excel Mapping PL DEF 2.xlsx n'est
plus utilisé en production. L'utilisateur a validé manuellement les 57 lignes
+ règles spéciales (DC/DN split, DK subdivision).

Usage : python tools/generate_bilan_constants.py
"""
import sys
import importlib.util

sys.path.insert(0, 'plugins')

# Charger bilan_dsl
spec_dsl = importlib.util.spec_from_file_location(
    'bilan_dsl', 'plugins/etl/mapping/bilan_dsl.py'
)
dsl = importlib.util.module_from_spec(spec_dsl)
spec_dsl.loader.exec_module(dsl)

# Charger bilan_reference (besoin de stub clickhouse)
class _StubPkg:
    pass
sys.modules['clickhouse'] = _StubPkg()
spec_ref = importlib.util.spec_from_file_location(
    'clickhouse.bilan_reference', 'plugins/clickhouse/bilan_reference.py'
)
ref = importlib.util.module_from_spec(spec_ref)
spec_ref.loader.exec_module(ref)

BILAN_REFERENCE = ref.BILAN_REFERENCE
COMPOSITE_ONLY = ref.COMPOSITE_ONLY_CODES
SUBDIVISIONS_REF = ref.BILAN_SUBDIVISIONS_REFERENCE


def main() -> None:
    labels: dict = {}
    composition: dict = {}
    mappings: list = []

    # Première passe : collecter les labels
    for row in BILAN_REFERENCE:
        labels[row.code] = row.libelle

    # Deuxième passe : parser les expressions
    for row in BILAN_REFERENCE:
        parsed = dsl.parse_bilan_expression(row.code, row.expression)
        if parsed.is_composition:
            children = [c for c in parsed.composition_children if c in labels]
            if len(children) != len(parsed.composition_children):
                skipped = set(parsed.composition_children) - set(children)
                print(f'  ⚠️ {row.code}: codes inconnus ignorés dans composition : {sorted(skipped)}')
            composition[row.code] = children
        else:
            for mp in parsed.atomic_mappings:
                mappings.append((
                    mp.racine, mp.code_bilan, mp.nb_racine,
                    mp.solde_filter, list(mp.exclusions),
                ))

    # Construire BILAN_SUBDIVISIONS au format attendu par le code
    subdivisions: dict = {}
    for parent, children in SUBDIVISIONS_REF.items():
        subdivisions[parent] = {}
        for child in children:
            # Récupérer la définition du child dans BILAN_REFERENCE
            child_row = next((r for r in BILAN_REFERENCE if r.code == child), None)
            if child_row is None:
                continue
            # Le child a typiquement une expression simple (racine 2)
            parsed_c = dsl.parse_bilan_expression(child, child_row.expression)
            if parsed_c.atomic_mappings:
                m = parsed_c.atomic_mappings[0]
                subdivisions[parent][child] = {
                    'libelle': child_row.libelle,
                    'racine': m.racine,
                    'nb_racine': m.nb_racine,
                }

    # Écrire le fichier de sortie (à coller dans config.py)
    out = 'tools/bilan_constants_generated.py'
    with open(out, 'w', encoding='utf-8') as f:
        f.write('# AUTO-GÉNÉRÉ par tools/generate_bilan_constants.py\n')
        f.write('# Source : plugins/clickhouse/bilan_reference.py (référentiel Python validé)\n\n')

        f.write('BILAN_LABELS = {\n')
        for code in sorted(labels.keys()):
            f.write(f'    {code!r}: {labels[code]!r},\n')
        f.write('}\n\n')

        f.write('BILAN_COMPOSITION = {\n')
        for code in sorted(composition.keys()):
            f.write(f'    {code!r}: {composition[code]!r},\n')
        f.write('}\n\n')

        f.write('BILAN_SUBDIVISIONS = {\n')
        for parent, subs in sorted(subdivisions.items()):
            f.write(f'    {parent!r}: {{\n')
            for child, info in sorted(subs.items()):
                f.write(f'        {child!r}: {info!r},\n')
            f.write('    },\n')
        f.write('}\n\n')

        f.write('BILAN_MAPPING_DATA = [\n')
        for racine, code, nb, solde, excl in sorted(mappings, key=lambda x: (x[1], x[0])):
            f.write(f'    ({racine!r}, {code!r}, {nb}, {solde!r}, {excl!r}),\n')
        f.write(']\n')

    # Stats
    print(f'\n✅ Fichier généré : {out}')
    print(f'  - Libellés     : {len(labels)} rubriques bilan')
    print(f'  - Compositions : {len(composition)} rubriques agrégées')
    print(f'  - Subdivisions : {len(subdivisions)} parents')
    print(f'  - Mappings     : {len(mappings)} entrées atomiques')
    print()
    print('Composition des rubriques agrégées:')
    for c in sorted(composition.keys()):
        print(f'  {c} = {" + ".join(composition[c])}')
    print()
    print('Subdivisions:')
    for p, subs in subdivisions.items():
        for child, info in subs.items():
            print(f'  {p} → {child}: racine {info["racine"]} ({info["libelle"]})')
    print()
    print('Rubriques avec filtre solde:')
    for r, c, nb, solde, ex in mappings:
        if solde:
            print(f'  {c}: racine {r} (solde={solde})')
    print()
    print('Rubriques avec exclusions:')
    seen = set()
    for r, c, nb, solde, ex in mappings:
        if ex and (c, tuple(ex)) not in seen:
            seen.add((c, tuple(ex)))
            print(f'  {c}: exclut {ex}')


if __name__ == '__main__':
    main()
