"""
Gestion de la table PLE (Plan Liasse Export) - Mapping Racine → Rubrique.

Cette table couvre deux référentiels SYSCOHADA dans la même structure
(différenciés par type_rubrique) :
    - 'PL'    : rubriques compte de résultat (RA-RS, TA-TO)
    - 'BILAN' : rubriques bilan (AD-DZ)

Filtres et exclusions :
    - solde_filter ∈ {'', 'debit', 'credit'} : pour les comptes mixtes
      (ex: classe 52 — incluse en BS si solde débiteur, en DQ si créditeur).
    - exclusions : liste de racines à exclure (ex: BI inclut "41" sauf "419").

`ple` est un référentiel À PART ENTIÈRE, modifiable par l'utilisateur depuis le
web (ligne à ligne ou par fichier). Airflow ne le reconstruit JAMAIS : la table
est créée si absente et reçoit le mapping par défaut uniquement si elle est
vide (nouveau client). Aucune opération n'y supprime de ligne.
"""
from typing import Dict, Iterable, List, Tuple

from clickhouse.base import ClickHouseBase
from clickhouse.config import PLE_MAPPING_DATA, BILAN_MAPPING_DATA


# Colonnes lues/écrites par le web : ne pas renommer.
PLE_COLUMNS = ('racine', 'rubrique', 'nb_racine', 'type_rubrique', 'solde_filter', 'exclusions')

# Classe de compte → type de rubrique (même règle au chargement et au reclassement)
_CLASSES_PL = ('6', '7', '8')
_CLASSES_BILAN = ('1', '2', '3', '4', '5')


def solde_signe(debit_moins_credit: float) -> float:
    """
    Solde signé retenu pour le classement (> 0 débiteur, < 0 créditeur).

    Arrondi au centime : la somme des montants n'est pas faite dans le même ordre
    au chargement (Python) et au reclassement (ClickHouse) ; sans arrondi, un
    compte soldé pourrait sortir à ±1e-12 et changer de rubrique (BJ/DK…).
    """
    return round(float(debit_moins_credit), 2)


class PleIndex:
    """
    Mapping `ple` d'un client chargé en mémoire.

    La recherche est pilotée par les données : pour un type donné, on essaie les
    longueurs de racine (nb_racine) réellement présentes dans la table, de la
    plus longue à la plus courte. Une ligne saisie avec une longueur atypique
    (ex: nb_racine = 5 en PL) est donc prise en compte.
    """

    def __init__(self, rows: Iterable[Tuple]):
        """rows : (racine, rubrique, nb_racine, type_rubrique, solde_filter, exclusions)."""
        self._index: Dict[str, Dict[int, Dict[str, List[Tuple]]]] = {}
        for racine, rubrique, nb_racine, type_rubrique, solde_filter, exclusions in rows:
            racine = (racine or '').strip()
            if not racine:
                continue
            exclus = tuple(e.strip() for e in (exclusions or '').split(',') if e.strip())
            (self._index
                .setdefault(type_rubrique, {})
                .setdefault(int(nb_racine), {})
                .setdefault(racine, [])
                .append((solde_filter or '', rubrique or '', exclus)))

        # Même ordre que la lecture ClickHouse (clé de tri) : '' < 'credit' < 'debit'
        for par_nb in self._index.values():
            for par_racine in par_nb.values():
                for regles in par_racine.values():
                    regles.sort(key=lambda r: r[0])
        self._levels = {t: sorted(par_nb, reverse=True) for t, par_nb in self._index.items()}

    def __len__(self):
        return sum(len(regles) for par_nb in self._index.values()
                   for par_racine in par_nb.values() for regles in par_racine.values())

    def lookup(self, compte: str, type_rubrique: str, solde: float = 0.0) -> str:
        """Rubrique de `compte` pour un type ('PL' | 'BILAN'), '' si aucune règle."""
        compte = (compte or '').strip()
        par_nb = self._index.get(type_rubrique)
        if not compte or not par_nb:
            return ''
        for nb in self._levels[type_rubrique]:
            if nb > len(compte):
                continue
            for solde_filter, rubrique, exclus in par_nb[nb].get(compte[:nb], ()):
                if any(compte.startswith(e) for e in exclus):
                    continue
                if solde_filter == 'debit' and solde < 0:
                    continue
                if solde_filter == 'credit' and solde > 0:
                    continue
                return rubrique
        return ''

    def classify(self, compte: str, solde: float = 0.0) -> str:
        """
        Rubrique unique d'un compte : PL pour les classes 6/7/8, BILAN (avec sens
        du solde et exclusions) pour les classes 1 à 5, '' sinon.
        Utilisée à l'identique par l'enrichissement et par le reclassement.
        """
        compte = (compte or '').strip()
        if compte.startswith(_CLASSES_PL):
            return self.lookup(compte, 'PL', solde)
        if compte.startswith(_CLASSES_BILAN):
            return self.lookup(compte, 'BILAN', solde)
        return ''


class PLEManager(ClickHouseBase):
    """Gestion de la table PLE (P&L + Bilan) pour le mapping des rubriques."""

    @staticmethod
    def _create_sql(db_name: str, table: str) -> str:
        # La clé de tri inclut solde_filter : une même racine porte deux rubriques
        # selon le sens du solde (ex: 44 → BJ si débiteur, DK3 si créditeur).
        return f"""
            CREATE TABLE IF NOT EXISTS {db_name}.{table} (
                racine String,
                rubrique String,
                nb_racine UInt8,
                type_rubrique LowCardinality(String) DEFAULT 'PL',
                solde_filter LowCardinality(String) DEFAULT '',
                exclusions String DEFAULT '',
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (type_rubrique, racine, nb_racine, solde_filter)
            PRIMARY KEY (type_rubrique, racine, nb_racine, solde_filter)
        """

    def ensure_table(self, client_id: str) -> bool:
        """
        Prépare la table ple SANS jamais perdre son contenu :
            - absente → créée ;
            - présente → colonnes manquantes ajoutées, clé de tri migrée si besoin
              (par recopie, voir _migrate_sorting_key) ;
            - vide → alimentée avec le mapping par défaut (nouveau client).
        Un client existant garde son mapping tel quel.

        Returns: True si le mapping par défaut vient d'être chargé.
        """
        db_name = self._get_db_name(client_id)
        if self._table_exists(db_name, 'ple'):
            self._migrate_schema(db_name)
            self._migrate_sorting_key(db_name)
        else:
            self._execute(self._create_sql(db_name, 'ple'))

        if self.get_count(client_id) == 0:
            self.populate_defaults(client_id)
            return True
        print(f"  ✓ Table {db_name}.ple prête (mapping du client conservé)")
        return False

    def _migrate_sorting_key(self, db_name: str):
        """
        Les anciennes tables ple n'avaient pas solde_filter dans leur clé de tri,
        ce qu'ALTER ne sait pas modifier. On recopie TOUTES les lignes (sans FINAL,
        versions comprises) dans une table à la bonne clé, on vérifie le compte,
        puis on échange les tables avant de supprimer l'ancienne.
        """
        result = self._execute(
            "SELECT sorting_key FROM system.tables WHERE database = %(db)s AND name = 'ple'",
            {'db': db_name},
        )
        if not result or 'solde_filter' in str(result[0][0]):
            return

        cols = ', '.join(PLE_COLUMNS + ('updated_at',))
        self._execute(f"DROP TABLE IF EXISTS {db_name}.ple__migration")  # reliquat d'un essai interrompu
        self._execute(self._create_sql(db_name, 'ple__migration'))
        self._execute(
            f"INSERT INTO {db_name}.ple__migration ({cols}) SELECT {cols} FROM {db_name}.ple"
        )
        n_old = self._execute(f"SELECT count() FROM {db_name}.ple")[0][0]
        n_new = self._execute(f"SELECT count() FROM {db_name}.ple__migration")[0][0]
        if n_old != n_new:
            raise RuntimeError(
                f"Migration de {db_name}.ple interrompue : {n_old} lignes source, "
                f"{n_new} recopiées. La table d'origine est intacte."
            )
        self._execute(
            f"RENAME TABLE {db_name}.ple TO {db_name}.ple__old, "
            f"{db_name}.ple__migration TO {db_name}.ple"
        )
        self._execute(f"DROP TABLE {db_name}.ple__old")
        print(f"    ♻️ {db_name}.ple : clé de tri migrée (+ solde_filter), {n_new} lignes recopiées")

    def _migrate_schema(self, db_name: str):
        """Ajoute les colonnes manquantes aux tables ple créées avant l'évolution Bilan."""
        required = [
            ('type_rubrique', "LowCardinality(String) DEFAULT 'PL'"),
            ('solde_filter', "LowCardinality(String) DEFAULT ''"),
            ('exclusions', "String DEFAULT ''"),
        ]
        try:
            existing = self._execute(f"""
                SELECT name FROM system.columns
                WHERE database = '{db_name}' AND table = 'ple'
            """)
            existing_cols = {row[0] for row in existing}
        except Exception:
            existing_cols = set()

        for col_name, col_def in required:
            if col_name not in existing_cols:
                try:
                    self._execute(
                        f"ALTER TABLE {db_name}.ple ADD COLUMN IF NOT EXISTS {col_name} {col_def}"
                    )
                    print(f"    + Colonne 'ple.{col_name}' ajoutée")
                except Exception as e:
                    if "already exists" not in str(e).lower():
                        print(f"    ⚠️ Erreur ajout colonne {col_name}: {e}")

    @staticmethod
    def default_rows() -> List[Tuple]:
        """Mapping par défaut (P&L + Bilan) au format PLE_COLUMNS."""
        rows: List[Tuple] = []
        for racine, rubrique, nb_racine in PLE_MAPPING_DATA:
            rows.append((racine, rubrique, nb_racine, 'PL', '', ''))
        for racine, code_bilan, nb_racine, solde_filter, exclusions in BILAN_MAPPING_DATA:
            rows.append((racine, code_bilan, nb_racine, 'BILAN', solde_filter,
                         ','.join(exclusions) if exclusions else ''))
        return rows

    def populate_defaults(self, client_id: str):
        """Insère le mapping par défaut. N'appeler que sur une table vide."""
        db_name = self._get_db_name(client_id)
        rows = self.default_rows()
        self._execute(
            f"INSERT INTO {db_name}.ple ({', '.join(PLE_COLUMNS)}) VALUES",
            rows,
        )
        self._execute(f"OPTIMIZE TABLE {db_name}.ple FINAL")
        print(f"  ✓ Table {db_name}.ple alimentée avec le mapping par défaut "
              f"({len(PLE_MAPPING_DATA)} PL + {len(BILAN_MAPPING_DATA)} Bilan)")

    def load_index(self, client_id: str) -> PleIndex:
        """Charge le mapping du client en mémoire (une seule requête)."""
        db_name = self._get_db_name(client_id)
        rows = self._execute(f"SELECT {', '.join(PLE_COLUMNS)} FROM {db_name}.ple FINAL")
        index = PleIndex(rows)
        print(f"  📚 Mapping ple chargé : {len(index)} règles")
        return index

    def get_count(self, client_id: str) -> int:
        db_name = self._get_db_name(client_id)
        result = self._execute(f"SELECT count() FROM {db_name}.ple")
        return result[0][0]
