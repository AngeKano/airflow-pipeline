"""
Gestion du Grand Livre ClickHouse
Version simplifiée - Plus de fusion, lecture directe du fichier unique
"""
from typing import List, Tuple, Optional
from clickhouse.base import ClickHouseBase


class GrandLivreManager(ClickHouseBase):
    """Gestion du Grand Livre unifié"""

    # Colonnes requises avec leur type et valeur par défaut
    REQUIRED_COLUMNS = {
        'date_gl': ('String', None),
        'entite': ('String', None),
        'compte': ('String', None),
        'intitule_compte': ('String', "''"),
        'rubrique': ('String', "''"),
        'date_transaction': ('String', None),
        'code_journal': ('String', None),
        'numero_piece': ('String', None),
        'numero_facture': ('String', "''"),
        'libelle_ecriture': ('String', None),
        'n_tiers': ('String', "''"),
        'intitule_tiers': ('String', "''"),
        'type_tiers': ('String', "''"),
        'debit': ('Float64', None),
        'credit': ('Float64', None),
        'solde': ('Float64', None),
        'periode': ('String', None),
        'batch_id': ('String', None),
        'row_id': ('UInt32', None),
        # Traçabilité du mapping PCG → SYSCOHADA (vide si source déjà SYSCOHADA)
        'compte_pcg_origine': ('String', "''"),
        'is_hao': ('UInt8', '0'),
        'mapping_status': ('String', "'none'"),
        'updated_at': ('DateTime', 'now()'),
    }

    def create_table(self, client_id: str):
        """Crée la table du Grand Livre avec n_tiers et n_facture."""
        db_name = self._get_db_name(client_id)

        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.grand_livre (
                date_gl String,
                entite String,
                compte String,
                intitule_compte String DEFAULT '',
                rubrique String DEFAULT '',
                date_transaction String,
                code_journal String,
                numero_piece String,
                numero_facture String DEFAULT '',
                libelle_ecriture String,
                n_tiers String DEFAULT '',
                intitule_tiers String DEFAULT '',
                type_tiers String DEFAULT '',
                debit Float64,
                credit Float64,
                solde Float64,
                periode String,
                batch_id String,
                row_id UInt32,
                compte_pcg_origine String DEFAULT '',
                is_hao UInt8 DEFAULT 0,
                mapping_status String DEFAULT 'none',
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (batch_id, periode, compte, date_transaction, code_journal, numero_piece, row_id)
            PRIMARY KEY (batch_id, periode, compte, date_transaction, code_journal, numero_piece, row_id)
        """)
        
        # Migrer le schéma si nécessaire
        self._migrate_schema(db_name)
        
        print(f"  ✓ Table {db_name}.grand_livre prête")

    def _migrate_schema(self, db_name: str):
        """Ajoute les colonnes manquantes à la table existante."""
        # Récupérer les colonnes existantes
        existing_columns = self._get_existing_columns(db_name)
        
        # Ajouter les colonnes manquantes
        for col_name, (col_type, default_val) in self.REQUIRED_COLUMNS.items():
            if col_name not in existing_columns:
                default_clause = f" DEFAULT {default_val}" if default_val else ""
                try:
                    self._execute(f"""
                        ALTER TABLE {db_name}.grand_livre
                        ADD COLUMN IF NOT EXISTS {col_name} {col_type}{default_clause}
                    """)
                    print(f"    + Colonne '{col_name}' ajoutée")
                except Exception as e:
                    # Ignorer si la colonne existe déjà
                    if "already exists" not in str(e).lower():
                        print(f"    ⚠️ Erreur ajout colonne {col_name}: {e}")

    def _get_existing_columns(self, db_name: str) -> set:
        """Récupère la liste des colonnes existantes."""
        try:
            result = self._execute(f"""
                SELECT name FROM system.columns 
                WHERE database = '{db_name}' AND table = 'grand_livre'
            """)
            return {row[0] for row in result}
        except Exception:
            return set()

    def upsert(self, client_id: str, data: List[Tuple], periode: str, batch_id: str):
        """
        Insère les transactions du Grand Livre.

        Format data attendu (22 colonnes):
        (date_gl, entite, compte, intitule_compte, rubrique, date_transaction,
         code_journal, numero_piece, numero_facture, libelle_ecriture,
         n_tiers, intitule_tiers, type_tiers, debit, credit, solde,
         periode, batch_id, row_id,
         compte_pcg_origine, is_hao, mapping_status)
        """
        if not data:
            print("⚠️ Aucune transaction à insérer")
            return

        # Sanity check : on s'attend à 22 colonnes par tuple. Les anciennes
        # versions de enrich_grand_livre produisaient 19 colonnes ; on les
        # rejette explicitement pour éviter un INSERT silencieusement corrompu.
        if len(data[0]) != 22:
            raise ValueError(
                f"upsert_grand_livre: tuples de {len(data[0])} colonnes reçus, "
                f"attendu 22 (sortie de enrich_grand_livre). "
                f"Mettre à jour les appelants."
            )

        db_name = self._get_db_name(client_id)

        # S'assurer que le schéma est à jour avant l'insertion
        self._migrate_schema(db_name)

        # Supprimer les anciennes données du batch
        self._execute(f"""
            ALTER TABLE {db_name}.grand_livre
            DELETE WHERE batch_id = %(batch_id)s
        """, {'batch_id': batch_id})

        print(f"  → Données batch {batch_id} nettoyées")

        query = f"""
            INSERT INTO {db_name}.grand_livre (
                date_gl, entite, compte, intitule_compte, rubrique,
                date_transaction, code_journal, numero_piece, numero_facture,
                libelle_ecriture, n_tiers, intitule_tiers, type_tiers,
                debit, credit, solde, periode, batch_id, row_id,
                compte_pcg_origine, is_hao, mapping_status
            ) VALUES
        """
        self._execute(query, data)

        self._execute(f"OPTIMIZE TABLE {db_name}.grand_livre FINAL")
        print(f"  → {len(data)} transactions insérées pour la période {periode}")

    def get_stats(self, client_id: str, periode: Optional[str] = None) -> dict:
        """Retourne les statistiques du Grand Livre."""
        db_name = self._get_db_name(client_id)

        where_clause = f"WHERE periode = '{periode}'" if periode else ""

        result = self._execute(f"""
            SELECT
                count() as nb_transactions,
                count(DISTINCT compte) as nb_comptes,
                count(DISTINCT rubrique) as nb_rubriques,
                countIf(n_tiers != '') as nb_avec_tiers,
                countIf(numero_facture != '') as nb_avec_facture,
                sum(debit) as total_debit,
                sum(credit) as total_credit
            FROM {db_name}.grand_livre
            {where_clause}
        """)

        row = result[0]
        return {
            'nb_transactions': row[0],
            'nb_comptes': row[1],
            'nb_rubriques': row[2],
            'nb_avec_tiers': row[3],
            'nb_avec_facture': row[4],
            'total_debit': row[5],
            'total_credit': row[6],
            'equilibre': abs(row[5] - row[6]) < 0.01
        }

    def get_data(self, client_id: str, batch_id: str) -> List[Tuple]:
        """Récupère toutes les données du grand livre pour export (22 colonnes)."""
        db_name = self._get_db_name(client_id)

        return self._execute(f"""
            SELECT
                date_gl, entite, compte, intitule_compte, rubrique,
                date_transaction, code_journal, numero_piece, numero_facture,
                libelle_ecriture, n_tiers, intitule_tiers, type_tiers,
                debit, credit, solde, periode, batch_id, row_id,
                compte_pcg_origine, is_hao, mapping_status
            FROM {db_name}.grand_livre
            WHERE batch_id = %(batch_id)s
            ORDER BY compte, date_transaction, row_id
        """, {'batch_id': batch_id})

    def get_balance_par_rubrique(self, client_id: str, periode: str) -> List[dict]:
        """Retourne la balance par rubrique."""
        db_name = self._get_db_name(client_id)

        result = self._execute(f"""
            SELECT
                rubrique,
                sum(debit) as total_debit,
                sum(credit) as total_credit,
                sum(debit) - sum(credit) as solde,
                count() as nb_ecritures
            FROM {db_name}.grand_livre
            WHERE periode = %(periode)s AND rubrique != ''
            GROUP BY rubrique
            ORDER BY rubrique
        """, {'periode': periode})

        return [
            {
                'rubrique': row[0],
                'total_debit': row[1],
                'total_credit': row[2],
                'solde': row[3],
                'nb_ecritures': row[4]
            }
            for row in result
        ]

    def delete_batch(self, client_id: str, batch_id: str):
        db_name = self._get_db_name(client_id)
        self._execute(f"""
            ALTER TABLE {db_name}.grand_livre
            DELETE WHERE batch_id = %(batch_id)s
        """, {'batch_id': batch_id})
        print(f"  → Batch {batch_id} supprimé")