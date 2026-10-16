"""
Gestion des tables de dimension ClickHouse
"""
from typing import List, Tuple, Set
from clickhouse.base import ClickHouseBase
from clickhouse.config import DIMENSION_CONFIG


class DimensionManager(ClickHouseBase):
    """Gestion des tables de dimension"""

    def create_tables(self, client_id: str):
        """Crée les tables de dimension pour un client."""
        db_name = self._get_db_name(client_id)

        # Table Code Journal
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.code_journal (
                code_journal String,
                intitule String,
                type String,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (code_journal)
            PRIMARY KEY (code_journal)
        """)
        print(f"  ✓ Table {db_name}.code_journal prête")

        # Table Plan Comptable
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.plan_compte (
                compte String,
                intitule_compte String,
                nature_compte String,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (compte)
            PRIMARY KEY (compte)
        """)
        print(f"  ✓ Table {db_name}.plan_compte prête")

        # Table Plan Tiers (simplifiée - 3 colonnes)
        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.plan_tiers (
                compte_tiers String,
                type String,
                intitule_tiers String,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (compte_tiers)
            PRIMARY KEY (compte_tiers)
        """)
        print(f"  ✓ Table {db_name}.plan_tiers prête")

    @staticmethod
    def _column_names(table_name: str) -> List[str]:
        config = DIMENSION_CONFIG.get(table_name)
        if not config:
            raise ValueError(f"Table inconnue: {table_name}")
        return [c.strip() for c in config['columns'].strip('()').split(',')]

    @staticmethod
    def _normalize(row) -> Tuple:
        return tuple('' if v is None else str(v).strip() for v in row)

    def merge(self, client_id: str, table_name: str, data: List[Tuple]) -> dict:
        """
        Fusion NON destructive d'un fichier dans une table de dimension.

        - clé absente de la table      → ligne ajoutée
        - clé présente, valeurs différentes → ligne mise à jour
        - clé présente, valeurs identiques  → rien
        - ligne de la table absente du fichier → CONSERVÉE (jamais de suppression)

        La mise à jour repose sur le ReplacingMergeTree(updated_at) : la nouvelle
        version (updated_at plus récent) remplace l'ancienne au merge, forcé par
        OPTIMIZE FINAL. Seules les lignes nouvelles/modifiées sont réécrites.

        Returns:
            {lignes_fichier, ajoutees, modifiees, inchangees, ignorees,
             rows_ecrites: [tuples ajoutés ou modifiés]}
        """
        columns = self._column_names(table_name)
        config = DIMENSION_CONFIG[table_name]
        # Clé simple (pk_index) ou composite (pk_indexes, ex: ple)
        pk_indexes = config.get('pk_indexes') or [config['pk_index']]
        required = config.get('required_indexes', pk_indexes)
        int_idx = [columns.index(c) for c in config.get('int_columns', [])]
        db_name = self._get_db_name(client_id)

        def key_of(row):
            return tuple(row[i] for i in pk_indexes)

        def typed(row):
            # Valeurs normalisées en texte pour comparer table et fichier ;
            # les colonnes entières sont reconverties pour l'INSERT.
            return tuple(int(v) if i in int_idx else v for i, v in enumerate(row))

        stats = {
            'lignes_fichier': len(data),
            'ajoutees': 0,
            'modifiees': 0,
            'inchangees': 0,
            'ignorees': 0,
            'rows_ecrites': [],
        }

        # Dédoublonnage du fichier par clé (la dernière occurrence l'emporte).
        incoming: dict = {}
        for row in data:
            row = self._normalize(row)
            if len(row) != len(columns):
                raise ValueError(
                    f"{table_name}: ligne à {len(row)} colonnes, attendu {len(columns)} {columns}"
                )
            if any(not row[i] for i in required):
                stats['ignorees'] += 1
                continue
            incoming[key_of(row)] = row

        if not incoming:
            print(f"⚠️ Aucune donnée à intégrer dans {table_name}")
            return stats

        cols_sql = ', '.join(columns)
        existing = {}
        for r in self._execute(f"SELECT {cols_sql} FROM {db_name}.{table_name} FINAL"):
            r = self._normalize(r)
            existing[key_of(r)] = r

        to_write = []
        for key, row in incoming.items():
            old = existing.get(key)
            if old is None:
                stats['ajoutees'] += 1
                to_write.append(typed(row))
            elif old != row:
                stats['modifiees'] += 1
                to_write.append(typed(row))
            else:
                stats['inchangees'] += 1

        if to_write:
            self._execute(f"INSERT INTO {db_name}.{table_name} ({cols_sql}) VALUES", to_write)
            self._execute(f"OPTIMIZE TABLE {db_name}.{table_name} FINAL")

        stats['rows_ecrites'] = to_write
        print(
            f"  → {db_name}.{table_name} : {stats['ajoutees']} ajoutées, "
            f"{stats['modifiees']} modifiées, {stats['inchangees']} inchangées "
            f"(aucune suppression)"
        )
        return stats

    def upsert(self, client_id: str, table_name: str, data: List[Tuple]) -> dict:
        """Alias historique : la mise à jour des dimensions est une fusion non destructive."""
        return self.merge(client_id, table_name, data)

    # Colonnes dénormalisées dans grand_livre à rafraîchir quand une dimension
    # change : table → (colonne clé grand_livre, {colonne grand_livre: index dans le tuple}).
    _GL_PROPAGATION = {
        'plan_compte': ('compte', {'intitule_compte': 1}),
        'plan_tiers': ('n_tiers', {'type_tiers': 1, 'intitule_tiers': 2}),
    }

    def propagate_to_grand_livre(self, client_id: str, table_name: str,
                                 rows: List[Tuple], chunk_size: int = 500) -> int:
        """
        Répercute les intitulés/types modifiés sur les écritures déjà chargées
        dans grand_livre (qui les stocke en dur). Ne touche QUE ces colonnes,
        ne supprime aucune ligne, et n'écrase jamais une valeur par du vide.

        Returns: nombre de clés répercutées.
        """
        spec = self._GL_PROPAGATION.get(table_name)
        db_name = self._get_db_name(client_id)
        if not spec or not rows or not self._table_exists(db_name, 'grand_livre'):
            return 0

        gl_key, targets = spec
        propagated = set()
        for gl_col, idx in targets.items():
            pairs = [(r[0], r[idx]) for r in rows if r[0] and r[idx]]
            for i in range(0, len(pairs), chunk_size):
                chunk = pairs[i:i + chunk_size]
                keys = [k for k, _ in chunk]
                values = [v for _, v in chunk]
                self._execute(
                    f"""
                    ALTER TABLE {db_name}.grand_livre
                    UPDATE {gl_col} = transform({gl_key}, %(keys)s, %(values)s, {gl_col})
                    WHERE {gl_key} IN %(keys_in)s
                    """,
                    {'keys': keys, 'values': values, 'keys_in': tuple(keys)},
                    settings={'mutations_sync': 1},
                )
                propagated.update(keys)

        if propagated:
            print(f"  ↻ grand_livre : {len(propagated)} clé(s) {table_name} répercutée(s)")
        return len(propagated)

    def get_count(self, client_id: str, table_name: str) -> int:
        db_name = self._get_db_name(client_id)
        result = self._execute(f"SELECT count() FROM {db_name}.{table_name}")
        return result[0][0]

    def get_intitule_compte(self, client_id: str, compte: str) -> str:
        """Récupère l'intitulé d'un compte."""
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT intitule_compte FROM {db_name}.plan_compte
            WHERE compte = %(compte)s
        """, {'compte': compte})
        return result[0][0] if result else ""

    def get_intitule_tiers(self, client_id: str, compte_tiers: str) -> str:
        """Récupère l'intitulé d'un tiers."""
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT intitule_tiers FROM {db_name}.plan_tiers
            WHERE compte_tiers = %(compte_tiers)s
        """, {'compte_tiers': compte_tiers})
        return result[0][0] if result else ""

    def get_type_tiers(self, client_id: str, compte_tiers: str) -> str:
        """Récupère le type d'un tiers (Client/Fournisseur)."""
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT type FROM {db_name}.plan_tiers
            WHERE compte_tiers = %(compte_tiers)s
        """, {'compte_tiers': compte_tiers})
        return result[0][0] if result else ""
