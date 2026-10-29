"""기판 검사·이송 관제 콘솔 — Flask 서버.

화면(HTML/CSS/JS)은 templates/, static/ 에 두고, 서버는 API로 데이터를 내려준다.
  검사 · 주행 · 이벤트 기록 → store.py (MySQL 또는 메모리 가짜 데이터, .env 로 고름)
  로봇 위치 · 상태 → 이 파일의 메모리 (main.py 의 /fms/status 로 받음, ros_bridge.py)
  화면은 보기 전용이다. 비상 정지 · 적재 · 하역은 main.py 창의 키로 한다.
"""
import os
import threading
import time
from datetime import date, datetime
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_from_directory

import fms_map
import ros_bridge
import store

app = Flask(__name__)
BASE = Path(__file__).resolve().parent
store.load_env(BASE / ".env")   # DB 접속 설정 (FMS_DB_*). 없으면 메모리 가짜 데이터로 동작

# ---- 지도 · 구역 (서버 켤 때 한 번 읽음. 파일을 바꾸면 서버를 다시 켠다) -------
# 기본은 maps/map_test1.yaml(실제 맵핑, 2026-10-26) + config/zones.yaml. 다른 지도로 켜려면 환경변수로 지정한다.
#   FMS_MAP=maps/다른지도.yaml  FMS_ZONES=config/다른구역.yaml  (.env 에 적어도 된다)
MAP_YAML = BASE / os.environ.get("FMS_MAP", "maps/map_test1.yaml")
ZONES_YAML = BASE / os.environ.get("FMS_ZONES", "config/zones.yaml")
# 지도 · 구역 파일이 깨져 있어도 서버는 켠다 (화면 지도 칸에 "지도 파일 없음", 나머지 기능은 그대로)
try:
    MAP_META, MAP_PNG = fms_map.load_map(MAP_YAML)
except Exception as e:      # yaml 형식 오류 · 그림 파일 없음 · 값 누락 등
    print(f" * [!] 지도를 읽을 수 없습니다: {e}")
    MAP_META, MAP_PNG = None, None
try:
    ZONES = fms_map.load_zones(ZONES_YAML)
except Exception as e:
    print(f" * [!] 구역 파일을 읽을 수 없습니다: {e}")
    ZONES = {"zones": [], "labels": [], "demo_plan": []}
print(f" * 지도: {MAP_YAML.relative_to(BASE) if MAP_YAML.is_relative_to(BASE) else MAP_YAML}"
      f"{'' if MAP_META else ' (없음)'} · 구역: {ZONES_YAML.name}")

# ---- 검사 사진 폴더 -----------------------------------------------------------
# 검사 프로그램이 검사마다 사진 한 장을 저장하고, DB inspection.img_path 에 이 폴더 기준 경로를 남긴다
# (예: logs/pass/img_pass_..._0001.jpg). 메인 화면 스냅샷 칸이 이 사진을 보여 준다.
# 실시간 검출 화면은 같은 관제 PC의 검사 프로그램 창(OpenCV)에서 본다.
# 다른 폴더를 쓰려면 FMS_SNAPSHOT_DIR. sample_* 는 시안용 샘플.
SNAPSHOT_DIR = BASE / os.environ.get("FMS_SNAPSHOT_DIR", "snapshots")


def photo_name(img_path):
    """DB 의 img_path → /snapshots/ 아래에서 찾을 이름.
    검사 프로그램이 절대 경로(/home/.../fms_main/logs/pass/...)로 저장해도
    SNAPSHOT_DIR 안이면 그 기준 상대 경로(logs/pass/...)로 바꾼다. 상대 경로는 그대로."""
    if not img_path:
        return img_path
    p = Path(img_path)
    if not p.is_absolute():
        return img_path
    try:
        return p.resolve().relative_to(SNAPSHOT_DIR.resolve()).as_posix()
    except ValueError:      # 사진 폴더 밖 → 화면은 "사진 없음"
        return img_path


# ---- 화면 정의 -------------------------------------------------------------
# main.py mission_state → 화면 배지 (main.py 에서 확인된 6개, 2026-10-29. 모르는 이름은 "주행 중")
MISSIONS = {
    "IDLE_WAIT": "대기",
    "MOVING_TO_INSPECT": "검사대로 이동",
    "WAIT_LOADING": "적재 대기",
    "MOVING_TO_DEST": "이송 중",
    "WAIT_UNLOADING": "하역 대기",
    "RETURNING_HOME": "복귀 중",
}

STATES = {
    "normal": {"tone": "run", "badge": "이송 중", "code": ""},
    "safety": {
        "tone": "warn", "badge": "안전 정지", "code": "",
        "banner": ["보행자 감지 · 안전 정지",
                   "경고음 출력 중 · 사람이 경로에서 벗어나면 자동으로 이어서 주행합니다"],
        "timerFrom": 8,
    },
    "lost": {
        "tone": "crit", "badge": "통신 끊김", "code": "마지막 상태: 이송 중",
        "banner": ["로봇 통신 끊김",
                   "로봇 전원과 와이파이 연결을 확인하세요 · 검사는 계속 진행됩니다"],
        "timerFrom": 12,
    },
}

KINDS = {
    "insp": ["검사", "k-insp"],
    "deliv": ["주행", "k-deliv"],
    "safety": ["안전", "k-safety"],
    "comm": ["통신", "k-comm"],
}

# ---- 검사 · 이송 · 이벤트 기록 저장소 ---------------------------------------
STORE = store.open_store()
print(f" * 데이터: {STORE.name}")

# ---- 로봇 실시간 상태 (메모리) ----------------------------------------------
_lock = threading.Lock()

# 통신 · 배터리 기준 (CLAUDE.md "서버 구조" 3번, "토픽 인터페이스" 배터리)
COMM_DELAY_SEC = 1.0                    # 마지막 수신 후 이 시간이 넘으면 '지연'
COMM_LOST_SEC = 3.0                     # 이 시간이 넘으면 '끊김' (COMM_LOST 이벤트 기록)
BATT_FULL_V, BATT_EMPTY_V = 12.6, 10.5  # 3셀 LiPo. 11.0 V 근처(약 25%)부터 경고
BATT_LOW_PCT = 25

robot = {"state": "normal", "since": time.time(), "last_seen": None, "battery": None, "fms": None}

# 지금 수행 중인 작업. plan 은 계획 경로(지도 좌표 m) — 실제로는 Nav2 /plan 또는
# /robot/status 로 받아야 하는데 설계 지침에 아직 없음(확정 필요).
# 시안에서는 화면이 이 경로를 따라 로봇을 움직이고, 실제 연동 때는 로봇 x · y · yaw 를 받는다.
# 시안용 경로는 지도마다 달라서 구역 파일의 demo_plan 에 둔다.
job = {
    "id": 40,
    "dest_marker": 3,
    "plan": ZONES["demo_plan"],
}


def battery_percent(percentage=None, voltage=None):
    """sensor_msgs/BatteryState 값 → 0~100 정수.
    percentage 는 ROS 규격상 0.0~1.0 (100 단위로 오면 그대로). 비었거나 0 · NaN 이면 전압으로 계산."""
    if percentage is not None and percentage == percentage and percentage > 0:   # NaN 은 자기 자신과 다름
        pct = percentage * 100 if percentage <= 1.0 else percentage
    elif voltage:
        pct = (voltage - BATT_EMPTY_V) / (BATT_FULL_V - BATT_EMPTY_V) * 100
    else:
        return None
    return max(0, min(100, round(pct)))


def update_robot(percentage=None, voltage=None):
    """로봇에서 무언가를 받았을 때 부른다 (마지막 수신 시각 + 배터리). update_fms() 와 개발용 /api/robot 이 부른다."""
    pct = battery_percent(percentage, voltage)
    with _lock:
        robot["last_seen"] = time.time()
        if pct is not None:
            robot["battery"] = pct


def update_fms(data):
    """main.py 의 /fms/status (system_state 전체) 를 받았을 때 ros_bridge 가 부른다.
    숫자가 아니거나 빠진 값은 None 으로 두고, 배터리 · 수신 시각은 update_robot() 으로 넘긴다."""
    r = data.get("robot")
    if not isinstance(r, dict):
        r = {}

    def num(key):
        v = r.get(key)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    fms = {
        "mission": str(r.get("mission_state") or ""),
        "x": num("x"), "y": num("y"), "yaw_deg": num("yaw_deg"),
        "speed": num("speed"), "front_dist": num("front_dist"),
        "queue": data.get("queue_length"),
    }
    with _lock:
        robot["fms"] = fms
    update_robot(num("battery"))


def robot_link():
    """통신 상태 판단. 화면에 보낼 dict 를 돌려준다.
    DB 에는 기록하지 않는다 (DB 쓰기는 main.py 하나, 통신 끊김 기록은 main.py 몫)."""
    now = time.time()
    with _lock:
        seen, pct = robot["last_seen"], robot["battery"]
        age = None if seen is None else now - seen
        if age is None:
            comm = "none"
        elif age > COMM_LOST_SEC:
            comm = "lost"
        elif age > COMM_DELAY_SEC:
            comm = "delay"
        else:
            comm = "ok"
    return {"comm": comm, "age": None if age is None else round(age, 2),
            "battery": pct, "battery_low": pct is not None and pct <= BATT_LOW_PCT}


def snapshot():
    """화면이 2초마다 받아 가는 전체 상태. 로봇 값은 잠금 안에서 복사하고, DB 조회는 잠금 밖에서 한다."""
    with _lock:
        live = {"state": robot["state"], "since": robot["since"], "job": dict(job),
                "fms": dict(robot["fms"]) if robot["fms"] else None}
    insp = STORE.latest_inspection()
    if insp:
        insp["image"] = photo_name(insp["image"])
    live.update({
        "server_time": time.time(),
        "robot": robot_link(),
        "inspection": insp,
        "recent": STORE.recent(6),
        "today": STORE.today_summary(),
    })
    return live


# ---- 페이지 ----------------------------------------------------------------
@app.route("/")
def index():
    status = snapshot()
    boot = {"states": STATES, "missions": MISSIONS, "kinds": KINDS, "status": status,
            "map": MAP_META, "zones": ZONES}
    return render_template("index.html", kinds=KINDS, today=status["today"],
                           today_date=date.today().isoformat(), boot=boot)


@app.get("/map/image.png")
def map_image():
    """지도 마스크 PNG (벽 = 흰색, 모름 = 반투명, 빈 곳 = 투명)."""
    if MAP_PNG is None:
        abort(404, "지도 파일이 없습니다")
    return Response(MAP_PNG, mimetype="image/png")


@app.get("/snapshots/<path:name>")
def snapshot_image(name):
    """검사 사진. send_from_directory 가 폴더 밖 경로(../ 등)는 막아 준다."""
    return send_from_directory(SNAPSHOT_DIR, name, max_age=0)


# ---- API -------------------------------------------------------------------
@app.get("/api/status")
def api_status():
    return jsonify(snapshot())


@app.post("/api/robot")
def api_robot():
    """개발용: ROS 없이 로봇 값을 넣어 본다. {"percentage": 0.76} / {"voltage": 11.9} / {} (수신만) / {"fms": {...}}
    실제 연동 때는 rclpy 콜백이 update_fms() 를 직접 부르므로 이 창구는 지운다."""
    d = request.get_json(silent=True)
    if d is None:
        d = {}
    if not isinstance(d, dict):
        abort(400, "JSON 객체({ ... })로 보내 주세요")
    if isinstance(d.get("fms"), dict):          # {"fms": {"robot": {...}, "queue_length": 0}} = /fms/status 흉내
        update_fms(d["fms"])
        return jsonify({"ok": True})
    try:
        pct = None if d.get("percentage") is None else float(d["percentage"])
        volt = None if d.get("voltage") is None else float(d["voltage"])
    except (TypeError, ValueError):
        abort(400, "percentage · voltage 는 숫자여야 합니다")
    update_robot(pct, volt)
    return jsonify({"ok": True})


@app.get("/api/events")
def api_events():
    """이벤트 기록 (최신 순 최대 50건). date=YYYY-MM-DD (비우면 전체), kind=all|insp|deliv|safety|comm"""
    try:
        day = date.fromisoformat(request.args["date"]) if request.args.get("date") else None
    except ValueError:
        abort(400, "날짜 형식은 YYYY-MM-DD")
    kind = request.args.get("kind", "all")
    if kind != "all" and kind not in KINDS:
        abort(400, "unknown kind")
    rows = STORE.events_on(day, kind, limit=50)
    return jsonify({"rows": rows, "queried_at": datetime.now().strftime("%H:%M:%S")})


# ---- ROS 2 연결 (FMS_ROS=1 일 때만) -------------------------------------------
# 디버그 자동 재시작(reloader)이 켜져 있으면 노드가 두 번 뜨므로 --no-reload 로 실행한다.
# 도메인 번호는 ros_bridge.DOMAIN_ID (22). 환경변수 ROS_DOMAIN_ID 가 있으면 그 값.
BRIDGE = None
if os.environ.get("FMS_ROS") == "1":
    BRIDGE = ros_bridge.start({
        "fms": update_fms,                     # /fms/status (main.py)
        "tick": robot_link,                    # 1초마다 통신 판단
    })
    print(f" * ROS: {'연결됨 · ROS_DOMAIN_ID=' + os.environ.get('ROS_DOMAIN_ID', '') if BRIDGE else 'rclpy 없음 (ROS 없이 동작)'}")


if __name__ == "__main__":
    # 개발용: 디버그 모드라서 이 PC에서만 열어 둔다 (디버그 화면에서 코드 실행이 가능하므로).
    # 다른 PC와 공유할 때는 VS Code 실행 설정의 "공유용: ..." 을 쓴다.
    app.run(host="127.0.0.1", port=5000, debug=True)
