"""
Processor d'export Excel du Grand Livre
"""
import os
import pandas as pd
from typing import Dict, Optional
from datetime import datetime

from clickhouse.manager import ClickHouseManager
from etl.s3 import upload_file_to_s3


def export_grand_livre_excel(
    client_id: str,
    batch_id: str,
    s3_prefix: str,
    ch_manager: ClickHouseManager = None
) -> Dict:
    """
    Exporte le Grand Livre vers Excel et l'upload sur S3.
    
    Args:
        client_id: ID du client
        batch_id: ID du batch
        s3_prefix: Préfixe S3 pour l'upload
        ch_manager: Manager ClickHouse (optionnel)
    
    Returns:
        {filename, s3_url, nb_transactions}
    """
    print(f"📊 Export Excel du Grand Livre...")
    
    # Créer le manager si non fourni
    close_manager = False
    if ch_manager is None:
        ch_manager = ClickHouseManager()
        close_manager = True
    
    try:
        # Récupérer les données
        data = ch_manager.get_grand_livre_data(client_id, batch_id)
        
        if not data:
            print("  ⚠️ Aucune donnée à exporter")
            return {'filename': None, 's3_url': None, 'nb_transactions': 0}
        
        print(f"  → {len(data)} transactions à exporter")
        
        # Créer le DataFrame (23 colonnes — Rubrique P&L et Rubrique Bilan
        # côte à côte juste après Intitulé Compte).
        columns = [
            'Date GL', 'Entité', 'Compte', 'Intitulé Compte',
            'Rubrique', 'Rubrique Bilan',
            'Date Transaction', 'Code Journal', 'N° Pièce', 'N° Facture',
            'Libellé', 'N° Tiers', 'Intitulé Tiers', 'Type Tiers',
            'Débit', 'Crédit', 'Solde', 'Période', 'Batch ID', 'Row ID',
            'Compte PCG Origine', 'HAO', 'Mapping Status',
        ]

        df = pd.DataFrame(data, columns=columns)

        # Générer le nom du fichier
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"GRAND_LIVRE_{client_id}_{timestamp}.xlsx"
        local_path = f"/tmp/{filename}"

        # Écrire le fichier Excel
        with pd.ExcelWriter(local_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Grand Livre', index=False)

            # Ajuster la largeur des colonnes
            worksheet = writer.sheets['Grand Livre']
            column_widths = {
                'A': 12,  # Date GL
                'B': 15,  # Entité
                'C': 10,  # Compte
                'D': 30,  # Intitulé Compte
                'E': 10,  # Rubrique (P&L)
                'F': 14,  # Rubrique Bilan
                'G': 12,  # Date Transaction
                'H': 8,   # Code Journal
                'I': 10,  # N° Pièce
                'J': 15,  # N° Facture
                'K': 40,  # Libellé
                'L': 20,  # N° Tiers
                'M': 30,  # Intitulé Tiers
                'N': 12,  # Type Tiers
                'O': 15,  # Débit
                'P': 15,  # Crédit
                'Q': 15,  # Solde
                'R': 8,   # Période
                'S': 36,  # Batch ID
                'T': 8,   # Row ID
                'U': 15,  # Compte PCG Origine
                'V': 5,   # HAO
                'W': 18,  # Mapping Status
            }

            for col, width in column_widths.items():
                worksheet.column_dimensions[col].width = width
        
        print(f"  ✓ Fichier créé: {local_path}")

        # Récupérer la taille du fichier avant upload
        file_size = os.path.getsize(local_path)

        # Construire la clé S3 (même logique que upload_file_to_s3)
        s3_key = f"{s3_prefix}EXCEL/{filename}"

        # Upload vers S3
        s3_url = upload_file_to_s3(local_path, s3_prefix, filename)

        # Supprimer le fichier local
        os.remove(local_path)

        return {
            'filename': filename,
            's3_key': s3_key,
            's3_url': s3_url,
            'file_size': file_size,
            'nb_transactions': len(data)
        }
        
    finally:
        if close_manager:
            ch_manager.close()
