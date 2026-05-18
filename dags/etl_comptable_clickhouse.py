"""
DAG ETL Comptable REPFI - Version 3.0
Format 4 fichiers avec Grand Livre unifié
"""
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from etl.config import DEFAULT_ARGS, ETLStatus
from etl.postgres import update_etl_status, insert_generated_file, get_batch_info
from etl.s3 import download_files_from_s3, validate_files, cleanup_local_files
from etl.parsers import (
    parse_plan_compte,
    parse_code_journal,
    parse_plan_tiers,
    parse_grand_livre,
)
from etl.processors import enrich_grand_livre, export_grand_livre_excel
from clickhouse.manager import ClickHouseManager


# ============================================================
# TASKS
# ============================================================

def task_download_files(**context):
    """Télécharge les fichiers depuis S3 et crée la base ClickHouse."""
    params = context['params']
    client_id = params['client_id']
    batch_id = params['batch_id']
    s3_prefix = params['s3_prefix']
    
    print(f"🚀 Démarrage ETL pour client: {client_id}, batch: {batch_id}")
    
    # Mettre à jour le statut
    update_etl_status(batch_id, ETLStatus.VALIDATING, 10)
    
    # Télécharger les fichiers
    downloaded_files = download_files_from_s3(client_id, batch_id, s3_prefix)
    
    # Valider la présence des fichiers requis
    if not validate_files(downloaded_files):
        raise ValueError("Fichiers manquants")
    
    update_etl_status(batch_id, ETLStatus.VALIDATING, 20)
    
    # Créer la base ClickHouse
    with ClickHouseManager() as ch:
        ch.create_client_database(client_id)
    
    update_etl_status(batch_id, ETLStatus.VALIDATING, 30)
    
    # Retourner les chemins pour les tâches suivantes
    return {
        'client_id': client_id,
        'batch_id': batch_id,
        's3_prefix': s3_prefix,
        'files': downloaded_files,
        'local_dir': f"/tmp/etl_{client_id}_{batch_id}"
    }


def task_process_plan_compte(**context):
    """Parse et charge le Plan Comptable."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')
    
    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('plan_comptes')
    
    if not file_path:
        print("⚠️ Fichier Plan Comptable non trouvé")
        return
    
    result = parse_plan_compte(file_path, client_id)
    
    with ClickHouseManager() as ch:
        ch.upsert_dimension(client_id, 'plan_compte', result['data'])
    
    update_etl_status(batch_id, ETLStatus.VALIDATING, 40)
    
    return result['stats']


def task_process_code_journal(**context):
    """Parse et charge les Codes Journaux."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')
    
    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('code_journal')
    
    if not file_path:
        print("⚠️ Fichier Codes Journaux non trouvé")
        return
    
    result = parse_code_journal(file_path, client_id)
    
    with ClickHouseManager() as ch:
        ch.upsert_dimension(client_id, 'code_journal', result['data'])
    
    update_etl_status(batch_id, ETLStatus.VALIDATING, 50)
    
    return result['stats']


def task_process_plan_tiers(**context):
    """Parse et charge le Plan Tiers."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')
    
    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('plan_tiers')
    
    if not file_path:
        print("⚠️ Fichier Plan Tiers non trouvé")
        return
    
    result = parse_plan_tiers(file_path, client_id)
    
    with ClickHouseManager() as ch:
        ch.upsert_dimension(client_id, 'plan_tiers', result['data'])
    
    update_etl_status(batch_id, ETLStatus.VALIDATING, 60)
    
    return result['stats']


def task_process_grand_livre(**context):
    """Parse, enrichit et charge le Grand Livre."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')
    
    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('grand_livre')
    
    if not file_path:
        raise ValueError("Fichier Grand Livre non trouvé")
    
    update_etl_status(batch_id, ETLStatus.PROCESSING, 70)
    
    # Parser le Grand Livre
    result = parse_grand_livre(file_path, client_id, batch_id)
    
    with ClickHouseManager() as ch:
        # Enrichir avec rubriques et infos tiers
        enriched_data = enrich_grand_livre(client_id, result['data'], ch)
        
        # Charger dans ClickHouse
        ch.upsert_grand_livre(
            client_id,
            enriched_data,
            result['periode'],
            batch_id
        )
    
    update_etl_status(batch_id, ETLStatus.PROCESSING, 85)
    
    return {
        'periode': result['periode'],
        'stats': result['stats']
    }


def task_export_excel(**context):
    """Exporte le Grand Livre vers Excel et enregistre le fichier en base."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')

    client_id = data['client_id']
    batch_id = data['batch_id']
    s3_prefix = data['s3_prefix']

    update_etl_status(batch_id, ETLStatus.PROCESSING, 90)

    # Générer et uploader le fichier Excel
    result = export_grand_livre_excel(client_id, batch_id, s3_prefix)

    # Enregistrer le fichier généré dans PostgreSQL (comptable_files)
    if result.get('s3_url'):
        # Récupérer les infos du batch pour period_start/end et uploadedById
        batch_info = get_batch_info(batch_id)

        if batch_info:
            insert_generated_file(
                batch_id=batch_id,
                client_id=client_id,
                uploaded_by_id=batch_info.get('uploaded_by_id', 'system'),
                filename=result['filename'],
                s3_key=result['s3_key'],
                s3_url=result['s3_url'],
                file_size=result.get('file_size', 0),
                period_start=batch_info['start_date'],
                period_end=batch_info['end_date'],
                file_type='GRAND_LIVRE',
            )
        else:
            print(f"  ⚠️ Impossible de récupérer les infos du batch {batch_id}")

    update_etl_status(batch_id, ETLStatus.PROCESSING, 95, s3_url=result.get('s3_url'))

    return result


def task_finalize(**context):
    """Finalise l'ETL et nettoie les fichiers temporaires."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')
    gl_result = ti.xcom_pull(task_ids='process_grand_livre')
    export_result = ti.xcom_pull(task_ids='export_excel')
    
    batch_id = data['batch_id']
    local_dir = data['local_dir']
    
    # Nettoyer les fichiers temporaires
    cleanup_local_files(local_dir)
    
    # Mettre à jour le statut final
    update_etl_status(batch_id, ETLStatus.COMPLETED, 100)
    
    print("=" * 60)
    print("🎉 ETL TERMINÉ AVEC SUCCÈS")
    print("=" * 60)
    if gl_result:
        stats = gl_result.get('stats', {})
        print(f"  📊 Transactions: {stats.get('nb_transactions', 0)}")
        print(f"  📊 Comptes: {stats.get('nb_comptes', 0)}")
        print(f"  📊 Avec tiers: {stats.get('nb_avec_tiers', 0)}")
        print(f"  📊 Avec facture: {stats.get('nb_avec_facture', 0)}")
    if export_result:
        print(f"  📁 Export: {export_result.get('filename')}")


def task_handle_failure(**context):
    """Gère les erreurs de l'ETL."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')
    
    if data:
        batch_id = data.get('batch_id')
        local_dir = data.get('local_dir')
        
        if batch_id:
            update_etl_status(batch_id, ETLStatus.FAILED, 0)
        
        if local_dir:
            cleanup_local_files(local_dir)
    
    print("❌ ETL ÉCHOUÉ")


# ============================================================
# DAG
# ============================================================

with DAG(
    dag_id='etl_comptable_clickhouse',
    default_args=DEFAULT_ARGS,
    description='ETL Comptable REPFI v3 - Grand Livre unifié',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['repfi', 'etl', 'comptable', 'clickhouse'],
) as dag:
    
    # Téléchargement et initialisation
    download = PythonOperator(
        task_id='download_files',
        python_callable=task_download_files,
    )
    
    # Traitement des dimensions (en parallèle)
    plan_compte = PythonOperator(
        task_id='process_plan_compte',
        python_callable=task_process_plan_compte,
    )
    
    code_journal = PythonOperator(
        task_id='process_code_journal',
        python_callable=task_process_code_journal,
    )
    
    plan_tiers = PythonOperator(
        task_id='process_plan_tiers',
        python_callable=task_process_plan_tiers,
    )
    
    # Traitement du Grand Livre (après les dimensions)
    grand_livre = PythonOperator(
        task_id='process_grand_livre',
        python_callable=task_process_grand_livre,
    )
    
    # Export Excel
    export = PythonOperator(
        task_id='export_excel',
        python_callable=task_export_excel,
    )
    
    # Finalisation
    finalize = PythonOperator(
        task_id='finalize',
        python_callable=task_finalize,
    )
    
    # Gestion des erreurs
    handle_failure = PythonOperator(
        task_id='handle_failure',
        python_callable=task_handle_failure,
        trigger_rule=TriggerRule.ONE_FAILED,
    )
    
    # Workflow
    download >> [plan_compte, code_journal, plan_tiers]
    [plan_compte, code_journal, plan_tiers] >> grand_livre >> export >> finalize
    [download, plan_compte, code_journal, plan_tiers, grand_livre, export] >> handle_failure
