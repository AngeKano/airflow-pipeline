FROM apache/airflow:2.7.1-python3.11

# Copier et installer les dépendances Python
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# L'image est prête avec toutes les dépendances