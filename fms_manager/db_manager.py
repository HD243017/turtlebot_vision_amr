"""DB매니저: main.py 가 검사 · 이송 · 이벤트를 DB 에 저장할 때 부르는 함수 모음 (테이블은 db/schema.sql).
접속 정보는 이 파일 옆 .env 의 FMS_DB_* 를 읽는다. DB 가 다른 PC 면 .env 의 FMS_DB_HOST 만 바꾸면 된다.
잘못된 값이면 ValueError 를 던진다 (main.py 에서 잡아 로그만 남기고 계속 돌 것)."""
import os
from datetime import datetime, timedelta
from pathlib import Path

import pymysql

PARTS = ["esp01", "ic_chip", "fnd", "switch"]          # inspection 의 {part}_status 컬럼 순서
DEST_MARKERS = (2, 3)                                   # 2 = 양품, 3 = 불량
DELIVERY_STEPS = {                                      # mark_delivery 단계 이름 → delivery 컬럼
    "station_arrived": "station_arrived_at",
    "departed": "departed_at",
    "return_started": "return_started_at",
}
EVENT_TYPES = ("OBSTACLE_STOP", "REROUTE", "COMM_LOST", "ESTOP")
TIME_FMT = "%Y-%m-%d %H:%M:%S"


def _load_env(path):
    """KEY=VALUE 형식의 .env 를 읽어, 이미 설정된 환경변수는 건드리지 않고 나머지만 채운다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _when(value):
    """None → 지금 시각, datetime 또는 'YYYY-MM-DD HH:MM:SS' 문자열 → datetime (DB 가 초 단위라 초까지만)."""
    if value is None:
        return datetime.now().replace(microsecond=0)
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    try:
        return datetime.strptime(value, TIME_FMT)
    except (TypeError, ValueError):
        raise ValueError(f"시각 형식은 YYYY-MM-DD HH:MM:SS 입니다: {value!r}") from None


class DbManager:
    def __init__(self, env_path=None):
        _load_env(Path(env_path) if env_path else Path(__file__).with_name(".env"))
        self._cfg = {
            "host": os.environ.get("FMS_DB_HOST", "127.0.0.1"),
            "port": int(os.environ.get("FMS_DB_PORT", "3306")),
            "user": os.environ.get("FMS_DB_USER", "fms_app"),
            "password": os.environ.get("FMS_DB_PASSWORD", ""),
            "database": os.environ.get("FMS_DB_NAME", "fms"),
            "charset": "utf8mb4",
            "connect_timeout": 3,
            # UPDATE 결과 줄 수를 '바뀐 줄'이 아니라 '찾은 줄'로 센다 (같은 값을 다시 넣어도 0 이 안 되게)
            "client_flag": pymysql.constants.CLIENT.FOUND_ROWS,
        }
        with self._conn():          # 켤 때 한 번 접속해 보고, 안 되면 여기서 바로 오류
            pass

    def _conn(self):
        return pymysql.connect(**self._cfg)

    # ---- 검사 ----
    def add_inspection(self, result, esp01="PASS", ic_chip="PASS", fnd="PASS", switch="PASS",
                       img_path=None, inspected_at=None):
        """검사 1회를 저장하고 새 검사 번호(inspection_id)를 돌려준다. 재촬영도 이 함수로 새 줄을 만든다.
        부품 상태는 검사 프로그램 결과 코드 그대로: 'PASS', 'MISSING', 'OFFSET(14.2px)' ..."""
        if result not in ("PASS", "FAIL"):
            raise ValueError(f"result 는 PASS 또는 FAIL 입니다: {result!r}")
        statuses = [str(s or "PASS")[:40] for s in (esp01, ic_chip, fnd, switch)]   # 컬럼 길이 40
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO inspection (result, inspected_at, esp01_status, ic_chip_status, "
                        "fnd_status, switch_status, img_path) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (result, _when(inspected_at), *statuses, img_path))
            conn.commit()
            return cur.lastrowid

    # ---- 이송 ----
    def start_delivery(self, inspection_id, dest_marker, called_at=None):
        """터틀봇 호출 = 이송 1건 시작. 새 이송 번호(delivery_id)를 돌려준다."""
        if dest_marker not in DEST_MARKERS:
            raise ValueError(f"dest_marker 는 2(양품) 또는 3(불량) 입니다: {dest_marker!r}")
        try:
            with self._conn() as conn, conn.cursor() as cur:
                cur.execute("INSERT INTO delivery (inspection_id, dest_marker, called_at) VALUES (%s, %s, %s)",
                            (inspection_id, dest_marker, _when(called_at)))
                conn.commit()
                return cur.lastrowid
        except pymysql.err.IntegrityError:
            raise ValueError(f"없는 검사 번호이거나 이미 이송이 잡힌 검사입니다: {inspection_id}") from None

    def mark_delivery(self, delivery_id, step, at=None):
        """이송 단계 시각 기록. step: 'station_arrived' / 'departed' / 'return_started'.
        복귀 시작 때 total_sec(= 복귀 시작 - 호출, 초)도 같이 계산한다."""
        col = DELIVERY_STEPS.get(step)
        if col is None:
            raise ValueError(f"step 은 {', '.join(DELIVERY_STEPS)} 중 하나입니다: {step!r}")
        when = _when(at)
        with self._conn() as conn, conn.cursor() as cur:
            if step == "return_started":
                cur.execute("UPDATE delivery SET return_started_at = %s, "
                            "total_sec = GREATEST(0, TIMESTAMPDIFF(SECOND, called_at, %s)) WHERE delivery_id = %s",
                            (when, when, delivery_id))
            else:
                cur.execute(f"UPDATE delivery SET {col} = %s WHERE delivery_id = %s", (when, delivery_id))
            if cur.rowcount == 0:
                raise ValueError(f"없는 이송 번호입니다: {delivery_id}")
            conn.commit()

    def relink_delivery(self, delivery_id, inspection_id, dest_marker):
        """재촬영으로 검사 번호가 바뀌면 아직 출발 전인 이송을 새 검사로 옮기고 목적지도 바꾼다."""
        if dest_marker not in DEST_MARKERS:
            raise ValueError(f"dest_marker 는 2(양품) 또는 3(불량) 입니다: {dest_marker!r}")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE delivery SET inspection_id = %s, dest_marker = %s "
                        "WHERE delivery_id = %s AND departed_at IS NULL",
                        (inspection_id, dest_marker, delivery_id))
            if cur.rowcount == 0:
                raise ValueError(f"없는 이송 번호이거나 이미 출발한 이송입니다: {delivery_id}")
            conn.commit()

    # ---- 이벤트 ----
    def open_event(self, event_type, delivery_id=None, x=None, y=None, at=None):
        """안전 정지 · 재탐색 · 통신 끊김 · 비상 정지 시작. 새 event_id 를 돌려준다.
        delivery_id 가 DB에 없는 번호면 비워서 넣는다 (외래 키 오류로 기록이 빠지지 않게)."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"event_type 은 {', '.join(EVENT_TYPES)} 중 하나입니다: {event_type!r}")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO event (delivery_id, event_type, occurred_at, x, y) VALUES ("
                        "(SELECT delivery_id FROM delivery WHERE delivery_id = %s), %s, %s, %s, %s)",
                        (delivery_id, event_type, _when(at), x, y))
            conn.commit()
            return cur.lastrowid

    def close_event(self, event_type, at=None):
        """같은 종류의 아직 안 끝난 이벤트 중 가장 최근 것에 재출발 · 복구 · 해제 시각을 넣는다.
        닫은 게 있으면 True."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"event_type 은 {', '.join(EVENT_TYPES)} 중 하나입니다: {event_type!r}")
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("UPDATE event SET resumed_at = %s WHERE event_type = %s AND resumed_at IS NULL "
                        "ORDER BY event_id DESC LIMIT 1", (_when(at), event_type))
            conn.commit()
            return cur.rowcount > 0

    # ---- main.py 연결용 (팀원 main.py · 검사 프로그램이 부르는 이름) ----
    def insert_inspection_result(self, db_record):
        """검사 프로그램의 db_record 를 그대로 받아 저장하고 새 검사 번호를 돌려준다.
        번호를 db_record["job_id"] 에도 넣어 둔다 (같은 dict 가 main.py 작업 대기열로 넘어가서,
        main.py 가 update_delivery_complete(job_id, ...) 를 부를 때 이 번호를 쓴다)."""
        iid = self.add_inspection(
            db_record.get("final_decision") or db_record.get("result"),
            esp01=db_record.get("esp01_status"),
            ic_chip=db_record.get("ic_chip_status"),
            fnd=db_record.get("fnd_status"),
            switch=db_record.get("switch_status"),
            img_path=db_record.get("img_path"),
            inspected_at=db_record.get("inspected_at"),
        )
        db_record["job_id"] = iid
        return iid

    def update_delivery_complete(self, job_id, elapsed_sec):
        """하역 후 대기소 복귀를 시작할 때 main.py 가 부른다. job_id = 검사 번호 (insert_inspection_result 가 넣어 둔 값).
        그 검사의 이송 줄이 아직 없으면 '지금 - elapsed_sec' 를 호출 시각으로 해서 만든다
        (지금 main.py 는 호출할 때 DB 에 기록하지 않으므로). 이송 번호를 돌려준다."""
        now = datetime.now().replace(microsecond=0)
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT d.delivery_id, i.result FROM inspection i "
                        "LEFT JOIN delivery d ON d.inspection_id = i.inspection_id "
                        "WHERE i.inspection_id = %s", (job_id,))
            row = cur.fetchone()
        if row is None:
            raise ValueError(f"없는 검사 번호입니다: {job_id}")
        delivery_id, result = row
        if delivery_id is None:
            called_at = now - timedelta(seconds=max(0, float(elapsed_sec)))
            delivery_id = self.start_delivery(job_id, 2 if result == "PASS" else 3, called_at=called_at)
        self.mark_delivery(delivery_id, "return_started", at=now)
        return delivery_id


DBManager = DbManager   # 팀원 main.py가 쓰는 이름 (from db_manager import DBManager)