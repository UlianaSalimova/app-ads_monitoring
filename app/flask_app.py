import os
from functools import wraps

from flask import Flask, render_template, redirect, url_for, request, session, send_file, flash
from dotenv import load_dotenv
import pandas as pd
import io
from app.db import get_engine

from app.db_reader import (
    get_all_runs,
    get_latest_run_id,
    get_run_summary,
    get_run_results,
    get_missing_lines,
    get_domain_history,
    get_monitoring_alerts
)
from app.main import main as run_check
from apscheduler.schedulers.background import BackgroundScheduler
from app.db import get_engine, delete_runs


load_dotenv()

app = Flask(
    __name__,
    template_folder="../templates",
    static_folder="../static",
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

USERS = {
    "analyst": {
        "password": os.getenv("ANALYST_PASSWORD"),
        "role": "analyst",
    },
    "manager": {
        "password": os.getenv("MANAGER_PASSWORD"),
        "role": "manager",
    },
}


# Декораторы доступа
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def analyst_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        print("=== analyst_required ===")  # добавь эту строку
        print(f"username: {session.get('username')}")  # и эту
        print(f"role: {session.get('role')}")  # и эту
        if "username" not in session:
            print("-> redirect to login")  # и эту
            return redirect(url_for("login"))
        if session.get("role") != "analyst":
            print("-> redirect to runs (недостаточно прав)")  # и эту
            flash("Недостаточно прав. Только аналитик может выполнять это действие.")
            return redirect(url_for("runs"))
        print("-> OK, доступ разрешён")  # и эту
        return f(*args, **kwargs)
    return decorated

# Авторизация
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        user = USERS.get(username)

        if user and user["password"] == password:
            session["username"] = username
            session["role"] = user["role"]
            return redirect(url_for("runs"))

        error = "Неверный логин или пароль"

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# Главная — список прогонов
@app.route("/")
@login_required
def runs():
    date_filter = request.args.get("date")

    df = get_all_runs(date_filter)
    runs_list = df.to_dict(orient="records")

    for run in runs_list:
        try:
            run["summary"] = get_run_summary(run["run_id"])
        except Exception:
            run["summary"] = None

    next_run = None
    job = scheduler.get_job("daily_check")
    if job and job.next_run_time:
        next_run = job.next_run_time

    return render_template(
        "runs.html",
        runs=runs_list,
        date_filter=date_filter,
        next_run=next_run,
        username=session.get("username"),
        role=session.get("role"),
    )


# Детализация прогона
@app.route("/run/<int:run_id>")
@login_required
def run_detail(run_id: int):
    summary = get_run_summary(run_id)
    df = get_run_results(run_id)

    managers = sorted(df["manager"].dropna().unique().tolist())
    segments = sorted(df["segment"].dropna().unique().tolist())

    # фильтрация по статусу
    status_filter = request.args.get("status", "ALL")
    if status_filter != "ALL":
        df = df[df["ads_status"] == status_filter]

    # фильтрация по активности
    active_filter = request.args.get("active", "ALL")
    if active_filter == "YES":
        df = df[df["is_active"] == True]
    elif active_filter == "NO":
        df = df[df["is_active"] == False]

    # фильтрация по менеджеру
    manager_filter = request.args.get("manager", "ALL")
    if manager_filter != "ALL":
        df = df[df["manager"] == manager_filter]

    # фильтрация по сегменту
    segment_filter = request.args.get("segment", "ALL")
    if segment_filter != "ALL":
        df = df[df["segment"] == segment_filter]

    # фильтрация по лёгкой монетизации
    easy_mon_filter = request.args.get("easy_mon", "ALL")
    if easy_mon_filter == "YES":
        df = df[df["is_easy_monetization"] == True]
    elif easy_mon_filter == "NO":
        df = df[df["is_easy_monetization"] == False]

    # расчёт приоритета
    def get_priority(row):
        if row["ads_status"] == "ERROR" and row["is_active"]:
            return 1  # высокий
        elif row["ads_status"] == "ERROR" and not row["is_active"]:
            return 2  # средний
        else:
            return 3  # низкий

    df["priority"] = df.apply(get_priority, axis=1)
    df = df.sort_values("priority")

    results = df.to_dict(orient="records")

    return render_template(
        "run.html",
        run_id=run_id,
        summary=summary,
        results=results,
        managers=managers,
        segments=segments,
        status_filter=status_filter,
        active_filter=active_filter,
        manager_filter=manager_filter,
        segment_filter=segment_filter,
        easy_mon_filter=easy_mon_filter,
        username=session.get("username"),
        role=session.get("role"),
    )


# Детализация домена — missing lines
@app.route("/result/<int:result_id>")
@login_required
def domain_detail(result_id: int):
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
            cr.run_id,
            m.app,
            p.partner_login,
            p.manager,
            p.segment,
            COALESCE(p.is_easy_monetization, FALSE) AS is_easy_monetization,
            COALESCE(f.page_tac_last_30_days, 0.0) AS page_tac_last_30_days,
            COALESCE(u.email, '') AS partner_email
        FROM check_results cr
        LEFT JOIN app_domain_mapping m ON cr.domain = m.domain
        LEFT JOIN pages p ON m.page_id = p.page_id
        LEFT JOIN v2_pi_funnel_partners f ON p.page_id = f.page_id
        LEFT JOIN users u ON p.partner_id = u.id
        WHERE cr.result_id = %(result_id)s;
    """

    df = pd.read_sql(query, engine, params={"result_id": result_id})

    if df.empty:
        return render_template("404.html"), 404

    result = df.iloc[0].to_dict()
    result["result_id"] = result_id

    result["match_rate"] = float(result.get("match_rate", 0))
    result["missing_count"] = int(result.get("missing_count", 0))
    result["page_tac_last_30_days"] = float(
        result.get("page_tac_last_30_days", 0)
    )
    result["is_easy_monetization"] = bool(
        result.get("is_easy_monetization", False)
    )
    domain_name = result["domain"]

    history = get_domain_history(domain_name)

    chart_labels = [h["date"] for h in history]
    chart_data = [h["rate"] for h in history]

    missing_lines = get_missing_lines(result_id)

    return render_template(
        "domain.html",
        result=result,
        missing_lines=missing_lines,
        # Передаем данные для графика
        chart_labels=chart_labels,
        chart_data=chart_data,
        username=session.get("username"),
        role=session.get("role"),
    )

# Экспорт CSV / XLSX
@app.route("/run/<int:run_id>/export")
@login_required
def export(run_id: int):
    fmt = request.args.get("format", "csv")
    df = get_run_results(run_id)

    if fmt == "xlsx":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Results")
        output.seek(0)
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"run_{run_id}_results.xlsx",
        )

    output = io.StringIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"run_{run_id}_results.csv",
    )


# Запуск проверки вручную (только аналитик)
@app.route("/run/start", methods=["POST"])
@analyst_required
def start_run():
    try:
        run_check()
        flash("Проверка успешно запущена и завершена.")
    except Exception as e:
        flash(f"Ошибка при запуске проверки: {e}")
    return redirect(url_for("runs"))

@app.route("/result/<int:result_id>/export")
@login_required
def export_missing_lines(result_id: int):
    fmt = request.args.get("format", "txt")
    lines = get_missing_lines(result_id)

    if fmt == "csv":
        output = io.StringIO()
        output.write("ad_system_domain,publisher_id,relationship,certification_id\n")

        for line in lines:
            parts = [p.strip() for p in line.split(",")]

            while len(parts) < 4:
                parts.append("")

            escaped = [f'"{p}"' for p in parts[:4]]
            output.write(",".join(escaped) + "\n")

        output.seek(0)
        return send_file(
            io.BytesIO(output.getvalue().encode("utf-8")),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"missing_lines_{result_id}.csv",
        )

    output = io.StringIO()
    for line in lines:
        output.write(line + "\n")
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"missing_lines_{result_id}.txt",
    )


@app.route("/runs/delete", methods=["POST"])
@analyst_required
def delete_runs_route():
    # Получаем список ID из чекбоксов
    run_ids = request.form.getlist("run_ids")

    if not run_ids:
        flash("Не выбрано ни одного прогона для удаления.")
        return redirect(url_for("runs"))

    try:
        ids_to_delete = [int(x) for x in run_ids]
        count = delete_runs(ids_to_delete)
        flash(f"Успешно удалено прогонов: {count}")
    except Exception as e:
        flash(f"Ошибка при удалении: {e}")

    return redirect(url_for("runs"))


# Управление эталоном (Только аналитик)
@app.route("/config/reference", methods=["GET", "POST"])
@analyst_required
def reference_config():
    from app.config_loader import CONFIG_DIR, load_reference_lines

    ref_path = CONFIG_DIR / "reference.txt"

    if request.method == "POST":
        if "file" not in request.files:
            flash("Нет файла в запросе")
            return redirect(request.url)

        file = request.files["file"]

        if file.filename == "":
            flash("Файл не выбран")
            return redirect(request.url)

        if file:
            try:
                content = file.read().decode("utf-8")
                lines = [l for l in content.splitlines() if l.strip()]

                if not lines:
                    flash("Ошибка: Файл пустой!")
                    return redirect(request.url)

                if "," not in lines[0]:
                    flash("Ошибка формата: строки должны содержать запятые (domain, id, type)")
                    return redirect(request.url)

                with open(ref_path, "w", encoding="utf-8") as f:
                    f.write(content)

                flash(f"Эталон успешно обновлен. Загружено строк: {len(lines)}")

            except Exception as e:
                flash(f"Ошибка при обработке файла: {e}")

            return redirect(request.url)

    current_lines = []
    try:
        if ref_path.exists():
            with open(ref_path, "r", encoding="utf-8") as f:
                current_lines = f.readlines()
    except Exception:
        pass

    return render_template(
        "reference.html",
        line_count=len(current_lines),
        preview_lines="".join(current_lines[:5]),
        username=session.get("username"),
        role=session.get("role"),
    )


@app.route("/config/reference/download")
@analyst_required
def download_reference():
    """Скачать текущий эталон"""
    from app.config_loader import CONFIG_DIR
    return send_file(
        CONFIG_DIR / "reference.txt",
        as_attachment=True,
        download_name="reference.txt",
        mimetype="text/plain"
    )


@app.route("/monitoring")
@login_required
def monitoring():
    alerts = get_monitoring_alerts()

    return render_template(
        "monitoring.html",
        alerts=alerts,
        username=session.get("username"),
        role=session.get("role"),
    )


@app.route("/result/<int:result_id>/mailto")
@login_required
def mailto_manager(result_id: int):
    """Формирует mailto-ссылку для уведомления партнёра."""
    import urllib.parse

    engine = get_engine()
    query = """
        SELECT
            cr.domain,
            cr.missing_count,
            cr.match_rate,
            cr.run_id,
            p.manager,
            p.partner_login,
            COALESCE(u.email, '') AS partner_email
        FROM check_results cr
        LEFT JOIN app_domain_mapping m ON cr.domain = m.domain
        LEFT JOIN pages p ON m.page_id = p.page_id
        LEFT JOIN users u ON p.partner_id = u.id
        WHERE cr.result_id = %(result_id)s;
    """

    df = pd.read_sql(query, engine, params={"result_id": result_id})

    if df.empty:
        flash("Результат не найден.")
        return redirect(url_for("runs"))

    row = df.iloc[0]
    partner_email = row["partner_email"]
    domain = row["domain"]
    missing_count = int(row["missing_count"])
    match_rate = float(row["match_rate"])
    manager = row["manager"] or ""
    partner_login = row["partner_login"] or ""

    if not partner_email:
        flash("Email партнёра не найден.")
        return redirect(url_for("domain_detail", result_id=result_id))

    missing_lines = get_missing_lines(result_id)

    lines_text = "\n".join(missing_lines[:50])
    if len(missing_lines) > 50:
        lines_text += (
            f"\n\n... и ещё {len(missing_lines) - 50} строк. "
            f"Полный список доступен в системе мониторинга."
        )

    subject = f"Требуется обновление файла app-ads.txt — {domain}"

    body = f"""Здравствуйте{', ' + partner_login if partner_login else ''},

в ходе автоматической проверки файла app-ads.txt для домена {domain} \
выявлены несоответствия требованиям рекламной платформы.

Текущий статус: ERROR
Match rate: {match_rate}%
Отсутствует строк: {missing_count}

Пожалуйста, добавьте следующие строки в файл app-ads.txt:

{lines_text}

Файл должен быть размещён по адресу:
https://{domain}/app-ads.txt

После обновления файла статус будет автоматически пересчитан \
при следующей проверке системы.

По вопросам обращайтесь к вашему менеджеру: {manager}

---
Сообщение сформировано автоматически системой мониторинга app-ads.txt Monitor.
Прогон #{row['run_id']}"""

    mailto = (
        f"mailto:{urllib.parse.quote(partner_email)}"
        f"?subject={urllib.parse.quote(subject)}"
        f"&body={urllib.parse.quote(body)}"
    )

    return redirect(mailto)



# Планировщик суточного запуска
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=run_check,
    trigger="cron",
    hour=6,
    minute=0,
    id="daily_check",
    name="Суточная проверка app-ads.txt",
    replace_existing=True,
)
scheduler.start()


# Запуск приложения
if __name__ == "__main__":
    app.run(debug=False, port=5000)

