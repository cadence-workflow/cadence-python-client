from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator


def extract(**kwargs):
    data = {"orders": 42, "revenue": 1234.56}
    print(f"Extracted data: {data}")
    return data


def transform(**kwargs):
    data = {"orders": 42, "revenue": 1234.56}
    result = {**data, "avg_order_value": data["revenue"] / data["orders"]}
    print(f"Transformed data: {result}")
    return result


with DAG(
    dag_id="example_python_operators",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    tags=["example"],
) as dag:
    extract_task = PythonOperator(
        task_id="extract",
        python_callable=extract,
    )

    transform_task = PythonOperator(
        task_id="transform",
        python_callable=transform,
    )

    extract_task >> transform_task
