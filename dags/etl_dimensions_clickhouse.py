"""
DAG de mise à jour UNITAIRE d'une table de dimension REPFI.

Un run = un seul fichier = une seule dimension (Plan Comptable, Codes Journaux
ou Plan Tiers). Le fichier est fusionné dans la table ClickHouse correspondante :
    - nouvelles lignes  → ajoutées
    - lignes modifiées  → mises à jour
    - lignes absentes du fichier → conservées (aucune suppression, jamais)
Les intitulés/types modifiés sont aussi répercutés sur les écritures déjà
chargées dans grand_livre. Aucun grand livre n'est requis ni traité.

Déclenchement (API Airflow) : POST /api/v1/dags/etl_dimensions_clickhouse/dagRuns
    {"conf": {
        "client_id": "<id client>",                       # obligatoire
        "dimension": "plan_comptes" | "code_journal" | "plan_tiers",  # obligatoire
        "s3_key":    "<clé S3 complète du fichier>",       # obligatoire
        "batch_id":  "<id de suivi>",                      # optionnel
        "update_id": "<id dimension_updates>"              # optionnel (front)
    }}

Si batch_id est fourni, le statut (comptable_files.processingStatus) et le
message d'erreur (comptable_files.errorMessage) des fichiers de ce batch sont
mis à jour, comme pour le DAG complet. Le résultat (lignes ajoutées /
modifiées / inchangées) est renvoyé en XCom (return_value de update_dimension).

Si update_id est fourni (dépôt depuis l'onglet Import du front), la ligne
dimension_updates correspondante reçoit statut, progression, compteurs et
message d'erreur : le front ne fait que la lire.
"""
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from etl.config import DEFAULT_ARGS, ETLStatus
from etl.postgres import (
    update_etl_status,
    update_files_error_message,
    update_dimension_update,
)
from etl.s3 import download_s3_object, cleanup_local_files
from etl.format_detect import detect_format, validate_format
from etl.processors import load_dimension, normalize_dimension
from clickhouse.manager import ClickHouseManager


def _get_conf(context) -> dict:
    """conf du run (prioritaire) complétée par les params du DAG."""
    conf = dict(context.get('params') or {})
    dag_run = context.get('dag_run')
    if dag_run and dag_run.conf:
        conf.update(dag_run.conf)
    return conf


def task_update_dimension(**context):
    conf = _get_conf(context)
    client_id = conf.get('client_id')
    s3_key = conf.get('s3_key')
    batch_id = conf.get('batch_id')
    update_id = conf.get('update_id')
    run_id = context['run_id'].replace(':', '_').replace('+', '_')
    local_dir = f"/tmp/etl_dim_{client_id}_{run_id}"

    try:
        if not client_id or not s3_key or not conf.get('dimension'):
            raise ValueError(
                "Paramètres manquants : client_id, dimension et s3_key sont obligatoires"
            )
        dimension = normalize_dimension(conf['dimension'])
        print(f"🚀 Mise à jour dimension '{dimension}' pour client {client_id}")

        if batch_id:
            update_etl_status(batch_id, ETLStatus.VALIDATING, 10)
        if update_id:
            update_dimension_update(update_id, ETLStatus.VALIDATING, 10)

        file_path = download_s3_object(s3_key, local_dir)
        file_format = detect_format(file_path)
        validate_format(dimension, file_format)  # ex: refuse un .pnm pour plan_comptes
        print(f"  ✓ Format '{file_format}' OK")

        if batch_id:
            update_etl_status(batch_id, ETLStatus.PROCESSING, 40)
        if update_id:
            update_dimension_update(update_id, ETLStatus.PROCESSING, 40)

        with ClickHouseManager() as ch:
            # Base + tables de dimension uniquement (ple / grand_livre non touchés)
            ch.ensure_dimension_tables(client_id)
            result = load_dimension(client_id, dimension, file_path, file_format, ch)

        if batch_id:
            update_etl_status(batch_id, ETLStatus.COMPLETED, 100)
        if update_id:
            update_dimension_update(
                update_id,
                ETLStatus.COMPLETED,
                100,
                rows_inserted=result.get('ajoutees', 0),
                rows_updated=result.get('modifiees', 0),
            )

        print("=" * 60)
        print(f"🎉 Dimension '{dimension}' mise à jour : "
              f"{result['ajoutees']} ajoutées, {result['modifiees']} modifiées, "
              f"{result['inchangees']} inchangées, aucune supprimée")
        print("=" * 60)
        return {**result, 's3_key': s3_key}

    except Exception as exc:
        if batch_id:
            try:
                update_files_error_message(batch_id, f"{type(exc).__name__}: {exc}")
            except Exception as e:
                print(f"  ⚠️ Impossible d'écrire errorMessage: {e}")
            update_etl_status(batch_id, ETLStatus.FAILED, 100)
        if update_id:
            update_dimension_update(
                update_id,
                ETLStatus.FAILED,
                100,
                error_message=f"{type(exc).__name__}: {exc}",
            )
        raise
    finally:
        cleanup_local_files(local_dir)


with DAG(
    dag_id='etl_dimensions_clickhouse',
    default_args=DEFAULT_ARGS,
    description='REPFI - Mise à jour unitaire d\'une table de dimension (fusion sans suppression)',
    schedule_interval=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=['repfi', 'etl', 'dimensions', 'clickhouse'],
) as dag:

    PythonOperator(
        task_id='update_dimension',
        python_callable=task_update_dimension,
    )
