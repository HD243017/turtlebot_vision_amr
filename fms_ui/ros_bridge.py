"""관제 서버 ↔ ROS 2 연결 (rclpy). 토픽 이름과 도메인 번호는 이 파일 맨 위에서만 정한다.

받는 것은 main.py 가 보내는 /fms/status 하나다 (B 구조: 로봇 · 검사 정보는 모두 main.py 를 거친다).
받은 값의 처리는 app.py 의 함수가 한다(handlers 로 넘겨받음). 여기서는 토픽을 받기만 한다.
관제 화면은 보기 전용이라 보내는 토픽은 없다 (비상 정지 · 적재 · 하역은 main.py 창의 키로).
rclpy 가 없으면(Windows 개발 PC) start() 가 None 을 돌려주고, 서버는 ROS 없이 지금처럼 동작한다.
"""

import json
import os
import threading

try:
    import rclpy
    from rclpy.executors import ExternalShutdownException
    from rclpy.node import Node
    from std_msgs.msg import String
except ImportError:      # ROS 가 없는 PC
    rclpy = None
    Node = object

# ---- 도메인 번호 · 토픽 이름 (팀과 바뀌면 여기만 고친다) ----------------------------
DOMAIN_ID = "22"                       # 팀 확정 (2026-10-26). 환경변수 ROS_DOMAIN_ID 가 있으면 그 값이 우선
TOPIC_FMS_STATUS = "/fms/status"       # std_msgs/String (JSON). main.py 의 system_state 전체. 받으면 '통신 살아 있음'


class Bridge(Node):
    def __init__(self, handlers):
        super().__init__("fms_web")
        self.h = handlers
        self.create_subscription(String, TOPIC_FMS_STATUS, self.on_fms_status, 10)
        self.create_timer(1.0, self.h["tick"])          # 통신 끊김 판단 1초마다

    def on_fms_status(self, msg):
        try:
            data = json.loads(msg.data)
        except ValueError:
            self.get_logger().warning(f"/fms/status JSON 아님: {msg.data[:80]!r}")
            return
        if not isinstance(data, dict):
            self.get_logger().warning("/fms/status 는 JSON 객체({ ... })여야 합니다")
            return
        self.h["fms"](data)


def start(handlers):
    """rclpy 를 켜고 노드를 별도 스레드에서 돌린다. ROS 가 없으면 None."""
    if rclpy is None:
        return None
    os.environ.setdefault("ROS_DOMAIN_ID", DOMAIN_ID)   # rclpy.init() 전에 정해야 적용된다
    rclpy.init()
    node = Bridge(handlers)
    threading.Thread(target=_spin, args=(node,), daemon=True).start()
    return node


def _spin(node):
    # 서버를 끌 때(Ctrl+C) rclpy 가 먼저 닫히면 spin 이 예외를 던진다. 끄는 중이라 조용히 끝낸다.
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, KeyboardInterrupt):
        pass
