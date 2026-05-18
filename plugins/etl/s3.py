"""
Module S3 pour REPFI ETL
Téléchargement et upload des fichiers comptables
"""
import os
import boto3
from typing import Dict, List, Optional

from etl.config import S3_CONFIG, FOLDER_TO_FILE_TYPE, FILE_TYPES


def get_s3_client():
    """Crée un client S3."""
    return boto3.client(
        's3',
        region_name=S3_CONFIG['region'],
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY')
    )


def download_files_from_s3(client_id: str, batch_id: str, s3_prefix: str) -> Dict[str, str]:
    """
    Télécharge les fichiers depuis S3.
    
    Args:
        client_id: ID du client
        batch_id: ID du batch
        s3_prefix: Préfixe S3 (ex: "client123/DSF/2024/periode-01-12/")
    
    Returns:
        Dict[file_type, local_path] pour chaque fichier téléchargé
    """
    print(f"📥 Téléchargement depuis S3: {s3_prefix}")
    
    s3 = get_s3_client()
    bucket = S3_CONFIG['bucket_name']
    
    # Créer le dossier local
    local_dir = f"/tmp/etl_{client_id}_{batch_id}"
    os.makedirs(local_dir, exist_ok=True)
    
    downloaded_files = {}
    
    try:
        # Lister les objets dans le préfixe
        response = s3.list_objects_v2(Bucket=bucket, Prefix=s3_prefix)
        
        if 'Contents' not in response:
            print(f"  ⚠️ Aucun fichier trouvé dans {s3_prefix}")
            return downloaded_files
        
        for obj in response['Contents']:
            key = obj['Key']
            
            # Ignorer les dossiers
            if key.endswith('/'):
                continue
            
            # Extraire le nom du fichier et le dossier
            parts = key.replace(s3_prefix, '').split('/')
            if len(parts) < 2:
                continue
            
            folder = parts[0].upper()
            filename = parts[-1]
            
            # Mapper le dossier au type de fichier
            file_type = FOLDER_TO_FILE_TYPE.get(folder)
            if not file_type:
                print(f"    ⚠️ Dossier non reconnu: {folder}")
                continue
            
            # Télécharger le fichier
            local_path = os.path.join(local_dir, f"{file_type}_{filename}")
            s3.download_file(bucket, key, local_path)
            
            downloaded_files[file_type] = local_path
            print(f"  ✓ {file_type}: {filename}")
        
        print(f"📥 {len(downloaded_files)} fichiers téléchargés")
        return downloaded_files
        
    except Exception as e:
        print(f"❌ Erreur téléchargement S3: {e}")
        raise


def validate_files(downloaded_files: Dict[str, str], required_types: List[str] = None) -> bool:
    """
    Valide que tous les fichiers requis sont présents.
    
    Args:
        downloaded_files: Dict des fichiers téléchargés
        required_types: Liste des types requis (défaut: FILE_TYPES)
    
    Returns:
        True si tous les fichiers requis sont présents
    """
    if required_types is None:
        required_types = FILE_TYPES
    
    missing = []
    for file_type in required_types:
        if file_type not in downloaded_files:
            missing.append(file_type)
    
    if missing:
        print(f"❌ Fichiers manquants: {missing}")
        return False
    
    print(f"✅ Tous les fichiers requis présents ({len(required_types)}/{len(required_types)})")
    return True


def upload_file_to_s3(local_path: str, s3_prefix: str, filename: str) -> str:
    """
    Upload un fichier vers S3.
    
    Args:
        local_path: Chemin local du fichier
        s3_prefix: Préfixe S3 de destination
        filename: Nom du fichier dans S3
    
    Returns:
        URL S3 du fichier uploadé
    """
    s3 = get_s3_client()
    bucket = S3_CONFIG['bucket_name']
    
    # Construire la clé S3
    s3_key = f"{s3_prefix}EXCEL/{filename}"
    
    # Upload
    s3.upload_file(local_path, bucket, s3_key)
    
    s3_url = f"s3://{bucket}/{s3_key}"
    print(f"📤 Fichier uploadé: {s3_url}")
    
    return s3_url


def cleanup_local_files(local_dir: str):
    """Supprime les fichiers locaux temporaires."""
    import shutil
    try:
        if os.path.exists(local_dir):
            shutil.rmtree(local_dir)
            print(f"🧹 Dossier temporaire supprimé: {local_dir}")
    except Exception as e:
        print(f"⚠️ Erreur nettoyage: {e}")
