"""
Gestion du Grand Livre des Tiers
"""
from typing import List, Tuple, Optional
from clickhouse.base import ClickHouseBase


class GLTiersManager(ClickHouseBase):
    """Gestion du Grand Livre des Tiers (Clients/Fournisseurs)"""

    def create_table(self, client_id: str):
        """
        Crée la table du Grand Livre des Tiers.
        
        Args:
            client_id: Identifiant du client
        """
        db_name = self._get_db_name(client_id)

        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.gl_tiers (
                date_gl String,
                entite String,
                compte_tiers String,
                type_tiers String,
                centralisateur String,
                date_transaction String,
                code_journal String,
                numero_piece String,
                libelle_ecriture String,
                debit Float64,
                credit Float64,
                solde Float64,
                periode String,
                batch_id String,
                row_id UInt32,
                updated_at DateTime DEFAULT now()
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (batch_id, periode, compte_tiers, date_transaction, code_journal, numero_piece, row_id)
            PRIMARY KEY (batch_id, periode, compte_tiers, date_transaction, code_journal, numero_piece, row_id)
        """)
        print(f"  ✓ Table {db_name}.gl_tiers prête")

    def upsert(self, client_id: str, data: List[Tuple], periode: str, batch_id: str):
        """
        Insère les transactions du Grand Livre Tiers.
        
        Args:
            client_id: Identifiant du client
            data: Liste de tuples avec les données tiers
            periode: Période comptable
            batch_id: Identifiant du batch d'import
        """
        if not data:
            print("⚠️ Aucune transaction tiers à insérer")
            return

        db_name = self._get_db_name(client_id)

        # S'assurer que la table existe
        self.create_table(client_id)

        # Supprimer les anciennes données du batch
        self._execute(f"""
            ALTER TABLE {db_name}.gl_tiers
            DELETE WHERE batch_id = %(batch_id)s
        """, {'batch_id': batch_id})

        print(f"  → Données batch {batch_id} nettoyées dans gl_tiers")

        # Ajouter période et batch_id aux données
        data_with_periode = [(*row[:12], periode, batch_id, row[12]) for row in data]

        query = f"""
            INSERT INTO {db_name}.gl_tiers
            (date_gl, entite, compte_tiers, type_tiers, centralisateur,
            date_transaction, code_journal, numero_piece, libelle_ecriture,
            debit, credit, solde, periode, batch_id, row_id)
            VALUES
        """
        self._execute(query, data_with_periode)

        self._execute(f"OPTIMIZE TABLE {db_name}.gl_tiers FINAL")
        print(f"  → {len(data)} transactions tiers insérées pour la période {periode}")

    def get_stats(self, client_id: str, periode: Optional[str] = None) -> dict:
        """
        Retourne les statistiques du Grand Livre Tiers.
        
        Args:
            client_id: Identifiant du client
            periode: Période à filtrer (optionnel)
            
        Returns:
            Dictionnaire avec les statistiques
        """
        db_name = self._get_db_name(client_id)

        where_clause = f"WHERE periode = '{periode}'" if periode else ""

        result = self._execute(f"""
            SELECT
                count() as nb_transactions,
                count(DISTINCT compte_tiers) as nb_tiers,
                sum(debit) as total_debit,
                sum(credit) as total_credit,
                countIf(type_tiers = 'Client') as nb_clients,
                countIf(type_tiers = 'Fournisseur') as nb_fournisseurs
            FROM {db_name}.gl_tiers
            {where_clause}
        """)

        row = result[0]
        return {
            'nb_transactions': row[0],
            'nb_tiers': row[1],
            'total_debit': row[2],
            'total_credit': row[3],
            'nb_clients': row[4],
            'nb_fournisseurs': row[5]
        }

    def get_by_tiers(self, client_id: str, compte_tiers: str, periode: Optional[str] = None) -> List[Tuple]:
        """
        Retourne les transactions pour un tiers donné.
        
        Args:
            client_id: Identifiant du client
            compte_tiers: Numéro de compte tiers
            periode: Période à filtrer (optionnel)
            
        Returns:
            Liste des transactions
        """
        db_name = self._get_db_name(client_id)

        where_clause = "WHERE compte_tiers = %(compte_tiers)s"
        params = {'compte_tiers': compte_tiers}

        if periode:
            where_clause += " AND periode = %(periode)s"
            params['periode'] = periode

        return self._execute(f"""
            SELECT *
            FROM {db_name}.gl_tiers
            {where_clause}
            ORDER BY date_transaction, row_id
        """, params)

    def get_by_type(self, client_id: str, type_tiers: str, periode: Optional[str] = None) -> List[Tuple]:
        """
        Retourne les transactions par type de tiers.
        
        Args:
            client_id: Identifiant du client
            type_tiers: Type de tiers (Client, Fournisseur)
            periode: Période à filtrer (optionnel)
            
        Returns:
            Liste des transactions
        """
        db_name = self._get_db_name(client_id)

        where_clause = "WHERE type_tiers = %(type_tiers)s"
        params = {'type_tiers': type_tiers}

        if periode:
            where_clause += " AND periode = %(periode)s"
            params['periode'] = periode

        return self._execute(f"""
            SELECT *
            FROM {db_name}.gl_tiers
            {where_clause}
            ORDER BY compte_tiers, date_transaction, row_id
        """, params)

    def delete_batch(self, client_id: str, batch_id: str):
        """
        Supprime les données d'un batch spécifique.
        
        Args:
            client_id: Identifiant du client
            batch_id: Identifiant du batch à supprimer
        """
        db_name = self._get_db_name(client_id)

        self._execute(f"""
            ALTER TABLE {db_name}.gl_tiers
            DELETE WHERE batch_id = %(batch_id)s
        """, {'batch_id': batch_id})

        print(f"  → Batch {batch_id} supprimé de gl_tiers")
