"""검사 · 주행 · 이벤트 기록 저장소 (DB 설계 2안: inspection / delivery / event).

두 가지가 있고, app.py 는 open_store() 가 고른 하나만 쓴다. 메서드 이름과 돌려주는 모양이 같다.
  MemoryStore : 서버 메모리의 가짜 데이터 (db/seed.sql 과 같은 내용). DB 없이 화면 개발할 때.
  MySQLStore  : MySQL 의 fms DB (db/schema.sql). .env 에 FMS_DB_PASSWORD 가 있으면 이쪽.
고르는 규칙: 환경변수 FMS_STORE=memory|mysql 이 있으면 그대로, 없으면 FMS_DB_PASSWORD 유무로.

두 저장소 모두 DB 줄과 같은 키 이름의 dict 를 다루고, 화면용 모양 · 한글 문구는
아래 공용 함수(format_inspection, timeline 등)가 만든다. DB에는 문구를 저장하지 않는다.
로봇 위치 · 상태처럼 실시간 값은 여기 넣지 않는다 (app.py 메모리).
관제 화면은 DB 를 읽기만 한다. 쓰기는 main.py → db_manager.py 하나 (2026-10-29, (나) 방식).
"""
import os
import re
import threading
from datetime import date, datetime, time as dtime, timedelta

# ---- 화면 표기 대응표 ----------------------------------------------------------
PARTS = ["esp01", "ic_chip", "fnd", "switch"]          # inspection 의 {part}_status 컬럼 순서
PART_KO = {"esp01": "ESP-01", "ic_chip": "IC 칩", "fnd": "FND", "switch": "스위치"}
TYPE_KO = {"MISSING": "누락", "OFFSET": "위치 이탈", "TILT": "기울어짐", "REVERSE": "역삽", "SHAPE": "모양 불량"}
DEST_TEXT = {2: "2 양품 구역", 3: "3 불량 구역"}
DEST_BY_RESULT = {"PASS": 2, "FAIL": 3}

# 이벤트 종류 → 이벤트 기록 창의 분류 (app.KINDS)
EVENT_KIND = {"OBSTACLE_STOP": "safety", "REROUTE": "safety", "ESTOP": "safety", "COMM_LOST": "comm"}

# 시안용 샘플 사진 (snapshots/). 메모리 모드 예시 검사가 이 사진을 가리킨다.
SAMPLE_IMAGE = "sample_board.jpg"


def load_env(path):
    """KEY=VALUE 형식의 .env 를 읽어, 이미 설정된 환경변수는 건드리지 않고 나머지만 채운다."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _now():
    # DB 컬럼이 초 단위(DATETIME)라서 메모리 저장소도 초 단위로 맞춘다
    return datetime.now().replace(microsecond=0)


# ---- 검사 결과 코드 → 화면 문구 ------------------------------------------------
_STATUS_RE = re.compile(r"^([A-Z_]+)(?:\((.*)\))?$")


def status_defects(part, status):
    """부품 하나의 결과 코드를 불량 문구 목록으로.
    'PASS' → [], 'MISSING' → ['ESP-01 누락'], 'TILT(+4.5d)' → ['IC 칩 기울어짐 +4.5°'],
    'OFFSET(3.0px),TILT(+2.0d)' → 두 개. 모르는 코드는 그대로 보여 준다."""
    name, out = PART_KO.get(part, part), []
    for item in (status or "").split(","):
        item = item.strip()
        m = _STATUS_RE.match(item)
        if not item or (m and m.group(1) == "PASS"):
            continue
        if not m:
            out.append(f"{name} {item}")
            continue
        code, value = m.groups()
        text = f"{name} {TYPE_KO.get(code, code)}"
        if value:
            if code == "TILT":
                value = value.rstrip("d") + "°"
            elif code == "SHAPE":
                value = f"(원형도 {value})"
            text += " " + value
        out.append(text)
    return out


def defect_summary(labels):
    """불량 여러 개를 한 줄로: 'FND 위치 이탈 19.3px 외 1건'"""
    if not labels:
        return None
    return labels[0] + (f" 외 {len(labels) - 1}건" if len(labels) > 1 else "")


def insp_no(iid):
    return f"#{iid:04d}"


def format_inspection(row, dest_marker):
    """inspection 줄(dict) → 화면이 쓰는 검사 결과 모양."""
    parts, labels = [], []
    for p in PARTS:
        found = status_defects(p, row[f"{p}_status"])
        labels += found
        # 부품 칸에는 이름이 이미 있으므로 문구에서 부품 이름은 뺀다 ('ESP-01 누락' → '누락')
        text = "; ".join(t[len(PART_KO[p]) + 1:] for t in found)
        parts.append({"name": PART_KO[p], "ok": not found, "text": text or "정상"})
    dest = dest_marker or DEST_BY_RESULT[row["result"]]
    return {
        "id": insp_no(row["inspection_id"]),
        "time": row["inspected_at"].strftime("%H:%M:%S"),
        "result": row["result"],
        "fail": row["result"] == "FAIL",
        "defect": defect_summary(labels),
        "defects": labels,
        "parts": parts,
        "dest": DEST_TEXT.get(dest, f"{dest}번 구역"),
        "image": row["img_path"],
    }


def format_avg(sec):
    if sec is None:
        return "-"
    sec = int(round(float(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


# ---- 이벤트 기록 창: 세 테이블을 시간순으로 합친다 --------------------------------
def _secs(a, b):
    return int(round((b - a).total_seconds()))


def _inspection_line(r):
    labels = [t for p in PARTS for t in status_defects(p, r[f"{p}_status"])]
    text = f"검사 {insp_no(r['inspection_id'])} {r['result']}"
    return text + (f" · {defect_summary(labels)}" if labels else "")


def _delivery_lines(d):
    job, dest = f"작업 #{d['delivery_id']}", DEST_TEXT.get(d["dest_marker"], f"{d['dest_marker']}번 구역")
    insp = f" · 검사 {insp_no(d['inspection_id'])}" if d["inspection_id"] else ""
    total = f" · 총 {format_avg(d['total_sec'])}" if d["total_sec"] is not None else ""
    return [
        (d["called_at"], f"{job} 호출{insp} → {dest}"),
        (d["station_arrived_at"], f"{job} 검사대 도착"),
        (d["departed_at"], f"{job} 하역장으로 출발 → {dest}"),
        (d["return_started_at"], f"{job} 대기소 복귀 시작{total}"),
    ]


def _event_line(e):
    job = f" · 작업 #{e['delivery_id']}" if e["delivery_id"] else ""
    after = _secs(e["occurred_at"], e["resumed_at"]) if e["resumed_at"] else None
    t = e["event_type"]
    if t == "OBSTACLE_STOP":
        return f"장애물 감지 · 일시 정지{job}" + (f" · {after}초 뒤 재출발" if after is not None else " · 정지 중")
    if t == "REROUTE":
        return f"장애물 감지 · 경로 재탐색{job}" + (f" · {after}초 뒤 재출발" if after is not None else "")
    if t == "COMM_LOST":
        return f"로봇 통신 끊김{job}" + (f" · {after}초 뒤 복구" if after is not None else " · 복구 전")
    if t == "ESTOP":
        return f"비상 정지 (관제 콘솔){job}" + (f" · {after}초 뒤 해제" if after is not None else " · 정지 중")
    return t


def timeline(inspections, deliveries, events, day, kind="all", limit=50):
    """이벤트 기록 창의 줄 목록 (최신 순). kind: all | insp | deliv | safety | comm"""
    rows = []
    if kind in ("all", "insp"):
        rows += [(r["inspected_at"], "insp", _inspection_line(r)) for r in inspections]
    if kind in ("all", "deliv"):
        rows += [(at, "deliv", text) for d in deliveries for at, text in _delivery_lines(d)]
    for e in events:
        k = EVENT_KIND.get(e["event_type"], "safety")
        if kind in ("all", k):
            rows.append((e["occurred_at"], k, _event_line(e)))
    rows = [r for r in rows if r[0] is not None and (day is None or r[0].date() == day)]
    # 같은 초에 생긴 줄은 나중에 넣은 것(큰 번호)이 위로 오게 순번도 같이 비교한다
    order = sorted(range(len(rows)), key=lambda i: (rows[i][0], i), reverse=True)
    return [{"date": rows[i][0].strftime("%Y-%m-%d"), "time": rows[i][0].strftime("%H:%M:%S"),
             "kind": rows[i][1], "text": rows[i][2]} for i in order[:limit]]


# =============================================================================
# 메모리 저장소 (가짜 데이터)
# =============================================================================
class MemoryStore:
    """db/seed.sql 과 같은 내용을 메모리에 들고 있는다. 서버를 끄면 처음으로 돌아간다."""

    name = "메모리 (가짜 데이터, 서버를 끄면 초기화)"

    def __init__(self):
        self._lock = threading.Lock()
        # 예시 시각은 '서버를 켠 시각 직전 15분' 안에 둔다 (seed.sql 의 @t0 와 같음).
        # 그래야 새로 생기는 기록이 항상 예시보다 뒤(최신)에 쌓인다.
        t0 = max(_now() - timedelta(minutes=15), datetime.combine(date.today(), dtime()))

        def at(ms):
            if ms is None:
                return None
            m, s = map(int, ms.split(":"))
            return t0 + timedelta(minutes=m, seconds=s)

        # 줄 모양은 DB 컬럼과 같다
        self.inspections = {}
        for iid, result, ms, esp01, ic_chip, fnd, switch in [
            (37, "PASS", "00:00", "PASS", "PASS", "PASS", "PASS"),
            (38, "PASS", "02:15", "PASS", "PASS", "PASS", "PASS"),
            (39, "PASS", "04:57", "PASS", "PASS", "PASS", "PASS"),
            (40, "FAIL", "07:25", "PASS", "TILT(+4.1d)", "PASS", "PASS"),
            (41, "PASS", "09:45", "PASS", "PASS", "PASS", "PASS"),
            (42, "FAIL", "11:35", "PASS", "PASS", "OFFSET(19.3px)", "OFFSET(16.8px)"),   # 비뚤게 놓임 → 재촬영
            (43, "FAIL", "11:53", "MISSING", "PASS", "PASS", "PASS"),
        ]:
            self.inspections[iid] = {"inspection_id": iid, "result": result, "inspected_at": at(ms),
                                     "esp01_status": esp01, "ic_chip_status": ic_chip, "fnd_status": fnd,
                                     "switch_status": switch, "img_path": SAMPLE_IMAGE}

        self.deliveries = {}
        for did, iid, dest, called, arrived, departed, returned, total in [
            (35, 37, 2, "00:03", "00:25", "00:41", "01:47", 104),
            (36, 38, 2, "02:18", "02:39", "02:54", "04:11", 113),
            (37, 39, 2, "05:00", "05:21", "05:36", "06:36", 96),
            (38, 40, 3, "07:28", "07:50", "08:06", "09:26", 118),
            (39, 41, 2, "09:48", "10:10", "10:26", "11:26", 98),
            (40, 43, 3, "11:55", "12:09", "12:36", None, None),
        ]:
            self.deliveries[did] = {"delivery_id": did, "inspection_id": iid, "dest_marker": dest,
                                    "called_at": at(called), "station_arrived_at": at(arrived),
                                    "departed_at": at(departed), "return_started_at": at(returned),
                                    "total_sec": total}

        self.events = []
        for did, etype, ms, x, y, resumed in [
            (36, "REROUTE", "03:25", 1.300, 0.720, "03:29"),
            (38, "COMM_LOST", "08:45", None, None, "08:47"),
            (40, "OBSTACLE_STOP", "13:07", 1.050, 0.720, "13:09"),
        ]:
            self._add_event(did, etype, at(ms), x, y, at(resumed))

    def _add_event(self, delivery_id, event_type, occurred_at, x=None, y=None, resumed_at=None):
        self.events.append({"event_id": len(self.events) + 1,
                            "delivery_id": delivery_id if delivery_id in self.deliveries else None,
                            "event_type": event_type, "occurred_at": occurred_at, "x": x, "y": y,
                            "resumed_at": resumed_at})

    def _delivery_of(self, iid):
        for d in self.deliveries.values():
            if d["inspection_id"] == iid:
                return d
        return None

    # ---- 읽기 ----
    def latest_inspection(self):
        with self._lock:
            if not self.inspections:
                return None
            row = self.inspections[max(self.inspections)]
            d = self._delivery_of(row["inspection_id"])
            return format_inspection(row, d["dest_marker"] if d else None)

    def recent(self, n=6):
        with self._lock:
            ids = sorted(self.inspections)[-n:]
            return [[insp_no(i), self.inspections[i]["result"] == "PASS"] for i in ids]

    def today_summary(self):
        """오늘 주행으로 이어진 검사(= 기판별 최종 검사)만 센다. 재촬영 전 검사는 빠진다."""
        with self._lock:
            start = datetime.combine(date.today(), dtime())
            final = [self.inspections[d["inspection_id"]] for d in self.deliveries.values()
                     if d["inspection_id"] in self.inspections]
            today = [r for r in final if r["inspected_at"] >= start]
            ok = sum(1 for r in today if r["result"] == "PASS")
            secs = [d["total_sec"] for d in self.deliveries.values()
                    if d["return_started_at"] and d["return_started_at"] >= start and d["total_sec"] is not None]
            return {"total": len(today), "pass_rate": round(ok / len(today) * 100) if today else 0,
                    "avg": format_avg(sum(secs) / len(secs) if secs else None)}

    def events_on(self, day, kind="all", limit=50):
        with self._lock:
            return timeline(list(self.inspections.values()), list(self.deliveries.values()),
                            list(self.events), day, kind, limit)


# =============================================================================
# MySQL 저장소
# =============================================================================
class MySQLStore:
    """fms DB 를 읽기만 한다. 요청마다 연결을 새로 열고 닫는다 (관제 화면 규모에서는 충분히 빠름)."""

    def __init__(self):
        import pymysql  # MySQL 을 쓸 때만 필요
        self._pymysql = pymysql
        self._cfg = {
            "host": os.environ.get("FMS_DB_HOST", "127.0.0.1"),
            "port": int(os.environ.get("FMS_DB_PORT", "3306")),
            "user": os.environ.get("FMS_DB_USER", "fms_app"),
            "password": os.environ.get("FMS_DB_PASSWORD", ""),
            "database": os.environ.get("FMS_DB_NAME", "fms"),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
            "connect_timeout": 3,
        }
        self.name = f"MySQL {self._cfg['user']}@{self._cfg['host']}:{self._cfg['port']}/{self._cfg['database']}"
        # 켤 때 한 번 확인: 접속 · 2안 테이블이 없으면 여기서 바로 알려 준다
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM information_schema.columns WHERE table_schema = %s AND ("
                        "(table_name = 'inspection' AND column_name = 'inspection_id') OR "
                        "(table_name = 'delivery' AND column_name = 'delivery_id') OR "
                        "(table_name = 'event' AND column_name = 'event_type'))",
                        (self._cfg["database"],))
            if cur.fetchone()["n"] != 3:
                raise RuntimeError("fms DB 에 2안 테이블이 없습니다. root 로 db/drop_v1.sql(1안을 만든 경우) → "
                                   "db/schema.sql → db/seed.sql 순서로 실행하세요.")

    def _conn(self):
        return self._pymysql.connect(**self._cfg)

    # ---- 읽기 ----
    def latest_inspection(self):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT i.*, d.dest_marker FROM inspection i "
                        "LEFT JOIN delivery d ON d.inspection_id = i.inspection_id "
                        "ORDER BY i.inspection_id DESC LIMIT 1")
            row = cur.fetchone()
        return format_inspection(row, row["dest_marker"]) if row else None

    def recent(self, n=6):
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT inspection_id, result FROM inspection ORDER BY inspection_id DESC LIMIT %s", (n,))
            rows = cur.fetchall()
        return [[insp_no(r["inspection_id"]), r["result"] == "PASS"] for r in reversed(rows)]

    def today_summary(self):
        """오늘 주행으로 이어진 검사(= 기판별 최종 검사)만 센다. 재촬영 전 검사는 빠진다."""
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS total, COALESCE(SUM(i.result = 'PASS'), 0) AS ok "
                        "FROM inspection i JOIN delivery d ON d.inspection_id = i.inspection_id "
                        "WHERE i.inspected_at >= CURDATE()")
            s = cur.fetchone()
            cur.execute("SELECT AVG(total_sec) AS avg FROM delivery "
                        "WHERE return_started_at >= CURDATE() AND total_sec IS NOT NULL")
            avg = cur.fetchone()["avg"]
        total, ok = int(s["total"]), int(s["ok"])
        return {"total": total, "pass_rate": round(ok / total * 100) if total else 0, "avg": format_avg(avg)}

    def events_on(self, day, kind="all", limit=50):
        # 테이블마다 최근 것만 가져와 합친다. 날짜를 고르면 그날 범위만 (주행은 전날 호출된 것도 포함).
        if day is not None:
            lo, hi = datetime.combine(day, dtime()), datetime.combine(day, dtime()) + timedelta(days=1)
            where_i, args_i = "WHERE inspected_at >= %s AND inspected_at < %s", [lo, hi]
            where_d, args_d = "WHERE called_at >= %s AND called_at < %s", [lo - timedelta(days=1), hi]
            where_e, args_e = "WHERE occurred_at >= %s AND occurred_at < %s", [lo, hi]
        else:
            where_i = where_d = where_e = ""
            args_i, args_d, args_e = [], [], []
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT * FROM inspection {where_i} ORDER BY inspected_at DESC LIMIT %s", args_i + [limit])
            insps = cur.fetchall()
            cur.execute(f"SELECT * FROM delivery {where_d} ORDER BY called_at DESC LIMIT %s", args_d + [limit])
            delivs = cur.fetchall()
            cur.execute(f"SELECT * FROM event {where_e} ORDER BY occurred_at DESC LIMIT %s", args_e + [limit])
            events = cur.fetchall()
        return timeline(insps, delivs, events, day, kind, limit)


def open_store():
    """환경변수에 따라 저장소를 고른다. MySQL 로 정했는데 접속이 안 되면 바로 오류를 낸다
    (조용히 가짜 데이터로 바뀌면 DB 문제를 모르고 지나치기 쉬움)."""
    kind = os.environ.get("FMS_STORE") or ("mysql" if os.environ.get("FMS_DB_PASSWORD") else "memory")
    if kind == "mysql":
        try:
            return MySQLStore()
        except Exception as e:
            raise SystemExit(f"[!] MySQL 에 연결할 수 없습니다: {e}\n"
                             f"    .env 의 FMS_DB_* 설정과 MySQL 실행 여부를 확인하세요. "
                             f"DB 없이 켜려면 FMS_STORE=memory") from None
    return MemoryStore()
