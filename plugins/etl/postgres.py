"""
Module PostgreSQL pour REPFI ETL
Gestion des statuts et métadonnées
"""
import os
import psycopg2
from urllib.parse import urlparse
from typing import Optional, Dict
from datetime import datetime
from etl.config import DATABASE_URL


def get_postgres_connection():
    """Crée une connexion PostgreSQL."""
    parsed = urlparse(DATABASE_URL)
    
    # Gérer le host Docker
    host = parsed.hostname
    if host == 'host.docker.internal':
        try:
            import socket
            socket.gethostbyname(host)
        except socket.gaierror:
            host = 'localhost'
    
    return psycopg2.connect(
        host=host,
        port=parsed.port or 5432,
        database=parsed.path[1:],
        user=parsed.username,
        password=parsed.password
    )


def update_etl_status(batch_id: str, status: str, progress: int = 0,
                      s3_url: Optional[str] = None):
    """
    Met à jour le statut ETL dans PostgreSQL.

    Tables mises à jour:
    - comptable_periods.status + progress + excelFileUrl (si s3_url fourni)
    - comptable_files.processingStatus
    """
    conn = None
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()

        # Mise à jour de comptable_periods
        if s3_url:
            cur.execute("""
                UPDATE comptable_periods
                SET status = %s,
                    progress = %s,
                    "excelFileUrl" = %s
                WHERE "batchId" = %s
            """, (status, progress, s3_url, batch_id))
        else:
            cur.execute("""
                UPDATE comptable_periods
                SET status = %s,
                    progress = %s
                WHERE "batchId" = %s
            """, (status, progress, batch_id))

        # Mettre à jour le processingStatus des fichiers du batch
        cur.execute("""
            UPDATE comptable_files
            SET "processingStatus" = %s
            WHERE "batchId" = %s
        """, (status, batch_id))

        conn.commit()
        print(f"  📊 Status mis à jour: {status} ({progress}%)")
        if s3_url:
            print(f"  📁 excelFileUrl mis à jour: {s3_url}")

    except Exception as e:
        print(f"  ⚠️ Erreur mise à jour status: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def insert_generated_file(
    batch_id: str,
    client_id: str,
    uploaded_by_id: str,
    filename: str,
    s3_key: str,
    s3_url: str,
    file_size: int,
    period_start: datetime,
    period_end: datetime,
    file_type: str = 'GRAND_LIVRE',
    file_year: int = None,
):
    """
    Insère le fichier Excel généré dans comptable_files.

    Enregistre le fichier final (ex: GRAND_LIVRE_xxx.xlsx) avec son lien S3
    pour qu'il soit accessible depuis l'application.

    Args:
        batch_id: ID du batch
        client_id: ID du client
        uploaded_by_id: ID de l'utilisateur ayant lancé le traitement
        filename: Nom du fichier (ex: GRAND_LIVRE_xxx_20260220_095255.xlsx)
        s3_key: Clé S3 complète (ex: ENVOL_xxx/.../EXCEL/GRAND_LIVRE_xxx.xlsx)
        s3_url: URL S3 complète (ex: s3://repfi/ENVOL_xxx/.../EXCEL/GRAND_LIVRE_xxx.xlsx)
        file_size: Taille du fichier en octets
        period_start: Début de la période comptable
        period_end: Fin de la période comptable
        file_type: Type de fichier (défaut: GRAND_LIVRE)
        file_year: Année du fichier (défaut: année de period_start)
    """
    conn = None
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()

        if file_year is None:
            file_year = period_start.year if isinstance(period_start, datetime) else datetime.now().year

        # Générer un cuid-like ID
        import hashlib
        import time
        raw = f"{batch_id}{filename}{time.time()}"
        file_id = hashlib.sha256(raw.encode()).hexdigest()[:25]

        cur.execute("""
            INSERT INTO comptable_files (
                id, "fileName", "fileType", "fileYear",
                "s3Key", "s3Url", "fileSize", "mimeType",
                status, "processingStatus",
                "batchId", "periodStart", "periodEnd",
                "clientId", "uploadedById",
                "uploadedAt", "processedAt"
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                %s, %s
            )
        """, (
            file_id, filename, file_type, file_year,
            s3_key, s3_url, file_size,
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'SUCCES', 'COMPLETED',
            batch_id, period_start, period_end,
            client_id, uploaded_by_id,
            datetime.now(), datetime.now()
        ))

        conn.commit()
        print(f"  📁 Fichier généré enregistré en base: {filename}")
        print(f"  📁 S3 URL: {s3_url}")

    except Exception as e:
        print(f"  ⚠️ Erreur insertion fichier généré: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def get_batch_info(batch_id: str) -> Optional[Dict]:
    """
    Récupère les informations d'un batch.

    Inclut le uploadedById depuis le premier fichier du batch
    pour pouvoir l'utiliser lors de l'insertion du fichier généré.
    """
    conn = None
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT
                cp.id,
                cp."clientId",
                cp."batchId",
                cp."periodStart",
                cp."periodEnd",
                cp.status,
                c.name as client_name,
                (
                    SELECT cf."uploadedById"
                    FROM comptable_files cf
                    WHERE cf."batchId" = cp."batchId"
                    LIMIT 1
                ) as uploaded_by_id
            FROM comptable_periods cp
            LEFT JOIN clients c ON cp."clientId" = c.id
            WHERE cp."batchId" = %s
        """, (batch_id,))

        row = cur.fetchone()
        if row:
            return {
                'id': row[0],
                'client_id': row[1],
                'batch_id': row[2],
                'start_date': row[3],
                'end_date': row[4],
                'status': row[5],
                'client_name': row[6],
                'uploaded_by_id': row[7]
            }
        return None

    except Exception as e:
        print(f"  ⚠️ Erreur récupération batch: {e}")
        return None
    finally:
        if conn:
            conn.close()