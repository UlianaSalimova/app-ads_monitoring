import json
from pathlib import Path
from typing import Any

from app.db import get_connection, close_connection


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_users(file_path: Path, cursor) -> None:
    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            obj: dict[str, Any] = json.loads(line)

            user_id = obj.get("id")
            email = obj.get("email")

            if not user_id:
                print("Skip user without id:", obj)
                continue

            user_id = str(user_id)

            cursor.execute(
                """
                INSERT INTO users (id, email)
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE
                SET email = EXCLUDED.email;
                """,
                (user_id, email),
            )


def load_pages(file_path: Path, cursor) -> None:
    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            obj: dict[str, Any] = json.loads(line)

            page_id = obj.get("page_id")

            if not page_id:
                print("Skip page without page_id:", obj)
                continue

            page_id = str(page_id)

            partner_id = obj.get("partner_id")
            partner_login = obj.get("partner_login")
            manager = obj.get("manager")
            segment = obj.get("segment")
            is_easy_monetization = obj.get("is_easy_monetization")

            if not partner_id:
                partner_id = None
            else:
                partner_id = str(partner_id)

            cursor.execute(
                """
                INSERT INTO pages (
                    page_id,
                    partner_id,
                    partner_login,
                    manager,
                    segment,
                    is_easy_monetization
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (page_id) DO UPDATE
                SET
                    partner_id = EXCLUDED.partner_id,
                    partner_login = EXCLUDED.partner_login,
                    manager = EXCLUDED.manager,
                    segment = EXCLUDED.segment,
                    is_easy_monetization = EXCLUDED.is_easy_monetization;
                """,
                (
                    page_id,
                    partner_id,
                    partner_login,
                    manager,
                    segment,
                    is_easy_monetization,
                ),
            )


def load_funnel(file_path: Path, cursor) -> None:
    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            # иногда в начале строки может быть лишний символ
            if line.startswith("t{"):
                line = line[1:]

            try:
                obj: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                print("Skip invalid JSON:", line)
                continue

            page_id = obj.get("page_id")
            app = obj.get("app")
            tac = obj.get("page_tac_last_30_days")

            if not page_id:
                print("Skip funnel row without page_id:", obj)
                continue

            page_id = str(page_id)

            # проверяем что page_id существует в pages
            cursor.execute(
                "SELECT 1 FROM pages WHERE page_id = %s",
                (page_id,)
            )

            if cursor.fetchone() is None:
                print(f"Skip funnel row: page_id {page_id} not found in pages")
                continue

            cursor.execute(
                """
                INSERT INTO v2_pi_funnel_partners (
                    page_id,
                    page_tac_last_30_days,
                    app
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (page_id) DO UPDATE
                SET
                    page_tac_last_30_days = EXCLUDED.page_tac_last_30_days,
                    app = EXCLUDED.app;
                """,
                (page_id, tac, app),
            )


def load_all() -> None:
    conn = None

    try:
        conn = get_connection()

        with conn.cursor() as cursor:
            print("Loading users...")
            load_users(DATA_DIR / "users", cursor)

            print("Loading pages...")
            load_pages(DATA_DIR / "pages", cursor)

            print("Loading funnel data...")
            load_funnel(DATA_DIR / "v2_PI_funnel_partners-2", cursor)

        conn.commit()

        print("All data loaded successfully.")

    except Exception as e:
        if conn:
            conn.rollback()
        print("Error occurred:", e)

    finally:
        close_connection(conn)


if __name__ == "__main__":
    load_all()