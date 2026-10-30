#!/bin/bash

# 작업 경로를 스크립트가 있는 현재 최상위 폴더로 고정
WORKSPACE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WORKSPACE_DIR"

echo "=========================================================="
echo " [FMS 관제 PC] 원클릭 통합 시스템 실행기"
echo " 작업 경로: $WORKSPACE_DIR"
echo "=========================================================="

# 터미널을 종료하거나 Ctrl+C를 누르면 백그라운드 프로세스들을 깔끔하게 함께 종료
trap 'echo -e "\n[종료] 모든 관제 시스템 프로세스를 안전하게 종료합니다..."; kill 0' SIGINT SIGTERM EXIT

# 1. ROS 2 환경 로드 (본인 환경 워크스페이스에 맞게 설정되어 있다고 가정)
source /opt/ros/humble/setup.bash 2>/dev/null
if [ -f "install/setup.bash" ]; then
    source install/setup.bash
fi

# 2. Flask UI 웹서버 백그라운드 실행
echo "[1/3] Flask 웹 UI 서버 백그라운드 가동..."
if [ -d "$WORKSPACE_DIR/fms_ui" ]; then
    (cd "$WORKSPACE_DIR/fms_ui" && python3 -m flask --app app run --host 0.0.0.0 --port 5000 --no-reload > "$WORKSPACE_DIR/flask_server.log" 2>&1) &
    echo "  -> Flask 가동 완료 (http://localhost:5000 | 로그: flask_server.log)"
else
    echo "  -> [경고] fms_ui 폴더를 찾을 수 없습니다."
fi

# 3. ROS 2 A* 미션 플래너 + AMCL + RViz + Web Video Server 실행
# (로그가 섞이지 않도록 새 터미널 창을 팝업으로 띄움)
echo "[2/3] ROS 2 네비게이션 및 A* 미션 노드 별도 창으로 가동..."
gnome-terminal --title="ROS2_AStar_Nav_Logs" -- bash -c "source /opt/ros/humble/setup.bash; [ -f install/setup.bash ] && source install/setup.bash; ros2 launch my_bot_cpp astar_mission_dwa.launch.py; exec bash" &

sleep 3

# 4. 현재 창에서 메인 관제(main.py) 실행 -> 키보드 입력창 역할
echo "[3/3] 통합 관제 메인 컨트롤러(main.py) 가동..."
echo "----------------------------------------------------------"
echo " [키보드 명령 단축키]"
echo "  - [Space] : 검사 시작 (카메라 캡처 -> DB 저장 -> 로봇 호출)"
echo "  - [L]     : 적재 완료 보고 (LOAD_PASS / LOAD_FAIL)"
echo "  - [U]     : 하역 완료 보고 (UNLOAD_DONE)"
echo "  - [R]     : 미션 비상 리셋"
echo "  - [Q]     : 전체 종료"
echo "----------------------------------------------------------"

cd "$WORKSPACE_DIR/fms_manager"
python3 main.py