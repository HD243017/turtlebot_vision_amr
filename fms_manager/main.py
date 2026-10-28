import os
import json
import math
import time
import threading
from collections import deque
from datetime import datetime
import cv2

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
    print("[WARN] rclpy 모듈을 찾을 수 없습니다. ROS 2 통신이 비활성화된 단독 테스트 모드로 실행됩니다.")

# 작성해 두신 검사대 모듈 임포트 (같은 폴더에 pcb_cv_inspector3_2.py가 있어야 함)
from pcb_cv_inspector3_2 import PCBInspector, SerialHandler, execute_inspection_sequence

# DB매니저 임포트 시도 (UI/DB 담당자가 아직 안 만들었어도 자동으로 Mock 클래스로 대체!)
try:
    from db_manager import DBManager
except ImportError:
    class DBManager:
        def __init__(self):
            print("[DB-MOCK] db_manager.py 미감지 -> 터미널 출력 모드로 대체 동작합니다.")

        def insert_inspection_result(self, db_record: dict):
            print(f"\n[DB-MOCK INSERT] 검사 결과 DB 저장 요청 수신:")
            print(f"  -> {json.dumps(db_record, ensure_ascii=False)}")
            return int(time.time()) % 10000  # 임시 작업 ID 반환

        def update_delivery_complete(self, job_id: int, elapsed_sec: float):
            print(f"\n[DB-MOCK UPDATE] 작업 #{job_id} 배송 완료 기록! (총 이송 소요시간: {elapsed_sec:.1f}초)")


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
            # 1. [main.py -> A* 노드] 명령 발행 퍼블리셔 (/task_command)
            self.pub_task_cmd = self.create_publisher(String, '/task_command', 10)

            # 2. [A* 노드 -> main.py] 로봇 미션 상태 및 계획된 경로 구독
            self.create_subscription(String, '/robot_state', self.cb_robot_state, 10)
            self.create_subscription(Path, '/planned_path', self.cb_planned_path, 10)

            # 3. [터틀봇 -> main.py] 위치 좌표, 도착/막힘 보고, 속도, 라이다 전방거리, 배터리 구독
            self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.cb_pose, 10)
            self.create_subscription(String, '/bot_report', self.cb_bot_report, 10)
            self.create_subscription(Twist, '/cmd_vel', self.cb_cmd_vel, 10)
            self.create_subscription(LaserScan, '/scan', self.cb_scan, qos_profile_sensor_data)
            self.create_subscription(BatteryState, '/battery_state', self.cb_battery, 10)

            print("[INFO] ROS 2 중앙 관제 노드(central_fms_manager) 초기화 완료!")

    # =========================================================================
    # [ROS 2 수신 콜백 함수들] A* 및 터틀봇에서 올라오는 실시간 정보 업데이트
    # =========================================================================
    def cb_robot_state(self, msg):
        prev_state = self.system_state["robot"]["mission_state"]
        new_state = msg.data
        self.system_state["robot"]["mission_state"] = new_state

        # 상태가 바뀔 때만 터미널에 눈에 띄게 로그 출력
        if prev_state != new_state:
            print(f"\n🔄 [A* 상태 변경] {prev_state} ➔ {new_state}")

            if new_state == "WAIT_LOADING":
                print("   👉 [안내] 터틀봇이 검사대에 도착했습니다! 물건을 올리고 [L] 키(적재 완료)를 누르세요.")
            elif new_state == "WAIT_UNLOADING":
                print("   👉 [안내] 터틀봇이 목적지에 도착했습니다! 물건을 내리고 [U] 키(하역 완료)를 누르세요.")
            elif prev_state == "WAIT_UNLOADING" and new_state == "RETURNING_HOME":
                # 하역 완료 후 복귀를 시작하는 순간 -> DB에 배송 완료 및 총 소요 시간 기록!
                if self.current_job and self.job_start_time:
                    elapsed = time.time() - self.job_start_time
                    self.db_manager.update_delivery_complete(self.current_job.get("job_id", 0), elapsed)
                    self.current_job = None
                    self.job_start_time = None

        # 로봇이 대기소(IDLE_WAIT)에 있고, 대기열(Queue)에 검사 끝난 보드가 있다면 자동 배차!
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
        print(f"\n📢 [터틀봇 보고 수신] /bot_report : '{msg.data}'")

    def cb_planned_path(self, msg):
        self.system_state["robot"]["waypoint_count"] = len(msg.poses)
        print(f"\n🗺️ [A* 경로 생성됨] 총 {len(msg.poses)}개의 웨이포인트가 터틀봇으로 전달되었습니다.")

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
        """
        pcb_cv_inspector3_2.py의 execute_inspection_sequence() 내부에서
        robot_caller(db_record)로 자동 호출되는 콜백 함수입니다.
        """
        print(f" [MAIN] 검사대 판정 결과 수신 완료! (결과: {db_record['final_decision']})")
        print(f" [MAIN] 저장된 스냅샷 경로: {db_record['img_path']}")

        # 1. 최신 검사 정보 갱신 및 작업 큐(스케줄러)에 등록
        self.system_state["latest_inspection"] = db_record
        self.job_queue.append(db_record)
        self.system_state["queue_length"] = len(self.job_queue)

        # 2. 로봇이 현재 IDLE_WAIT 상태이고 진행 중인 작업이 없으면 즉시 호출!
        if self.system_state["robot"]["mission_state"] == "IDLE_WAIT" and self.current_job is None:
            self.dispatch_next_job()
        else:
            print(f" [스케줄러] 현재 로봇이 바쁩니다({self.system_state['robot']['mission_state']}). 대기열에 추가됨 (대기: {len(self.job_queue)}건)")

    def dispatch_next_job(self):
        """대기열에서 가장 먼저 검사된 기판을 꺼내 A* 노드로 호출 명령 전송"""
        if not self.job_queue:
            return

        self.current_job = self.job_queue.popleft()
        self.system_state["queue_length"] = len(self.job_queue)
        self.job_start_time = time.time()

        decision = self.current_job["final_decision"]  # "PASS" 또는 "FAIL"
        print(f"\n [스케줄러 배차 시작] 판정 결과 '{decision}' 기판 이송을 위해 터틀봇을 검사대로 호출합니다!")

        # ros2_astar_dwa.cpp의 commandCallback 규격에 맞춰 판정 결과와 CALL 명령 전송
        self.send_task_command(decision)
        self.send_task_command("CALL")

    def send_task_command(self, cmd_str: str):
        """A* 노드의 /task_command 토픽으로 명령 문자열 발행"""
        if ROS_AVAILABLE:
            msg = String()
            msg.data = cmd_str
            self.pub_task_cmd.publish(msg)
            print(f" [main.py ➔ A* 명령 전송] /task_command : '{cmd_str}'")
        else:
            print(f" [ROS-MOCK 명령 전송] /task_command : '{cmd_str}'")

    def print_status_json(self):
        """현재 main.py가 수집한 모든 정보(향후 UI로 던져줄 JSON 패킷)를 터미널에 출력"""
        print("\n" + "=" * 65)
        print(" [현재 통합 관제 상태 (UI 전송용 JSON 데이터 덤프)]")
        print("=" * 65)
        print(json.dumps(self.system_state, indent=2, ensure_ascii=False))
        print("=" * 65 + "\n")


def main():
    if ROS_AVAILABLE:
        rclpy.init()

    # 1. DB 매니저 및 중앙 관제 매니저 생성
    db_mgr = DBManager()
    manager = CentralManager(db_manager=db_mgr)

    # 2. ROS 2 수신 루프(spin)를 별도 백그라운드 스레드로 실행 (카메라 루프와 동시에 돌기 위함)
    if ROS_AVAILABLE:
        ros_thread = threading.Thread(target=rclpy.spin, args=(manager,), daemon=True)
        ros_thread.start()

    # 3. 검사대(PCBInspector) 및 아두이노 시리얼 초기화
    inspector = PCBInspector(model_path="best.pt")
    serial_handler = SerialHandler(port="COM3", baudrate=115200)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[WARN] 웹캠(0번)을 열 수 없습니다. 가상 빈 화면으로 키보드 명령 테스트만 진행합니다.")

    print("\n" + "=" * 65)
    print(" [통합 관제 시스템 main.py 가동 시작]")
    print("  - [Space 바] : 수동 촬영 및 기판 검사 -> DB 저장 -> A*(터틀봇) 자동 호출")
    print("  - [L 키]     : 적재 완료 신호 전송 (LOAD_DONE -> PASS/FAIL 구역 출발)")
    print("  - [U 키]     : 하역 완료 신호 전송 (UNLOAD_DONE -> 대기소 복귀 및 DB 기록)")
    print("  - [R 키]     : 비상 정지 / 리셋 신호 전송 (RESET)")
    print("  - [P 키]     : 현재 수집된 통합 상태(JSON) 터미널에 출력해보기")
    print("  - [Q 키]     : 프로그램 종료")
    print("=" * 65 + "\n")

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
                import numpy as np
                display_frame = np.zeros((300, 500, 3), dtype=np.uint8)
                cv2.putText(display_frame, "NO CAMERA (Key Test Mode)", (40, 150),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

            # 1. 아두이노(MCU) 물리 버튼 입력('REQ_CAPTURE') 비차단 확인
            mcu_cmd = serial_handler.read_command()
            if mcu_cmd == "REQ_CAPTURE":
                print("\n[MCU 트리거] 검사대 촬영 버튼 눌림 감지! 검사를 시작합니다.")
                res_img, _ = execute_inspection_sequence(
                    cap, inspector,
                    serial_handler=serial_handler,
                    db_manager=db_mgr,
                    robot_caller=manager.on_inspection_complete, # ★ 검사 끝나면 자동으로 main 매니저 호출!
                    triggered_by_mcu=True
                )
                if res_img is not None:
                    cv2.imshow("Inspection Result", res_img)

            # 2. 카메라 화면에 현재 로봇 상태 및 키 안내 오버레이 표시
            if display_frame is not None:
                r_state = manager.system_state["robot"]["mission_state"]
                rx = manager.system_state["robot"]["x"]
                ry = manager.system_state["robot"]["y"]
                cv2.rectangle(display_frame, (0, 0), (display_frame.shape[1], 65), (25, 25, 25), -1)
                cv2.putText(display_frame, f"BOT: {r_state} | Pos:({rx:.2f}, {ry:.2f})",
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
                cv2.putText(display_frame, "[SPACE]:Inspect [L]:Load [U]:Unload [P]:Status [R]:Reset",
                            (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
                cv2.imshow("FMS Main Controller (Cam & Key Input)", display_frame)

            # 3. 키보드 입력 처리 (웹 UI 버튼 역할을 키보드로 완벽히 시뮬레이션)
            key = cv2.waitKey(20) & 0xFF
            if key == ord('q'):
                break
            elif key == ord(' '):
                print("\n[수동 트리거] 스페이스바 입력 감지! 검사를 시작합니다.")
                res_img, _ = execute_inspection_sequence(
                    cap, inspector,
                    serial_handler=serial_handler,
                    db_manager=db_mgr,
                    robot_caller=manager.on_inspection_complete, # ★ 검사 끝나면 자동으로 main 매니저 호출!
                    triggered_by_mcu=False
                )
                if res_img is not None:
                    cv2.imshow("Inspection Result", res_img)
            elif key == ord('l') or key == ord('L'):
                # 웹 UI에서 작업자가 [적재 완료] 버튼을 누른 것과 동일
                manager.send_task_command("LOAD_DONE")
            elif key == ord('u') or key == ord('U'):
                # 웹 UI에서 작업자가 [하역 완료] 버튼을 누른 것과 동일
                manager.send_task_command("UNLOAD_DONE")
            elif key == ord('r') or key == ord('R'):
                # 웹 UI에서 작업자가 [비상 정지] 버튼을 누른 것과 동일
                manager.send_task_command("RESET")
            elif key == ord('p') or key == ord('P'):
                # 현재까지 수집된 A*, 터틀봇, 검사대 정보를 터미널에 한눈에 출력
                manager.print_status_json()

    except KeyboardInterrupt:
        print("\n[INFO] 사용자에 의해 프로그램이 종료됩니다.")
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