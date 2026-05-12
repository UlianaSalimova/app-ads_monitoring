from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.checker import (
    check_domain,
    STATUS_OK,
    STATUS_ERROR,
    STATUS_NETWORK_ERROR
)
from app.config_loader import load_reference_lines, load_websites
from app.db import (
    get_connection,
    create_check_run,
    save_check_result,
    finish_check_run,
    close_connection,
)

# Количество параллельных потоков для сетевых запросов
MAX_WORKERS = 10


def main() -> None:
    reference_set = load_reference_lines()
    websites = load_websites()

    if not reference_set:
        print("Reference set is empty. Check config/reference.txt")
        return

    if not websites:
        print("Websites list is empty. Check config/websites.txt")
        return

    results = []
    skipped = []
    conn = None

    try:
        conn = get_connection()
        run_id = create_check_run(conn)

        domains = sorted(websites)
        total = len(domains)

        print(f"Loaded {len(reference_set)} reference lines")
        print(f"Loaded {total} websites")
        print(f"Created check run: {run_id}")
        print(f"Workers: {MAX_WORKERS}")
        print("\nStarting parallel checks...\n")

        # ── Параллельный сбор и анализ данных ──
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_domain = {
                executor.submit(check_domain, domain, reference_set): domain
                for domain in domains
            }

            for index, future in enumerate(as_completed(future_to_domain), start=1):
                domain = future_to_domain[future]

                try:
                    result = future.result()
                except Exception as e:
                    print(f"[{index}/{total}] {domain} — exception: {e}")
                    continue

                results.append(result)
                print(
                    f"[{index}/{total}] {domain} — "
                    f"{result['ads_status']} "
                    f"(missing: {result['missing_count']})"
                )

        # ── Последовательная запись в БД ──
        for result in results:
            try:
                save_check_result(conn, run_id, result)
            except Exception as e:
                conn.rollback()
                skipped.append(result["domain"])
                print(f"  SKIPPED: {result['domain']} — ({e})")

        finish_check_run(conn, run_id)

        ok_count = sum(1 for r in results if r["ads_status"] == STATUS_OK)
        error_count = sum(1 for r in results if r["ads_status"] == STATUS_ERROR)
        network_count = sum(1 for r in results if r["ads_status"] == STATUS_NETWORK_ERROR)

        print("\n=== CHECK SUMMARY ===")
        print(f"Run ID: {run_id}")
        print(f"Total domains checked: {len(results)}")
        print(f"Saved to DB: {len(results) - len(skipped)}")
        print(f"Skipped (not in mapping): {len(skipped)}")
        print(f"OK: {ok_count}")
        print(f"ERROR: {error_count}")
        print(f"NETWORK_ERROR: {network_count}")

        if skipped:
            print("\n=== SKIPPED DOMAINS ===")
            for domain in skipped:
                print(f"  {domain}")

        problem_results = [
            r for r in results
            if r["ads_status"] != STATUS_OK
            and r["domain"] not in skipped
        ]

        if problem_results:
            print("\n=== FIRST PROBLEMATIC DOMAINS ===")
            for r in problem_results[:10]:
                print(
                    f'{r["domain"]} | '
                    f'status={r["ads_status"]} | '
                    f'missing_count={r["missing_count"]} | '
                    f'error_details={r["error_details"]}'
                )
        else:
            print("\nAll saved domains passed successfully.")

    finally:
        close_connection(conn)


if __name__ == "__main__":
    main()