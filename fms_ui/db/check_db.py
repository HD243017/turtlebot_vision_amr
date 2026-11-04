"""DB 접속과 예시 데이터를 확인한다.

    python db/check_db.py

fmsUI/.env 의 FMS_DB_* 설정으로 접속해, 테이블별 건수와 화면에 쓰일 '오늘 요약'을 출력한다.
비밀번호는 출력하지 않는다.
"""
import os
import sys
from pathlib import Path

import pymysql

BASE = Path(__file__).resolve().parent.parent


def load_env(path):
    """KEY=VALUE 형식의 .env 를 읽어 환경변수에 없는 값만 채운다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main():
    load_env(BASE / ".env")
    if not os.environ.get("FMS_DB_PASSWORD"):
        sys.exit("[!] .env 에 FMS_DB_PASSWORD 가 없습니다. .env.example 을 복사해 .env 를 만들어 주세요.")

    conn = pymysql.connect(
        host=os.environ.get("FMS_DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("FMS_DB_PORT", "3306")),
        user=os.environ.get("FMS_DB_USER", "fms_app"),
        password=os.environ["FMS_DB_PASSWORD"],
        database=os.environ.get("FMS_DB_NAME", "fms"),
        charset="utf8mb4",
    )
    with conn, conn.cursor() as cur:
        print(f"[*] 접속 성공: {os.environ.get('FMS_DB_USER', 'fms_app')}@{os.environ.get('FMS_DB_HOST', '127.0.0.1')}/{os.environ.get('FMS_DB_NAME', 'fms')}")
        for table in ["inspection", "delivery", "event"]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                print(f"    {table:<12} {cur.fetchone()[0]:>4}건")
            except pymysql.err.ProgrammingError:
                sys.exit(f"[!] {table} 테이블이 없습니다. root 로 db/schema.sql → db/seed.sql 을 실행하세요.")
        cur.execute("SHOW TABLES LIKE 'inspection_shot'")
        if cur.fetchone():
            print("[!] 1안 테이블(inspection_shot 등)이 남아 있습니다. db/drop_v1.sql → schema.sql → seed.sql 순서로 다시 만드세요.")

        # 화면(store.today_summary)과 같은 기준: 주행으로 이어진 검사(기판별 최종 검사)만
        cur.execute("""
            SELECT COUNT(*), SUM(i.result = 'PASS')
            FROM inspection i JOIN delivery d ON d.inspection_id = i.inspection_id
            WHERE i.inspected_at >= CURDATE()
        """)
        total, ok = cur.fetchone()
        cur.execute("""
            SELECT AVG(total_sec) FROM delivery
            WHERE return_started_at >= CURDATE() AND total_sec IS NOT NULL
        """)
        avg = cur.fetchone()[0]
        rate = round((ok or 0) / total * 100) if total else 0
        sec = int(round(float(avg))) if avg is not None else None   # 화면(store.format_avg)과 같은 반올림
        avg_txt = f"{sec // 60}:{sec % 60:02d}" if sec is not None else "-"
        print(f"[*] 오늘 요약: 검사 {total}건 · PASS {rate}% · 평균 이송 {avg_txt}")

        cur.execute("""
            SELECT i.inspection_id, i.result, i.esp01_status, i.ic_chip_status, i.fnd_status, i.switch_status,
                   i.img_path, d.delivery_id
            FROM inspection i LEFT JOIN delivery d ON d.inspection_id = i.inspection_id
            ORDER BY i.inspection_id DESC LIMIT 6
        """)
        print("[*] 최근 검사 6건 (esp01 / ic_chip / fnd / switch)")
        for iid, result, esp01, ic, fnd, sw, image, did in cur.fetchall():
            job = f"작업 #{did}" if did else "주행 없음"
            print(f"    #{iid:04d} {result:<4} {esp01} / {ic} / {fnd} / {sw}  {image}  {job}")


if __name__ == "__main__":
    main()
