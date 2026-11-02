#!/bin/bash

WORKSPACE_DIR="$(cd "$(dirname "$0")" && pwd)"
ROS_WS_DIR="$(cd "$WORKSPACE_DIR/../.." && pwd)"
cd "$WORKSPACE_DIR"

echo "=========================================================="
echo " [FMS 관제 PC] 원클릭 통합 시스템 실행기"
echo " 프로젝트 경로: $WORKSPACE_DIR"
echo " ROS 워크스페이스: $ROS_WS_DIR"
echo "=========================================================="

clean_all_fms() {
    # 1. 포트 점유 프로세스 정리 (5000: Flask, 8080: web_video_server)
    fuser -k 5000/tcp 2>/dev/null
    fuser -k 8080/tcp 2>/dev/null

    # 2. 우리 프로젝트 관련 프로세스만 정밀 타격 (시스템 python3 보호)
    pkill -9 -f "flask --app app" 2>/dev/null
    pkill -9 -f "web_video_server" 2>/dev/null
    pkill -9 -f "astar_mission_dwa" 2>/dev/null
    pkill -9 -f "rviz2" 2>/dev/null
    pkill -9 -f "amcl" 2>/dev/null
    pkill -9 -f "map_server" 2>/dev/null
    pkill -9 -f "lifecycle_manager" 2>/dev/null
}

echo "[0/4] 기존 실행 중인 관제 및 스트리밍 프로세스 정리 중..."
pkill -9 -f "fms_manager/main.py" 2>/dev/null
clean_all_fms
sleep 1

# 무한 루프 방지 처리된 안전 종료 함수
cleanup() {
    trap - SIGINT SIGTERM EXIT
    echo -e "\n[종료] 모든 관제 서버, 영상 서버, RViz 및 네비게이션 노드를 일괄 종료..."
    clean_all_fms
    kill 0 2>/dev/null
    echo "[종료 완료]"
}
trap cleanup SIGINT SIGTERM EXIT

# 1. ROS 2 환경 및 도메인 ID 통일 (ros_bridge.py 기준 22번)
source /opt/ros/humble/setup.bash
if [ -f "$ROS_WS_DIR/install/setup.bash" ]; then
    source "$ROS_WS_DIR/install/setup.bash"
fi
export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-22}
export FMS_ROS=1
export PYTHONPATH="/opt/ros/humble/hbox/lib/python3.10/site-packages:/opt/ros/humble/lib/python3.10/site-packages:/opt/ros/humble/local/lib/python3.10/dist-packages:$PYTHONPATH"
echo " -> 적용된 ROS_DOMAIN_ID: $ROS_DOMAIN_ID | FMS_ROS: $FMS_ROS"

# 2. 터틀봇 카메라 스트리밍용 web_video_server 백그라운드 실행
echo "[1/4] 터틀봇 영상 스트리밍 서버(web_video_server) 가동..."
ros2 run web_video_server web_video_server > "$WORKSPACE_DIR/video_server.log" 2>&1 &

# 3. Flask UI 웹서버 백그라운드 실행 (FMS_ROS=1 필수 전달!)
echo "[2/4] Flask 웹 UI 서버 백그라운드 가동..."
if [ -d "$WORKSPACE_DIR/fms_ui" ]; then
    (cd "$WORKSPACE_DIR/fms_ui" && FMS_ROS=1 ROS_DOMAIN_ID=$ROS_DOMAIN_ID python3 -m flask --app app run --host 0.0.0.0 --port 5000 --no-reload > "$WORKSPACE_DIR/flask_server.log" 2>&1) &
    echo "  -> Flask 가동 완료 (http://localhost:5000 | 로그: flask_server.log)"
fi

# 4. ROS 2 A* 미션 플래너 + AMCL + RViz 새 창 실행
echo "[3/4] ROS 2 네비게이션 및 A* 미션 노드 별도 창으로 가동..."
gnome-terminal --title="ROS2_AStar_Nav_Logs" -- bash -c "source /opt/ros/humble/setup.bash; [ -f '$ROS_WS_DIR/install/setup.bash' ] && source '$ROS_WS_DIR/install/setup.bash'; export ROS_DOMAIN_ID=$ROS_DOMAIN_ID; ros2 launch my_bot_cpp astar_mission_dwa.launch.py; exec bash" &

sleep 3

# 5. 현재 창에서 메인 관제(main.py) 실행
echo "[4/4] 통합 관제 메인 컨트롤러(main.py) 가동..."
cd "$WORKSPACE_DIR/fms_manager"
python3 main.py