"""
Gestion du Grand Livre des Comptes
"""
from typing import List, Tuple, Optional
from clickhouse.base import ClickHouseBase


class GLCompteManager(ClickHouseBase):
    """Gestion du Grand Livre des Comptes"""

    def create_table(self, client_id: str):
        """
        Crée la table du Grand Livre des Comptes.
        
        Args:
            client_id: Identifiant du client
        """
        db_name = self._get_db_name(client_id)

        self._execute(f"""
            CREATE TABLE IF NOT EXISTS {db_name}.gl_compte (
                date_gl String,
                entite String,
                compte String,
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
            ORDER BY (batch_id, periode, compte, date_transaction, code_journal, numero_piece, row_id)
            PRIMARY KEY (batch_id, periode, compte, date_transaction, code_journal, numero_piece, row_id)
        """)
        print(f"  ✓ Table {db_name}.gl_compte prête")

    def upsert(self, client_id: str, data: List[Tuple], periode: str, batch_id: str):
        """
        Insère les transactions du Grand Livre.
        
        Args:
            client_id: Identifiant du client
            data: Liste de tuples (date_gl, entite, compte, date_transaction, 
                  code_journal, numero_piece, libelle_ecriture, debit, credit, solde, row_id)
            periode: Période comptable (ex: "2024-01")
            batch_id: Identifiant du batch d'import
        """
        if not data:
            print("⚠️ Aucune transaction à insérer")
            return

        db_name = self._get_db_name(client_id)

        # Supprimer les anciennes données du batch
        self._execute(f"""
            ALTER TABLE {db_name}.gl_compte
            DELETE WHERE batch_id = %(batch_id)s
        """, {'batch_id': batch_id})

        print(f"  → Données batch {batch_id} nettoyées dans gl_compte")

        # Ajouter période et batch_id aux données
        data_with_periode = [(*row[:10], periode, batch_id, row[10]) for row in data]

        query = f"""
            INSERT INTO {db_name}.gl_compte
            (date_gl, entite, compte, date_transaction, code_journal,
            numero_piece, libelle_ecriture, debit, credit, solde, periode, batch_id, row_id)
            VALUES
        """
        self._execute(query, data_with_periode)

        self._execute(f"OPTIMIZE TABLE {db_name}.gl_compte FINAL")
        print(f"  → {len(data)} transactions insérées pour la période {periode}")

    def get_periodes(self, client_id: str) -> List[str]:
        """
        Retourne la liste des périodes disponibles.
        
        Args:
            client_id: Identifiant du client
            
        Returns:
            Liste des périodes triées par ordre décroissant
        """
        db_name = self._get_db_name(client_id)
        result = self._execute(f"""
            SELECT DISTINCT periode
            FROM {db_name}.gl_compte
            ORDER BY periode DESC
        """)
        return [row[0] for row in result]

    def get_stats(self, client_id: str, periode: Optional[str] = None) -> dict:
        """
        Retourne les statistiques du Grand Livre.
        
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
                count(DISTINCT compte) as nb_comptes,
                sum(debit) as total_debit,
                sum(credit) as total_credit
            FROM {db_name}.gl_compte
            {where_clause}
        """)

        row = result[0]
        return {
            'nb_transactions': row[0],
            'nb_comptes': row[1],
            'total_debit': row[2],
            'total_credit': row[3],
            'equilibre': abs(row[2] - row[3]) < 0.01
        }

    def get_by_compte(self, client_id: str, compte: str, periode: Optional[str] = None) -> List[Tuple]:
        """
        Retourne les transactions pour un compte donné.
        
        Args:
            client_id: Identifiant du client
            compte: Numéro de compte
            periode: Période à filtrer (optionnel)
            
        Returns:
            Liste des transactions
        """
        db_name = self._get_db_name(client_id)

        where_clause = f"WHERE compte = %(compte)s"
        params = {'compte': compte}

        if periode:
            where_clause += " AND periode = %(periode)s"
            params['periode'] = periode

        return self._execute(f"""
            SELECT *
            FROM {db_name}.gl_compte
            {where_clause}
            ORDER BY date_transaction, row_id
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
            ALTER TABLE {db_name}.gl_compte
            DELETE WHERE batch_id = %(batch_id)s
        """, {'batch_id': batch_id})

        print(f"  → Batch {batch_id} supprimé de gl_compte")
