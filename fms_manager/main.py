import os
import json
import math
import time
import threading
from collections import deque
from datetime import datetime
import cv2
import numpy as np

# ROS 2 (rclpy) 모듈 임포트 (미설치 윈도우 환경에서도 코드 구조 확인이 가능하도록 방어 처리)
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data
    from std_msgs.msg import String
    from nav_msgs.msg import Path
    from geometry_msgs.msg import PoseWithCovarianceStamped, Twist
    from sensor_msgs.msg import LaserScan, BatteryState
    ROS_AVAILABLE = True
except ImportError:
    ROS_AVAILABLE = False
    print("[WARN] rclpy 미설치: ROS 2 비활성화 단독 모드로 실행")

# 작성해 두신 검사대 모듈 임포트 (같은 폴더에 pcb_cv_inspector3_2.py가 있어야 함)
from pcb_cv_inspector3_2 import PCBInspector, SerialHandler, execute_inspection_sequence

# DB매니저 임포트 시도 (UI/DB 담당자가 아직 안 만들었어도 자동으로 Mock 클래스로 대체!)
try:
    from db_manager import DBManager
except ImportError:
    class DBManager:
        def __init__(self):
            print("[DB-MOCK] db_manager 미감지: 콘솔 출력 모드")

        def insert_inspection_result(self, db_record: dict):
            print(f"[DB-MOCK] 결과 저장: {json.dumps(db_record, ensure_ascii=False)}")
            return int(time.time()) % 10000

        def update_delivery_complete(self, job_id: int, elapsed_sec: float):
            print(f"[DB-MOCK] 작업 #{job_id} 이송 완료 기록: {elapsed_sec:.1f}초")


class CentralManager(Node if ROS_AVAILABLE else object):
    def __init__(self, db_manager):
        if ROS_AVAILABLE:
            super().__init__('central_fms_manager')

        self.db_manager = db_manager
        self.job_queue = deque()   # 검사 완료 후 로봇 배차를 기다리는 보드 대기열
        self.current_job = None    # 현재 로봇이 이송 중인 작업 정보
        self.job_start_time = None # 이송 소요 시간 측정용 타이머

        # 웹 UI로 초당 1~2회 JSON 포장해서 던져줄 통합 상태 데이터 딕셔너리
        self.system_state = {
            "robot": {
                "mission_state": "IDLE_WAIT", # A* 노드가 알려주는 미션 상태
                "last_report": "NONE",        # 터틀봇이 보고한 신호 (ARRIVED, BLOCKED 등)
                "x": 0.0,                     # 지도에 표시할 로봇 X 좌표 (m)
                "y": 0.0,                     # 지도에 표시할 로봇 Y 좌표 (m)
                "yaw_deg": 0.0,               # 로봇 바라보는 각도 (도)
                "speed": 0.0,                 # 현재 선속도 (m/s)
                "battery": 100.0,             # 배터리 잔량 (%)
                "front_dist": 99.9,           # 전방 가장 가까운 물체 거리 (m)
                "waypoint_count": 0           # 현재 할당된 A* 경로의 웨이포인트 개수
            },
            "latest_inspection": None,        # 가장 최근 검사대 판정 결과 (db_record)
            "queue_length": 0                 # 대기 중인 물량 수
        }

        if ROS_AVAILABLE:
            # 1. A* 노드 명령 발행
            self.pub_task_cmd = self.create_publisher(String, '/task_command', 10)

            # 2. UI 상태 전송용 퍼블리셔 및 0.5초 타이머
            self.pub_fms_status = self.create_publisher(String, '/fms/status', 10)
            self.create_timer(0.5, self.publish_fms_status)

            # 3. A* 및 터틀봇 토픽 구독
            self.create_subscription(String, '/robot_state', self.cb_robot_state, 10)
            self.create_subscription(Path, '/planned_path', self.cb_planned_path, 10)
            self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.cb_pose, 10)
            self.create_subscription(String, '/bot_report', self.cb_bot_report, 10)
            self.create_subscription(Twist, '/cmd_vel', self.cb_cmd_vel, 10)
            self.create_subscription(LaserScan, '/scan', self.cb_scan, qos_profile_sensor_data)
            self.create_subscription(BatteryState, '/battery_state', self.cb_battery, 10)

            print("[INIT] ROS 2 중앙 관제 노드 초기화 완료")

    def publish_fms_status(self):
        msg = String()
        msg.data = json.dumps(self.system_state, ensure_ascii=False)
        self.pub_fms_status.publish(msg)

    # [ROS 2 수신 콜백 함수들] A* 및 터틀봇에서 올라오는 실시간 정보 업데이트
    def cb_robot_state(self, msg):
        prev_state = self.system_state["robot"]["mission_state"]
        new_state = msg.data
        self.system_state["robot"]["mission_state"] = new_state

        # 상태가 바뀔 때만 터미널에 눈에 띄게 로그 출력
        if prev_state != new_state:
            print(f"[STATE] 로봇 상태 변경: {prev_state} -> {new_state}")

            if new_state == "WAIT_LOADING":
                print("[WAIT] 검사대 도착: 적재 후 [L] 키 입력 대기")
            elif new_state == "WAIT_UNLOADING":
                print("[WAIT] 목적지 도착: 하역 후 [U] 키 입력 대기")
            elif prev_state == "WAIT_UNLOADING" and new_state == "RETURNING_HOME":
                if self.current_job and self.job_start_time:
                    elapsed = time.time() - self.job_start_time
                    self.db_manager.update_delivery_complete(self.current_job.get("job_id", 0), elapsed)
                    self.current_job = None
                    self.job_start_time = None

        # 로봇이 대기소(IDLE_WAIT)에 있고, 대기열(Queue)에 검사 끝난 보드가 있다면 자동 배차
        if new_state == "IDLE_WAIT" and len(self.job_queue) > 0 and self.current_job is None:
            self.dispatch_next_job()

    def cb_pose(self, msg):
        x = msg.pose.pose.position.x
        y = msg.pose.pose.position.y
        q = msg.pose.pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))

        self.system_state["robot"]["x"] = round(x, 3)
        self.system_state["robot"]["y"] = round(y, 3)
        self.system_state["robot"]["yaw_deg"] = round(math.degrees(yaw), 1)

    def cb_bot_report(self, msg):
        self.system_state["robot"]["last_report"] = msg.data
        print(f"[REPORT] 터틀봇 보고 수신: {msg.data}")

    def cb_planned_path(self, msg):
        self.system_state["robot"]["waypoint_count"] = len(msg.poses)
        print(f"[PATH] A* 경로 생성: {len(msg.poses)} waypoints")

    def cb_cmd_vel(self, msg):
        self.system_state["robot"]["speed"] = round(msg.linear.x, 2)

    def cb_scan(self, msg):
        # 터틀봇 DWA 코드와 동일하게 전방(약 -30도 ~ +30도) 최소 장애물 거리 계산
        min_front = 99.9
        total = len(msg.ranges)
        for i in range(total):
            r = msg.ranges[i]
            if r < 0.08 or r > 1.5 or math.isnan(r) or math.isinf(r):
                continue
            angle = msg.angle_min + i * msg.angle_increment
            norm_angle = math.atan2(math.sin(angle), math.cos(angle))
            if abs(norm_angle) < 0.5 and r < min_front:
                min_front = r
        self.system_state["robot"]["front_dist"] = round(min_front, 2)

    def cb_battery(self, msg):
        self.system_state["robot"]["battery"] = round(msg.percentage, 1)

    # =========================================================================
    # [검사대 연동 및 스케줄링 함수들]
    # =========================================================================
    def on_inspection_complete(self, db_record: dict):
        print(f"[MAIN] 검사 결과 수신: {db_record['final_decision']} ({db_record['img_path']})")

        self.system_state["latest_inspection"] = db_record
        self.job_queue.append(db_record)
        self.system_state["queue_length"] = len(self.job_queue)

        # 2. 로봇이 현재 IDLE_WAIT 상태이고 진행 중인 작업이 없으면 호출
        if self.system_state["robot"]["mission_state"] == "IDLE_WAIT" and self.current_job is None:
            self.dispatch_next_job()
        else:
            print(f"[SCHEDULER] 로봇 작업 중({self.system_state['robot']['mission_state']}): 대기열 등록 (대기 {len(self.job_queue)}건)")

    def dispatch_next_job(self):
        # 대기열에서 가장 먼저 검사된 기판을 꺼내 A* 노드로 호출 명령 전송
        if not self.job_queue:
            return

        self.current_job = self.job_queue.popleft()
        self.system_state["queue_length"] = len(self.job_queue)
        self.job_start_time = time.time()

        decision = self.current_job["final_decision"]
        print(f"[SCHEDULER] 배차 시작: 판정 {decision} 기판 이송 호출")
        self.send_task_command("CALL")

    def handle_load_done(self):
        curr_state = self.system_state["robot"]["mission_state"]
        if curr_state != "WAIT_LOADING":
            print(f"[WARN] 불가: 현재 상태 {curr_state}")
            return

        if self.current_job and "final_decision" in self.current_job:
            decision = self.current_job["final_decision"]
            cmd = f"LOAD_{decision}"
            print(f"[LOAD] 적재 완료: {cmd} 전송")
            self.send_task_command(cmd)
        else:
            print("[LOAD] 작업 정보 없음: 기본 LOAD_DONE 전송")
            self.send_task_command("LOAD_DONE")

    def handle_unload_done(self):
        curr_state = self.system_state["robot"]["mission_state"]
        if curr_state != "WAIT_UNLOADING":
            print(f"[WARN] 하역 완료 무시: 현재 상태 {curr_state}")
            return

        print("[UNLOAD] 하역 완료: 대기소 복귀 명령(UNLOAD_DONE) 전송")
        self.send_task_command("UNLOAD_DONE")

    def send_task_command(self, cmd_str: str):
        if ROS_AVAILABLE:
            msg = String()
            msg.data = cmd_str
            self.pub_task_cmd.publish(msg)
            print(f"[CMD] /task_command 발행: {cmd_str}")
        else:
            print(f"[CMD-MOCK] /task_command: {cmd_str}")

    def print_status_json(self):
        print("-" * 60)
        print("[STATUS] 현재 통합 관제 상태 JSON:")
        print(json.dumps(self.system_state, indent=2, ensure_ascii=False))
        print("-" * 60)


def main():
    if ROS_AVAILABLE:
        rclpy.init()

    # DB 매니저 및 중앙 관제 매니저 생성
    db_mgr = DBManager()
    manager = CentralManager(db_manager=db_mgr)

    # ROS 2 수신 루프(spin)를 별도 백그라운드 스레드로 실행 (카메라 루프와 동시에 돌기 위함)
    if ROS_AVAILABLE:
        ros_thread = threading.Thread(target=rclpy.spin, args=(manager,), daemon=True)
        ros_thread.start()

    # main.py 파일 위치 기준 weights/best.pt 절대 경로 지정
    base_dir = os.path.dirname(os.path.abspath(__file__))
    weight_path = os.path.join(base_dir, "weights", "best.pt")

    # 검사대(PCBInspector) 및 아두이노 시리얼 초기화
    inspector = PCBInspector(model_path=weight_path)
    serial_handler = SerialHandler(port="/dev/ttyACM0", baudrate=9600)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[WARN] 웹캠(0번) 오픈 실패: 키보드 제어 모드로 동작")

    print("-" * 65)
    print("[SYSTEM] 통합 관제 main.py 가동")
    print("  - [MCU 버튼 / Space] : 기판 촬영 및 검사 -> DB 저장 -> 로봇 호출")
    print("  - [L 키] : 적재 완료 (LOAD_PASS / LOAD_FAIL)")
    print("  - [U 키] : 하역 완료 (UNLOAD_DONE)")
    print("  - [R 키] : 비상 리셋 (RESET)")
    print("  - [P 키] : 상태 JSON 출력")
    print("  - [Q 키] : 종료")
    print("-" * 65)

    try:
        while True:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret:
                    frame = cv2.flip(frame, -1)
                    display_frame = frame.copy()
                else:
                    display_frame = cv2.imread("latest_inspection_result.jpg")
            else:
                # 카메라가 없을 때도 키 입력을 받기 위한 검은색 더미 화면 생성
                display_frame = np.zeros((300, 500, 3), dtype=np.uint8)
                cv2.putText(display_frame, "NO CAMERA (Key Test Mode)", (40, 150),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            # 아두이노 물리 버튼('CAPTURE') 비차단 수신 확인
            mcu_cmd = serial_handler.poll_command()
            if mcu_cmd == "CAPTURE":
                print("[TRIGGER] 아두이노 촬영 신호 수신: 검사 시작")
                res_img, _ = execute_inspection_sequence(
                    cap, inspector,
                    serial_handler=serial_handler,
                    db_manager=db_mgr,
                    robot_caller=manager.on_inspection_complete
                )
                if res_img is not None:
                    cv2.imshow("Inspection Result", res_img)

            # 카메라 화면에 보드 가이드라인 및 로봇 상태 표시
            if display_frame is not None:
                if cap.isOpened():
                    auto_corners = inspector.find_board_corners_auto(frame)
                    if auto_corners is not None:
                        cv2.polylines(display_frame, [auto_corners.astype(np.int32)], True, (0, 255, 0), 2)

                r_state = manager.system_state["robot"]["mission_state"]
                rx = manager.system_state["robot"]["x"]
                ry = manager.system_state["robot"]["y"]
                cv2.rectangle(display_frame, (0, 0), (display_frame.shape[1], 65), (25, 25, 25), -1)
                cv2.putText(display_frame, f"BOT: {r_state} | Pos:({rx:.2f}, {ry:.2f})",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                cv2.putText(display_frame, "[SPACE]:Inspect [L]:Load [U]:Unload [P]:Status [R]:Reset",
                            (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
                cv2.imshow("FMS Main Controller", display_frame)

            # 3. 키보드 입력 처리
            key = cv2.waitKey(20) & 0xFF
            if key == ord('q'):
                break
            elif key == ord(' '):
                print("[TRIGGER] 수동 스페이스바 입력: 검사 시작")
                res_img, _ = execute_inspection_sequence(
                    cap, inspector,
                    serial_handler=serial_handler,
                    db_manager=db_mgr,
                    robot_caller=manager.on_inspection_complete
                )
                if res_img is not None:
                    cv2.imshow("Inspection Result", res_img)
            elif key == ord('l') or key == ord('L'):
                manager.handle_load_done()
            elif key == ord('u') or key == ord('U'):
                manager.handle_unload_done()
            elif key == ord('r') or key == ord('R'):
                manager.send_task_command("RESET")
            elif key == ord('p') or key == ord('P'):
                manager.print_status_json()

    except KeyboardInterrupt:
        print("[SYSTEM] 사용자 인터럽트 종료")
    finally:
        serial_handler.close()
        if cap.isOpened():
            cap.release()
        cv2.destroyAllWindows()
        if ROS_AVAILABLE:
            manager.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()