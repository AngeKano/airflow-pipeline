"""
DAG ETL Comptable REPFI - Version 3.0
Format 4 fichiers avec Grand Livre unifié
"""
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.trigger_rule import TriggerRule

from etl.config import DEFAULT_ARGS, ETLStatus
from etl.postgres import (
    update_etl_status,
    insert_generated_file,
    get_batch_info,
    update_files_error_message,
    update_period_plan_source,
)
from etl.s3 import download_files_from_s3, validate_files, cleanup_local_files
from etl.parsers import (
    parse_plan_compte,
    parse_code_journal,
    parse_plan_tiers,
    parse_grand_livre,
    parse_sage_pnm,
    parse_sage_pnc,
)
from etl.processors import enrich_grand_livre, export_grand_livre_excel
from etl.format_detect import detect_format, validate_format
from etl.mapping import detect_plan_source, map_compte
from clickhouse.manager import ClickHouseManager


# ============================================================
# HELPERS
# ============================================================

def _capture_error(batch_id: str, exc: Exception) -> None:
    """
    Écrit le message d'exception sur tous les ComptableFile du batch
    (champ errorMessage). Le front affichera ce message sur la page de
    statut quand le batch est en FAILED.

    Best-effort : si l'écriture Postgres échoue, on log mais on ne masque
    pas l'exception métier d'origine.
    """
    try:
        update_files_error_message(batch_id, f"{type(exc).__name__}: {exc}")
    except Exception as e:
        print(f"  ⚠️ _capture_error: impossible d'écrire errorMessage: {e}")


# ============================================================
# TASKS
# ============================================================

def task_download_files(**context):
    """Télécharge les fichiers depuis S3 et crée la base ClickHouse."""
    params = context['params']
    client_id = params['client_id']
    batch_id = params['batch_id']
    s3_prefix = params['s3_prefix']

    try:
        print(f"🚀 Démarrage ETL pour client: {client_id}, batch: {batch_id}")

        # Mettre à jour le statut
        update_etl_status(batch_id, ETLStatus.VALIDATING, 10)

        # Télécharger les fichiers
        downloaded_files = download_files_from_s3(client_id, batch_id, s3_prefix)

        # Valider la présence des fichiers requis
        if not validate_files(downloaded_files):
            raise ValueError("Fichiers manquants : les 4 fichiers comptables ne sont pas tous présents dans S3")

        # Valider que chaque fichier est dans un format autorisé pour son type
        file_formats = {}
        for file_type, path in downloaded_files.items():
            fmt = detect_format(path)
            validate_format(file_type, fmt)  # lève ValueError si non autorisé
            file_formats[file_type] = fmt
            print(f"  ✓ {file_type}: format '{fmt}' OK")

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
            'file_formats': file_formats,
            'local_dir': f"/tmp/etl_{client_id}_{batch_id}"
        }
    except Exception as exc:
        _capture_error(batch_id, exc)
        raise


def task_process_plan_compte(**context):
    """Parse et charge le Plan Comptable + détecte le plan source (PCG/SYSCOHADA)."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')

    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('plan_comptes')

    if not file_path:
        print("⚠️ Fichier Plan Comptable non trouvé")
        return

    result = parse_plan_compte(file_path, client_id)

    # Détection du plan source à partir des comptes du plan comptable.
    # data = [(compte, type, intitule, nature), ...] → col[0] = compte
    comptes = [row[0] for row in result['data']]
    plan_source = detect_plan_source(comptes)
    print(f"  📋 Plan source détecté (plan_compte): {plan_source}")

    # Si le plan source est PCG, on mappe les comptes en SYSCOHADA avant
    # insertion. Ainsi la table plan_compte ClickHouse reste toujours en
    # référentiel SYSCOHADA, et les lookups d'intitulés depuis le grand livre
    # (déjà mappé) fonctionnent correctement.
    final_data = result['data']
    if plan_source == 'PCG':
        mapped_data = []
        nb_mapped = 0
        nb_unmapped = 0
        for compte, type_c, intitule, nature in final_data:
            m = map_compte(compte)
            mapped_data.append((m['compte_syscohada'], type_c, intitule, nature))
            if m['mapping_status'] == 'unmapped':
                nb_unmapped += 1
            else:
                nb_mapped += 1
        final_data = mapped_data
        print(f"  🔁 Plan_compte mappé PCG→SYSCO: {nb_mapped} mappés, {nb_unmapped} non mappés (conservés)")

    with ClickHouseManager() as ch:
        ch.upsert_dimension(client_id, 'plan_compte', final_data)

    update_etl_status(batch_id, ETLStatus.VALIDATING, 40)

    return {
        **result['stats'],
        'plan_source': plan_source,
    }


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
    """Parse et charge le Plan Tiers (Excel ou .pnc Sage)."""
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')

    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('plan_tiers')
    file_format = data['file_formats'].get('plan_tiers')

    if not file_path:
        print("⚠️ Fichier Plan Tiers non trouvé")
        return

    # Dispatch selon format
    if file_format == 'sage_pnc':
        result = parse_sage_pnc(file_path, client_id)
    else:
        result = parse_plan_tiers(file_path, client_id)

    with ClickHouseManager() as ch:
        ch.upsert_dimension(client_id, 'plan_tiers', result['data'])

    update_etl_status(batch_id, ETLStatus.VALIDATING, 60)

    return result['stats']


def task_process_grand_livre(**context):
    """Parse, enrichit et charge le Grand Livre (Excel ou .pnm Sage).

    Validations bloquantes :
    - Période : transactions hors [periodStart, periodEnd] → fail (RAN exempté)
    - Équilibre : sum(debit) != sum(credit) → fail
    - Cohérence : plan source du grand livre vs plan_compte → fail si divergent

    Toute ValueError métier est capturée pour écrire le message d'erreur
    dans ComptableFile.errorMessage avant le re-raise (visible côté front).
    """
    ti = context['ti']
    data = ti.xcom_pull(task_ids='download_files')

    client_id = data['client_id']
    batch_id = data['batch_id']
    file_path = data['files'].get('grand_livre')
    file_format = data['file_formats'].get('grand_livre')

    try:
        if not file_path:
            raise ValueError("Fichier Grand Livre non trouvé")

        update_etl_status(batch_id, ETLStatus.PROCESSING, 70)

        # Récupérer la période depuis comptable_periods (utilisée par les 2 formats)
        batch_info = get_batch_info(batch_id)
        if not batch_info:
            raise ValueError(
                f"Impossible de récupérer la période du batch {batch_id} "
                f"depuis comptable_periods (requise pour la validation)"
            )
        period_start = batch_info['start_date']
        period_end = batch_info['end_date']

        # Dispatch selon format
        if file_format == 'sage_pnm':
            result = parse_sage_pnm(
                file_path,
                client_id,
                batch_id,
                period_start=period_start,
                period_end=period_end,
            )
        else:
            result = parse_grand_livre(
                file_path,
                client_id,
                batch_id,
                period_start=period_start,
                period_end=period_end,
            )

        # Validation d'équilibre Débit/Crédit (bloquante)
        stats = result['stats']
        total_debit = stats.get('total_debit', 0)
        total_credit = stats.get('total_credit', 0)
        if not stats.get('equilibre', False):
            raise ValueError(
                f"Grand Livre déséquilibré: "
                f"Débit={total_debit:,.2f} ≠ Crédit={total_credit:,.2f} "
                f"(écart={total_debit - total_credit:,.2f})"
            )

        # Validation cohérence inter-fichiers : plan source GL vs plan_compte.
        # Les valeurs 'UNKNOWN' (fichier sans comptes financiers discriminants)
        # ne déclenchent pas de fail.
        comptes_gl = sorted({row[2] for row in result['data']})
        plan_source_gl = detect_plan_source(comptes_gl)
        pc_stats = ti.xcom_pull(task_ids='process_plan_compte') or {}
        plan_source_pc = pc_stats.get('plan_source', 'UNKNOWN')
        print(f"  📋 Plan source — grand_livre: {plan_source_gl} | plan_compte: {plan_source_pc}")

        # Écrire le plan source en base dès qu'il est connu (avant le upsert
        # ClickHouse) : même si l'upsert plante ensuite, le front peut afficher
        # le plan détecté pour aider au debug.
        update_period_plan_source(batch_id, plan_source_gl)

        if plan_source_gl != 'UNKNOWN' and plan_source_pc != 'UNKNOWN':
            if plan_source_gl != plan_source_pc:
                raise ValueError(
                    f"Incohérence de plan comptable détectée: "
                    f"plan_compte = {plan_source_pc}, grand_livre = {plan_source_gl}. "
                    f"Tous les fichiers d'un même batch doivent être dans le même plan."
                )

        with ClickHouseManager() as ch:
            # Enrichir avec rubriques + infos tiers + mapping PCG→SYSCO si applicable.
            # On utilise le plan détecté sur le grand livre lui-même (cohérence déjà
            # vérifiée plus haut avec plan_compte).
            enriched_data = enrich_grand_livre(
                client_id,
                result['data'],
                ch,
                plan_source=plan_source_gl,
            )

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
            'plan_source': plan_source_gl,
            'stats': result['stats']
        }
    except Exception as exc:
        _capture_error(batch_id, exc)
        raise


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
