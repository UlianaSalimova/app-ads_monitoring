import os
from typing import Iterable, Optional

import psycopg2
from psycopg2.extensions import connection
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

load_dotenv()


def _get_db_url() -> str:
    """Формирует строку подключения из переменных окружения."""
    db_name = os.getenv("DB_NAME", "app_ads_monitoring")
    db_user = os.getenv("DB_USER", "ulboh")
    db_password = os.getenv("DB_PASSWORD", "")
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")

    if db_password:
        return (
            f"postgresql+psycopg2://"
            f"{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        )
    return f"postgresql+psycopg2://{db_user}@{db_host}:{db_port}/{db_name}"


def get_engine() -> Engine:
    """
    Возвращает SQLAlchemy Engine.
    Используется в db_reader.py для pandas.read_sql.
    """
    return create_engine(_get_db_url())


def get_connection() -> connection:
    """
    Возвращает psycopg2-соединение.
    Используется для операций записи (INSERT, UPDATE).
    """
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME", "app_ads_monitoring"),
        user=os.getenv("DB_USER", "ulboh"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


def create_check_run(conn: connection) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO check_runs DEFAULT VALUES
            RETURNING run_id;
            """
        )
        run_id = cursor.fetchone()[0]

    conn.commit()
    return run_id


def finish_check_run(conn: connection, run_id: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE check_runs
            SET finished_at = CURRENT_TIMESTAMP
            WHERE run_id = %s;
            """,
            (run_id,),
        )

    conn.commit()


def save_check_result(conn: connection, run_id: int, result: dict) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO check_results (
                run_id,
                domain,
                ads_status,
                error_details,
                missing_count,
                match_rate,
                checked_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING result_id;
            """,
            (
                run_id,
                result["domain"],
                result["ads_status"],
                result["error_details"],
                result["missing_count"],
                result["match_rate"],
                result["checked_at"],
            ),
        )

        result_id = cursor.fetchone()[0]

        missing_lines: Iterable[str] = result["missing_lines"]
        for missing_line in missing_lines:
            cursor.execute(
                """
                INSERT INTO check_result_missing_lines (
                    result_id,
                    missing_line
                )
                VALUES (%s, %s);
                """,
                (result_id, missing_line),
            )

    conn.commit()
    return result_id


def close_connection(conn: Optional[connection]) -> None:
    if conn is not None:
        conn.close()


def delete_runs(run_ids: list[int]) -> int:
    """
    Удаляет список прогонов и все связанные результаты.
    """
    if not run_ids:
        return 0

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            ids_tuple = tuple(run_ids)

            cursor.execute(
                "DELETE FROM check_results WHERE run_id IN %s",
                (ids_tuple,)
            )

            cursor.execute(
                "DELETE FROM check_runs WHERE run_id IN %s",
                (ids_tuple,)
            )

            deleted_count = cursor.rowcount
        conn.commit()
        return deleted_count
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        close_connection(conn)
