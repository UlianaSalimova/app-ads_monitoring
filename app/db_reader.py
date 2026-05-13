import pandas as pd
from sqlalchemy import text

from app.db import get_engine


def get_latest_run_id() -> int | None:
    """Возвращает run_id последнего завершённого прогона."""
    engine = get_engine()

    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT run_id
                FROM check_runs
                WHERE finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1;
            """)
        )
        row = result.fetchone()

    return row[0] if row else None


def get_all_runs(date_filter: str = None) -> pd.DataFrame:
    """
    Возвращает список прогонов.
    date_filter: "YYYY-MM-DD" или "YYYY-MM-DD — YYYY-MM-DD"
    """
    engine = get_engine()

    sql = """
        SELECT
            run_id,
            started_at,
            finished_at,
            EXTRACT(EPOCH FROM (finished_at - started_at))::int AS duration_seconds
        FROM check_runs
    """

    params = {}

    if date_filter:

        separator = " — "

        if separator in date_filter:
            start_date, end_date = date_filter.split(separator)
            sql += " WHERE DATE(started_at) BETWEEN %(start)s AND %(end)s"
            params["start"] = start_date
            params["end"] = end_date
        else:
            sql += " WHERE DATE(started_at) = %(date)s"
            params["date"] = date_filter

    sql += " ORDER BY started_at DESC;"

    df = pd.read_sql(sql, engine, params=params)

    df["started_at"] = pd.to_datetime(df["started_at"])
    df["finished_at"] = pd.to_datetime(df["finished_at"])
    df["duration_seconds"] = df["duration_seconds"].fillna(0).astype(int)

    return df


def get_run_summary(run_id: int) -> dict:
    """Возвращает агрегированную статистику по прогону."""
    engine = get_engine()

    query = """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE ads_status = 'OK') AS ok_count,
            COUNT(*) FILTER (WHERE ads_status = 'ERROR') AS error_count,
            COUNT(*) FILTER (WHERE ads_status = 'NETWORK_ERROR') AS network_error_count,
            ROUND(AVG(match_rate), 2) AS avg_match_rate
        FROM check_results
        WHERE run_id = %(run_id)s;
    """

    df = pd.read_sql(query, engine, params={"run_id": run_id})
    row = df.iloc[0]

    return {
        "total": int(row["total"]),
        "ok_count": int(row["ok_count"]),
        "error_count": int(row["error_count"]),
        "network_error_count": int(row["network_error_count"]),
        "avg_match_rate": float(row["avg_match_rate"] or 0.0),
    }


def get_run_results(run_id: int) -> pd.DataFrame:
    """
    Возвращает результаты прогона, обогащённые данными
    из вспомогательных таблиц через app_domain_mapping.
    """
    engine = get_engine()

    query = """
        SELECT
            cr.result_id,
            cr.domain,
            cr.ads_status,
            cr.error_details,
            cr.missing_count,
            cr.match_rate,
            cr.checked_at,
            m.app,
            p.partner_id,
            p.partner_login,
            p.manager,
            p.segment,
            COALESCE(p.is_easy_monetization, FALSE) AS is_easy_monetization,
            COALESCE(f.page_tac_last_30_days, 0.0) AS page_tac_last_30_days,
            COALESCE(u.email, '') AS partner_email,
            CASE
                WHEN COALESCE(f.page_tac_last_30_days, 0) > 0 THEN TRUE
                ELSE FALSE
            END AS is_active
        FROM check_results cr
        LEFT JOIN app_domain_mapping m ON cr.domain = m.domain
        LEFT JOIN pages p ON m.page_id = p.page_id
        LEFT JOIN v2_pi_funnel_partners f ON p.page_id = f.page_id
        LEFT JOIN users u ON p.partner_id = u.id
        WHERE cr.run_id = %(run_id)s
        ORDER BY cr.ads_status ASC, cr.missing_count DESC;
    """

    df = pd.read_sql(query, engine, params={"run_id": run_id})

    # обработка NULL-значений
    df["partner_id"] = df["partner_id"].fillna("")
    df["partner_login"] = df["partner_login"].fillna("")
    df["manager"] = df["manager"].fillna("")
    df["segment"] = df["segment"].fillna("")
    df["partner_email"] = df["partner_email"].fillna("")
    df["app"] = df["app"].fillna("")
    df["page_tac_last_30_days"] = pd.to_numeric(
        df["page_tac_last_30_days"], errors="coerce"
    ).fillna(0.0)
    df["is_active"] = df["is_active"].fillna(False)

    return df


def get_missing_lines(result_id: int) -> list[str]:
    """Возвращает список отсутствующих строк для конкретного результата."""
    engine = get_engine()

    query = """
        SELECT missing_line
        FROM check_result_missing_lines
        WHERE result_id = %(result_id)s
        ORDER BY missing_line;
    """

    df = pd.read_sql(query, engine, params={"result_id": result_id})
    return df["missing_line"].tolist()


def get_domain_history(domain: str) -> list[dict]:
    """Возвращает историю проверок по конкретному домену."""
    engine = get_engine()

    query = """
        SELECT 
            checked_at, 
            match_rate,
            ads_status
        FROM check_results
        WHERE domain = %(domain)s
        ORDER BY checked_at ASC
    """

    df = pd.read_sql(query, engine, params={"domain": domain})

    history = []
    for _, row in df.iterrows():
        history.append({
            "date": row["checked_at"].strftime("%d.%m %H:%M"),
            "rate": float(row["match_rate"]),
            "status": row["ads_status"]
        })

    return history


def get_monitoring_alerts() -> list[dict]:
    """
    Возвращает сводку по всем доменам:
    - Текущий статус
    - Сколько прогонов подряд этот статус держится (Downtime duration)
    - Финансовые показатели
    """
    engine = get_engine()

    query = """
        SELECT 
            cr.domain, 
            cr.ads_status, 
            cr.match_rate,
            cr.return_id, -- нужно для сортировки, поле run_id
            cr.checked_at,
            COALESCE(f.page_tac_last_30_days, 0.0) as revenue,
            p.manager,
            p.partner_login
        FROM check_results cr
        LEFT JOIN app_domain_mapping m ON cr.domain = m.domain
        LEFT JOIN pages p ON m.page_id = p.page_id
        LEFT JOIN v2_pi_funnel_partners f ON p.page_id = f.page_id
        ORDER BY cr.domain, cr.checked_at DESC
    """

    query = """
        SELECT 
            cr.domain, 
            cr.ads_status, 
            cr.match_rate,
            cr.checked_at,
            COALESCE(f.page_tac_last_30_days, 0.0) as revenue,
            p.manager,
            p.partner_login
        FROM check_results cr
        LEFT JOIN app_domain_mapping m ON cr.domain = m.domain
        LEFT JOIN pages p ON m.page_id = p.page_id
        LEFT JOIN v2_pi_funnel_partners f ON p.page_id = f.page_id
        ORDER BY cr.domain, cr.checked_at DESC
    """

    df = pd.read_sql(query, engine)

    alerts = []

    for domain, group in df.groupby("domain"):
        latest = group.iloc[0]

        if latest["ads_status"] != "OK":

            streak = 0
            start_date = latest["checked_at"]

            for _, row in group.iterrows():
                if row["ads_status"] == latest["ads_status"]:
                    streak += 1
                    start_date = row["checked_at"] 
                else:
                    break

            alerts.append({
                "domain": domain,
                "status": latest["ads_status"],
                "manager": latest["manager"],
                "partner": latest["partner_login"],
                "revenue": float(latest["revenue"]),
                "last_match_rate": float(latest["match_rate"]),
                "streak_count": streak,
                "problem_since": start_date
            })

    alerts.sort(key=lambda x: (x["revenue"], x["streak_count"]), reverse=True)

    return alerts
