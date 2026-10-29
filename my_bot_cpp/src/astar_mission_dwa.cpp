#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <nav_msgs/msg/path.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <map>
#include <memory>
#include <queue>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

using namespace std::chrono_literals;

enum class RobotState {
    IDLE_WAIT,          // 대기 장소에서 호출 대기
    MOVING_TO_INSPECT,  // 검사대로 이동 중
    WAIT_LOADING,       // 검사대에서 적재 및 판정(PASS/FAIL) 대기
    MOVING_TO_DEST,     // 판정된 목적지로 이동 중
    WAIT_UNLOADING,     // 목적지에서 하역 완료 대기
    RETURNING_HOME      // 대기 장소로 복귀 중
};

struct AStarNode {
    int y, x;
    double g, h, f;
    bool operator>(const AStarNode& other) const { return f > other.f; }
};

class PcMissionPlanner : public rclcpp::Node {
public:
    PcMissionPlanner() : Node("astar_mission_dwa") {
        // 코스트맵 파라미터
        inflate_radius_  = this->declare_parameter<double>("inflate_radius", 9.0);    // 부풀리기 전체 반경(칸)
        hard_radius_     = this->declare_parameter<double>("hard_radius", 4.5);       // 100(절대 금지) 반경(칸)
        dyn_hard_radius_ = this->declare_parameter<double>("dyn_hard_radius", 4.5);   // 가벽 점 하나의 100 반경(칸)
        dyn_soft_radius_ = this->declare_parameter<double>("dyn_soft_radius", 7.0);   // 가벽 점 하나의 80 반경(칸)
        start_clear_     = static_cast<int>(this->declare_parameter<int64_t>("start_clear_cells", 6));
        goal_clear_      = static_cast<int>(this->declare_parameter<int64_t>("goal_clear_cells", 3));
        simplify_path_   = this->declare_parameter<bool>("simplify_path", false);
        if (inflate_radius_ <= hard_radius_) inflate_radius_ = hard_radius_ + 1.0;

        // 장애물 감지(레이저) 파라미터
        obstacle_detect_   = this->declare_parameter<bool>("obstacle_detect", true);          // 레이저 감시 켜기/끄기
        check_ahead_       = this->declare_parameter<double>("check_ahead", 1.2);             // 경로 앞 몇 m까지 감시할지
        corridor_          = this->declare_parameter<double>("corridor_half_width", 0.25);    // 경로 좌우 감시 폭(m)
        scan_use_range_    = this->declare_parameter<double>("scan_use_range", 2.0);          // 이 거리 안의 레이저만 사용(m)
        scan_min_range_    = this->declare_parameter<double>("scan_min_range", 0.18);         // 이보다 가까운 점은 무시(m)
        register_band_     = this->declare_parameter<double>("register_band", 0.8);           // 경로에서 이 거리 안의 점만 가벽으로 등록(m)
        wall_ignore_cells_ = this->declare_parameter<double>("wall_ignore_cells", 4.0);       // 지도 벽에서 이 칸 이내 점은 벽으로 간주
        min_block_hits_    = static_cast<int>(this->declare_parameter<int64_t>("min_block_hits", 4));   // 경로 위 최소 점 개수
        confirm_scans_     = static_cast<int>(this->declare_parameter<int64_t>("confirm_scans", 3));    // 연속 확인 횟수
        replan_cooldown_   = this->declare_parameter<double>("replan_cooldown", 2.0);         // 재탐색 후 쉬는 시간(초)

        // TF: 레이저 센서의 map 기준 위치를 얻기 위해 사용
        tf_buffer_   = std::make_unique<tf2_ros::Buffer>(this->get_clock());
        tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

        // 1. 주요 거점 좌표 설정
        waypoints_["HOME"]    = {0.035, -0.020};
        waypoints_["INSPECT"] = {2.500, 0.070};
        waypoints_["PASS"]    = {3.200, 2.000};
        waypoints_["FAIL"]    = {-0.100, 1.800};

        last_replan_time_ = this->get_clock()->now() - rclcpp::Duration::from_seconds(100.0);

        // 2. 퍼블리셔 설정
        pub_path_  = this->create_publisher<nav_msgs::msg::Path>("/planned_path", 10);
        pub_state_ = this->create_publisher<std_msgs::msg::String>("/robot_state", 10);
        pub_event_ = this->create_publisher<std_msgs::msg::String>("/mission_event", 10);
        pub_costmap_ = this->create_publisher<nav_msgs::msg::OccupancyGrid>(
            "/custom_costmap", rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable());

        auto map_qos = rclcpp::QoS(rclcpp::KeepLast(1)).transient_local().reliable();

        sub_map_ = this->create_subscription<nav_msgs::msg::OccupancyGrid>(
            "/map", map_qos, std::bind(&PcMissionPlanner::mapCallback, this, std::placeholders::_1));
        sub_pose_ = this->create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
            "/amcl_pose", 10, std::bind(&PcMissionPlanner::poseCallback, this, std::placeholders::_1));
        sub_goal_ = this->create_subscription<geometry_msgs::msg::PoseStamped>(
            "/goal_pose", 10, std::bind(&PcMissionPlanner::rvizGoalCallback, this, std::placeholders::_1));
        sub_scan_ = this->create_subscription<sensor_msgs::msg::LaserScan>(
            "/scan", rclcpp::SensorDataQoS(), std::bind(&PcMissionPlanner::scanCallback, this, std::placeholders::_1));

        // 관제 UI(또는 터미널) 명령 수신
        sub_cmd_ = this->create_subscription<std_msgs::msg::String>(
            "/task_command", 10, std::bind(&PcMissionPlanner::commandCallback, this, std::placeholders::_1));

        // 터틀봇(DWA 노드)으로부터 도착 또는 길 막힘 보고 수신
        sub_bot_report_ = this->create_subscription<std_msgs::msg::String>(
            "/bot_report", 10, std::bind(&PcMissionPlanner::botReportCallback, this, std::placeholders::_1));

        timer_ = this->create_wall_timer(500ms, std::bind(&PcMissionPlanner::publishCurrentState, this));

        RCLCPP_INFO(this->get_logger(),
            "=== [PC] Global A* & Mission Manager Started (hard=%.1f, inflate=%.1f cells, scan-replan %s) ===",
            hard_radius_, inflate_radius_, obstacle_detect_ ? "ON" : "OFF");
    }

private:
    RobotState state_ = RobotState::IDLE_WAIT;
    std::string pending_result_ = "";
    std::map<std::string, std::pair<double, double>> waypoints_;
    std::pair<double, double> current_goal_ = {0.0, 0.0};

    // 코스트맵 파라미터
    double inflate_radius_ = 9.0, hard_radius_ = 4.5;
    double dyn_hard_radius_ = 4.5, dyn_soft_radius_ = 7.0;
    int start_clear_ = 6, goal_clear_ = 3;
    bool simplify_path_ = false;

    // 장애물 감지 파라미터
    bool obstacle_detect_ = true;
    double check_ahead_ = 1.2, corridor_ = 0.25;
    double scan_use_range_ = 2.0, scan_min_range_ = 0.18, register_band_ = 0.8;
    double wall_ignore_cells_ = 4.0, replan_cooldown_ = 2.0;
    int min_block_hits_ = 4, confirm_scans_ = 3;

    double current_x_ = 0.0, current_y_ = 0.0;
    bool is_localized_ = false;

    std::vector<int8_t> static_costmap_;
    std::vector<uint8_t> wall_mask_;        // 진짜 벽/미확인 칸 (비우기 대상에서 제외)
    std::vector<float> wall_dist_;          // 각 칸에서 가장 가까운 벽까지 거리(칸 단위)
    std::vector<int8_t> dynamic_obstacles_; // 임시 장애물(가벽)
    int map_width_ = 0, map_height_ = 0;
    double map_res_ = 0.05, origin_x_ = 0.0, origin_y_ = 0.0;
    bool map_received_ = false;

    std::vector<std::pair<double, double>> path_pts_;  // 마지막으로 보낸 경로(월드 좌표)
    int block_count_ = 0;                              // 경로 막힘이 연속으로 확인된 횟수
    bool replan_failed_ = false;                       // 재탐색에 실패해 정지 중인지
    rclcpp::Time last_replan_time_{0, 0, RCL_ROS_TIME};

    std::unique_ptr<tf2_ros::Buffer> tf_buffer_;
    std::shared_ptr<tf2_ros::TransformListener> tf_listener_;

    rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr pub_path_;
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_state_;
    rclcpp::Publisher<std_msgs::msg::String>::SharedPtr pub_event_;
    rclcpp::Publisher<nav_msgs::msg::OccupancyGrid>::SharedPtr pub_costmap_;
    rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr sub_map_;
    rclcpp::Subscription<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr sub_pose_;
    rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr sub_goal_;
    rclcpp::Subscription<sensor_msgs::msg::LaserScan>::SharedPtr sub_scan_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_cmd_;
    rclcpp::Subscription<std_msgs::msg::String>::SharedPtr sub_bot_report_;
    rclcpp::TimerBase::SharedPtr timer_;

    // ---------- 좌표 변환 / 유틸 ----------
    int toCellX(double wx) const { return static_cast<int>(std::floor((wx - origin_x_) / map_res_)); }
    int toCellY(double wy) const { return static_cast<int>(std::floor((wy - origin_y_) / map_res_)); }
    double cellToWorldX(int cx) const { return origin_x_ + (cx + 0.5) * map_res_; }
    double cellToWorldY(int cy) const { return origin_y_ + (cy + 0.5) * map_res_; }
    bool inMap(int x, int y) const { return x >= 0 && x < map_width_ && y >= 0 && y < map_height_; }

    bool isMoving() const {
        return state_ == RobotState::MOVING_TO_INSPECT ||
               state_ == RobotState::MOVING_TO_DEST ||
               state_ == RobotState::RETURNING_HOME;
    }

    void publishEvent(const std::string& text) {
        std_msgs::msg::String m;
        m.data = text;
        pub_event_->publish(m);
    }

    int8_t costFromDist(double d) const {
        if (d <= hard_radius_) return 100;
        double t = (d - hard_radius_) / (inflate_radius_ - hard_radius_);
        double c = 80.0 * (1.0 - t);
        if (c < 0.0) c = 0.0;
        return static_cast<int8_t>(c);
    }

    // --- [1] 맵 수신 및 코스트맵 생성 (8방향 거리 변환: 벽에서 가까울수록 100, 멀수록 80~0) ---
    void mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg) {
        map_res_ = msg->info.resolution;
        map_width_ = msg->info.width;
        map_height_ = msg->info.height;
        origin_x_ = msg->info.origin.position.x;
        origin_y_ = msg->info.origin.position.y;

        const int total_cells = map_width_ * map_height_;
        static_costmap_.assign(total_cells, 0);
        wall_mask_.assign(total_cells, 0);
        dynamic_obstacles_.assign(total_cells, 0);

        std::vector<double> dist_map(total_cells, 1e9);
        using QItem = std::pair<double, int>;
        std::priority_queue<QItem, std::vector<QItem>, std::greater<QItem>> pq;

        // 진짜 벽(>50) 또는 미확인(-1) 칸을 시작점으로
        for (int i = 0; i < total_cells; ++i) {
            if (msg->data[i] > 50 || msg->data[i] == -1) {
                dist_map[i] = 0.0;
                static_costmap_[i] = 100;
                wall_mask_[i] = 1;
                pq.push({0.0, i});
            }
        }

        const int dy[8] = {0, 0, 1, -1, 1, 1, -1, -1};
        const int dx[8] = {1, -1, 0, 0, 1, -1, 1, -1};
        const double step[8] = {1.0, 1.0, 1.0, 1.0, 1.414, 1.414, 1.414, 1.414};

        while (!pq.empty()) {
            QItem top = pq.top();
            pq.pop();
            double d = top.first;
            int cur = top.second;
            if (d > dist_map[cur]) continue;       // 오래된 항목
            if (d >= inflate_radius_) continue;    // 부풀리기 반경 도달

            int cy = cur / map_width_;
            int cx = cur % map_width_;
            for (int k = 0; k < 8; ++k) {
                int ny = cy + dy[k], nx = cx + dx[k];
                if (!inMap(nx, ny)) continue;
                int ni = ny * map_width_ + nx;
                double nd = d + step[k];
                if (nd < dist_map[ni]) {
                    dist_map[ni] = nd;
                    if (nd <= inflate_radius_) {
                        if (!wall_mask_[ni]) static_costmap_[ni] = costFromDist(nd);
                        pq.push({nd, ni});
                    }
                }
            }
        }

        // 레이저 점이 지도의 벽인지 장애물인지 구분하기 위해 벽까지 거리를 저장
        wall_dist_.assign(total_cells, 1e9f);
        for (int i = 0; i < total_cells; ++i) wall_dist_[i] = static_cast<float>(dist_map[i]);

        map_received_ = true;
        publishCostmapViz();
        RCLCPP_INFO(this->get_logger(), "[MAP] %d x %d, res %.3f", map_width_, map_height_, map_res_);
    }

    // --- [2] 관제 UI / 터미널 명령어 처리 ---
    void commandCallback(const std_msgs::msg::String::SharedPtr msg) {
        std::string cmd = msg->data;
        RCLCPP_INFO(this->get_logger(), "[UI CMD] '%s'", cmd.c_str());

        if (cmd == "CALL") {
            if (state_ != RobotState::IDLE_WAIT) {
                RCLCPP_WARN(this->get_logger(), "[CALL] ignored: robot is not IDLE_WAIT");
                return;
            }
            replan_failed_ = false;
            block_count_ = 0;
            clearDynamicObstacles(); // 새 미션 시 임시 장애물 초기화
            if (planPathTo(waypoints_["INSPECT"].first, waypoints_["INSPECT"].second)) {
                state_ = RobotState::MOVING_TO_INSPECT;
            } else {
                publishEvent("NO_PATH:INSPECT");
            }
        }
        else if (cmd == "PASS" || cmd == "FAIL") {
            pending_result_ = cmd;
        }
        else if (cmd == "LOAD_DONE" || cmd == "LOAD_PASS" || cmd == "LOAD_FAIL") {
            if (state_ != RobotState::WAIT_LOADING) {
                RCLCPP_WARN(this->get_logger(), "[%s] ignored: robot is not WAIT_LOADING", cmd.c_str());
                return;
            }
            if (cmd == "LOAD_PASS") pending_result_ = "PASS";
            if (cmd == "LOAD_FAIL") pending_result_ = "FAIL";
            if (pending_result_ != "PASS" && pending_result_ != "FAIL") {
                RCLCPP_WARN(this->get_logger(), "[LOAD] no PASS/FAIL result yet");
                return;
            }
            replan_failed_ = false;
            block_count_ = 0;
            auto target = waypoints_[pending_result_];
            if (planPathTo(target.first, target.second)) {
                state_ = RobotState::MOVING_TO_DEST;
            } else {
                publishEvent("NO_PATH:" + pending_result_);
            }
        }
        else if (cmd == "UNLOAD_DONE") {
            if (state_ != RobotState::WAIT_UNLOADING) {
                RCLCPP_WARN(this->get_logger(), "[UNLOAD_DONE] ignored: robot is not WAIT_UNLOADING");
                return;
            }
            replan_failed_ = false;
            block_count_ = 0;
            if (planPathTo(waypoints_["HOME"].first, waypoints_["HOME"].second)) {
                state_ = RobotState::RETURNING_HOME;
                pending_result_ = "";
            } else {
                publishEvent("NO_PATH:HOME");
            }
        }
        else if (cmd == "RETRY") {
            // 길이 막혀 정지한 뒤, 장애물을 치우고 같은 목적지로 다시 출발
            if (!isMoving() || !replan_failed_) {
                RCLCPP_WARN(this->get_logger(), "[RETRY] ignored: nothing to retry");
                return;
            }
            clearDynamicObstacles();
            replanAroundObstacle("retry");
        }
        else if (cmd == "RESET") {
            sendEmptyPath(); // 터틀봇 정지 지시
            clearDynamicObstacles();
            pending_result_ = "";
            replan_failed_ = false;
            block_count_ = 0;
            state_ = RobotState::IDLE_WAIT;
        }
    }

    // --- [3] 터틀봇 보고 수신 (도착 완료 or 길 막힘) ---
    void botReportCallback(const std_msgs::msg::String::SharedPtr msg) {
        std::string data = msg->data;

        if (data == "ARRIVED") {
            if (state_ == RobotState::MOVING_TO_INSPECT) {
                state_ = RobotState::WAIT_LOADING;
                clearDynamicObstacles();
                RCLCPP_INFO(this->get_logger(), "[ARRIVED] Inspection Desk. Waiting UI Judgment...");
            } else if (state_ == RobotState::MOVING_TO_DEST) {
                state_ = RobotState::WAIT_UNLOADING;
                clearDynamicObstacles();
                RCLCPP_INFO(this->get_logger(), "[ARRIVED] Destination. Waiting Unload...");
            } else if (state_ == RobotState::RETURNING_HOME) {
                state_ = RobotState::IDLE_WAIT;
                clearDynamicObstacles();
                RCLCPP_INFO(this->get_logger(), "[ARRIVED] Home Base. IDLE_WAIT.");
            }
            block_count_ = 0;
        }
        // 터틀봇 DWA가 못 피하는 장애물을 만나 "BLOCKED:x,y;x,y;..."를 보낸 경우
        else if (data.rfind("BLOCKED:", 0) == 0) {
            if (!isMoving()) {
                RCLCPP_WARN(this->get_logger(), "[BLOCKED] ignored: robot is not moving");
                return;
            }

            std::string pts_str = data.substr(8);
            std::stringstream ss(pts_str);
            std::string pt_token;
            int registered_cnt = 0;

            // 세미콜론(;) 단위로 쪼개서 모든 스캔 포인트를 맵에 등록
            while (std::getline(ss, pt_token, ';')) {
                if (pt_token.empty()) continue;
                std::stringstream pt_ss(pt_token);
                double obs_x, obs_y;
                char comma;
                if ((pt_ss >> obs_x >> comma >> obs_y) && comma == ',') {
                    registerDynamicObstacle(obs_x, obs_y);
                    registered_cnt++;
                }
            }

            if (registered_cnt > 0) {
                RCLCPP_WARN(this->get_logger(),
                    "[REPLAN] Registered %d scan points as Wall! Re-running A*!", registered_cnt);
                publishCostmapViz();
                replanAroundObstacle("bot_report");
            }
        }
    }

    // --- [3-2] 레이저를 직접 보고 경로 앞 장애물을 감지 ---
    void scanCallback(const sensor_msgs::msg::LaserScan::SharedPtr msg) {
        if (!obstacle_detect_ || !map_received_ || !is_localized_) return;
        if (!isMoving() || replan_failed_ || path_pts_.size() < 2) { block_count_ = 0; return; }
        if ((this->get_clock()->now() - last_replan_time_).seconds() < replan_cooldown_) return;

        // 1. 레이저 센서의 map 기준 위치/방향 (TF 사용: /amcl_pose보다 최신)
        geometry_msgs::msg::TransformStamped tfm;
        try {
            tfm = tf_buffer_->lookupTransform("map", msg->header.frame_id, tf2::TimePointZero);
        } catch (const tf2::TransformException&) {
            return;  // TF가 아직 없으면 이번 스캔은 건너뜀
        }
        const double sx = tfm.transform.translation.x;
        const double sy = tfm.transform.translation.y;
        const auto& q = tfm.transform.rotation;
        const double syaw = std::atan2(2.0 * (q.w * q.z + q.x * q.y),
                                       1.0 - 2.0 * (q.y * q.y + q.z * q.z));

        // 2. 로봇 앞쪽 check_ahead 미터 구간의 경로
        size_t nearest = 0;
        double best = 1e18;
        for (size_t i = 0; i < path_pts_.size(); ++i) {
            double d = std::hypot(path_pts_[i].first - sx, path_pts_[i].second - sy);
            if (d < best) { best = d; nearest = i; }
        }
        std::vector<std::pair<double, double>> ahead;
        double acc = 0.0;
        for (size_t i = nearest; i < path_pts_.size(); ++i) {
            if (i > nearest) {
                acc += std::hypot(path_pts_[i].first - path_pts_[i - 1].first,
                                  path_pts_[i].second - path_pts_[i - 1].second);
            }
            if (acc > check_ahead_) break;
            ahead.push_back(path_pts_[i]);
        }
        if (ahead.empty()) return;

        // 3. 레이저 점을 지도에 찍고, 지도에 없는 장애물만 골라냄
        const double min_r = std::max(static_cast<double>(msg->range_min), scan_min_range_);
        std::vector<std::pair<double, double>> near_hits;  // 경로 주변의 장애물 점 (등록 대상)
        int corridor_hits = 0;                             // 그중 경로 위(corridor_ 이내)에 있는 점
        for (size_t i = 0; i < msg->ranges.size(); ++i) {
            double r = msg->ranges[i];
            if (!std::isfinite(r) || r < min_r || r > scan_use_range_) continue;
            double a = msg->angle_min + static_cast<double>(i) * msg->angle_increment + syaw;
            double wx = sx + r * std::cos(a);
            double wy = sy + r * std::sin(a);
            int gx = toCellX(wx), gy = toCellY(wy);
            if (!inMap(gx, gy)) continue;
            int idx = gy * map_width_ + gx;
            if (wall_dist_[idx] <= wall_ignore_cells_) continue;  // 지도의 벽(또는 미확인) 근처는 벽으로 간주
            if (dynamic_obstacles_[idx] >= 100) continue;         // 이미 등록한 장애물

            double dmin = 1e18;
            for (const auto& p : ahead) dmin = std::min(dmin, std::hypot(p.first - wx, p.second - wy));
            if (dmin <= corridor_) ++corridor_hits;
            if (dmin <= register_band_) near_hits.push_back({wx, wy});
        }

        if (corridor_hits >= min_block_hits_) ++block_count_;
        else block_count_ = 0;
        if (block_count_ < confirm_scans_) return;
        block_count_ = 0;

        RCLCPP_WARN(this->get_logger(),
            "[OBSTACLE] %d scan points block the path ahead. Registering %zu points and replanning...",
            corridor_hits, near_hits.size());
        for (const auto& h : near_hits) registerDynamicObstacle(h.first, h.second);
        publishCostmapViz();
        replanAroundObstacle("scan");
    }

    // 현재 위치에서 같은 목적지로 A*를 다시 돌려 새 경로를 보냄. 실패하면 정지.
    void replanAroundObstacle(const std::string& why) {
        last_replan_time_ = this->get_clock()->now();
        if (planPathTo(current_goal_.first, current_goal_.second)) {
            replan_failed_ = false;
            RCLCPP_INFO(this->get_logger(), "[REPLAN OK] new path sent (%s)", why.c_str());
            publishEvent("REPLANNED:" + why);
        } else {
            sendEmptyPath(); // 길이 없으면 터틀봇 정지
            replan_failed_ = true;
            RCLCPP_ERROR(this->get_logger(),
                "[REPLAN FAIL] no path, robot stopped. Remove the obstacle and send RETRY, or send RESET.");
            publishEvent("NO_PATH:REPLAN");
        }
    }

    // 가벽 점 하나 등록: 기존 값보다 큰 값만 남김 (앞 점의 100을 뒤 점의 80이 덮어쓰지 않도록)
    void registerDynamicObstacle(double wx, double wy) {
        int gx = toCellX(wx);
        int gy = toCellY(wy);
        int r = static_cast<int>(std::ceil(dyn_soft_radius_));

        for (int dy = -r; dy <= r; ++dy) {
            for (int dx = -r; dx <= r; ++dx) {
                int ny = gy + dy, nx = gx + dx;
                if (!inMap(nx, ny)) continue;
                double dist = std::hypot(dx, dy);
                int8_t v = 0;
                if (dist <= dyn_hard_radius_) v = 100;
                else if (dist <= dyn_soft_radius_) v = 80;
                if (v == 0) continue;
                int idx = ny * map_width_ + nx;
                if (dynamic_obstacles_[idx] < v) dynamic_obstacles_[idx] = v;
            }
        }
    }

    void clearDynamicObstacles() {
        if (!map_received_) return;
        dynamic_obstacles_.assign(map_width_ * map_height_, 0);
        publishCostmapViz();
    }

    // 직선 경로가 통과 가능한지 검사 (경로 단순화용)
    bool lineFree(const std::vector<int8_t>& m, int x0, int y0, int x1, int y1, int max_cost) const {
        double dx = x1 - x0, dy = y1 - y0;
        int steps = std::max(1, static_cast<int>(std::ceil(std::hypot(dx, dy) * 2.0)));
        for (int s = 0; s <= steps; ++s) {
            double t = static_cast<double>(s) / steps;
            int cx = static_cast<int>(std::lround(x0 + dx * t));
            int cy = static_cast<int>(std::lround(y0 + dy * t));
            if (!inMap(cx, cy)) return false;
            if (m[cy * map_width_ + cx] > max_cost) return false;
        }
        return true;
    }

    std::vector<std::pair<int, int>> simplifyCells(
        const std::vector<int8_t>& m, const std::vector<std::pair<int, int>>& c) const {
        if (c.size() < 3) return c;
        std::vector<std::pair<int, int>> out;
        out.push_back(c.front());
        size_t anchor = 0;
        while (anchor < c.size() - 1) {
            size_t far = anchor + 1;
            for (size_t j = c.size() - 1; j > anchor + 1; --j) {
                if (lineFree(m, c[anchor].first, c[anchor].second, c[j].first, c[j].second, 30)) {
                    far = j;
                    break;
                }
            }
            out.push_back(c[far]);
            anchor = far;
        }
        return out;
    }

    // --- [4] 가중치 A* 알고리즘 (100은 회피, 80 이하는 페널티 부여 후 통과 가능) ---
    bool planPathTo(double goal_x, double goal_y) {
        if (!map_received_) {
            RCLCPP_WARN(this->get_logger(), "[A*] map not received yet");
            return false;
        }
        if (!is_localized_) {
            RCLCPP_WARN(this->get_logger(), "[A*] robot not localized yet (/amcl_pose)");
            return false;
        }
        current_goal_ = {goal_x, goal_y};

        int start_x = toCellX(current_x_);
        int start_y = toCellY(current_y_);
        int end_x   = toCellX(goal_x);
        int end_y   = toCellY(goal_y);

        if (!inMap(start_x, start_y) || !inMap(end_x, end_y)) {
            RCLCPP_ERROR(this->get_logger(), "[A* FAIL] start or goal is outside the map");
            return false;
        }

        std::vector<int8_t> work_map = static_costmap_;
        for (size_t i = 0; i < work_map.size(); ++i) {
            if (dynamic_obstacles_[i] > work_map[i]) work_map[i] = dynamic_obstacles_[i];
        }

        // 시작/목표 주변의 부풀린 영역과 가벽은 비움 (진짜 벽과 미확인 칸은 그대로)
        auto clearAround = [&](int cx, int cy, int r) {
            for (int dy = -r; dy <= r; ++dy)
                for (int dx = -r; dx <= r; ++dx) {
                    int ny = cy + dy, nx = cx + dx;
                    if (!inMap(nx, ny)) continue;
                    int idx = ny * map_width_ + nx;
                    if (!wall_mask_[idx]) work_map[idx] = 0;
                }
        };
        clearAround(start_x, start_y, start_clear_);
        clearAround(end_x, end_y, goal_clear_);

        int start_idx = start_y * map_width_ + start_x;
        int end_idx   = end_y * map_width_ + end_x;

        if (wall_mask_[end_idx]) {
            RCLCPP_ERROR(this->get_logger(),
                "[A* FAIL] goal (%.2f, %.2f) is on a wall/unknown cell. Change the waypoint.", goal_x, goal_y);
            return false;
        }

        std::priority_queue<AStarNode, std::vector<AStarNode>, std::greater<AStarNode>> open_list;
        std::vector<double> g_score(map_width_ * map_height_, 1e9);
        std::vector<int> parent(map_width_ * map_height_, -1);
        std::vector<bool> closed(map_width_ * map_height_, false);

        g_score[start_idx] = 0.0;
        open_list.push({start_y, start_x, 0.0, 0.0, std::hypot(end_x - start_x, end_y - start_y)});

        const int dy[8] = {0, 0, 1, -1, 1, 1, -1, -1};
        const int dx[8] = {1, -1, 0, 0, 1, -1, 1, -1};
        const double step_cost[8] = {1.0, 1.0, 1.0, 1.0, 1.414, 1.414, 1.414, 1.414};

        bool found = false;
        while (!open_list.empty()) {
            AStarNode curr = open_list.top();
            open_list.pop();

            int curr_idx = curr.y * map_width_ + curr.x;
            if (closed[curr_idx]) continue;
            closed[curr_idx] = true;

            if (curr_idx == end_idx) { found = true; break; }

            for (int i = 0; i < 8; ++i) {
                int ny = curr.y + dy[i], nx = curr.x + dx[i];
                if (!inMap(nx, ny)) continue;

                int n_idx = ny * map_width_ + nx;
                // 100(절대 벽)만 막고, 80 이하(부풀린 영역)는 페널티를 주며 통과 허용
                if (work_map[n_idx] >= 100 || closed[n_idx]) continue;

                // 대각선 이동 시 양옆 칸이 막혀 있으면 모서리를 파고들지 못하게 막음
                if (i >= 4) {
                    if (work_map[curr.y * map_width_ + nx] >= 100 ||
                        work_map[ny * map_width_ + curr.x] >= 100) continue;
                }

                double penalty = work_map[n_idx] * 0.15; // 코스트가 80이면 +12점의 페널티
                double new_g = curr.g + step_cost[i] + penalty;

                if (new_g < g_score[n_idx]) {
                    g_score[n_idx] = new_g;
                    parent[n_idx] = curr_idx;
                    double h = std::hypot(end_x - nx, end_y - ny);
                    open_list.push({ny, nx, new_g, h, new_g + h});
                }
            }
        }

        if (!found) {
            RCLCPP_ERROR(this->get_logger(), "[A* FAIL] Path completely blocked!");
            return false;
        }

        // 경로 복원 (셀 단위)
        std::vector<std::pair<int, int>> cells;
        for (int t = end_idx; t != -1; t = parent[t]) {
            cells.push_back({t % map_width_, t / map_width_});
        }
        std::reverse(cells.begin(), cells.end());

        // 월드 좌표로 변환 (옵션: 직선 단순화 후 칸 간격으로 다시 채움)
        std::vector<std::pair<double, double>> pts;
        if (simplify_path_) {
            auto simp = simplifyCells(work_map, cells);
            for (size_t s = 0; s + 1 < simp.size(); ++s) {
                double x0 = cellToWorldX(simp[s].first),     y0 = cellToWorldY(simp[s].second);
                double x1 = cellToWorldX(simp[s + 1].first), y1 = cellToWorldY(simp[s + 1].second);
                int n = std::max(1, static_cast<int>(std::ceil(std::hypot(x1 - x0, y1 - y0) / map_res_)));
                for (int k = 0; k < n; ++k) {
                    double t = static_cast<double>(k) / n;
                    pts.push_back({x0 + (x1 - x0) * t, y0 + (y1 - y0) * t});
                }
            }
            pts.push_back({cellToWorldX(simp.back().first), cellToWorldY(simp.back().second)});
        } else {
            for (auto& c : cells) pts.push_back({cellToWorldX(c.first), cellToWorldY(c.second)});
        }

        nav_msgs::msg::Path path_msg;
        path_msg.header.frame_id = "map";
        path_msg.header.stamp = this->get_clock()->now();

        double last_yaw = 0.0;
        for (size_t i = 0; i < pts.size(); ++i) {
            geometry_msgs::msg::PoseStamped pose;
            pose.header = path_msg.header;
            pose.pose.position.x = pts[i].first;
            pose.pose.position.y = pts[i].second;
            double yaw = last_yaw;
            if (i + 1 < pts.size()) {
                yaw = std::atan2(pts[i + 1].second - pts[i].second, pts[i + 1].first - pts[i].first);
            }
            last_yaw = yaw;
            pose.pose.orientation.z = std::sin(yaw / 2.0);
            pose.pose.orientation.w = std::cos(yaw / 2.0);
            path_msg.poses.push_back(pose);
        }
        path_pts_ = pts;  // 레이저 감시가 이 경로를 기준으로 앞쪽을 살핌
        pub_path_->publish(path_msg);
        RCLCPP_INFO(this->get_logger(), "[A* SUCCESS] Sent %zu waypoints to TurtleBot!", path_msg.poses.size());
        return true;
    }

    void poseCallback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg) {
        current_x_ = msg->pose.pose.position.x;
        current_y_ = msg->pose.pose.position.y;
        is_localized_ = true;
    }

    void rvizGoalCallback(const geometry_msgs::msg::PoseStamped::SharedPtr msg) {
        planPathTo(msg->pose.position.x, msg->pose.position.y);
    }

    void sendEmptyPath() {
        nav_msgs::msg::Path empty_msg;
        empty_msg.header.frame_id = "map";
        empty_msg.header.stamp = this->get_clock()->now();
        pub_path_->publish(empty_msg);
        path_pts_.clear();
    }

    void publishCostmapViz() {
        if (!map_received_) return;
        nav_msgs::msg::OccupancyGrid grid;
        grid.header.frame_id = "map";
        grid.header.stamp = this->get_clock()->now();
        grid.info.resolution = map_res_;
        grid.info.width = map_width_;
        grid.info.height = map_height_;
        grid.info.origin.position.x = origin_x_;
        grid.info.origin.position.y = origin_y_;
        grid.info.origin.orientation.w = 1.0;
        grid.data = static_costmap_;
        for (size_t i = 0; i < grid.data.size(); ++i) {
            if (dynamic_obstacles_[i] > grid.data[i]) grid.data[i] = dynamic_obstacles_[i];
        }
        pub_costmap_->publish(grid);
    }

    void publishCurrentState() {
        std_msgs::msg::String msg;
        switch (state_) {
            case RobotState::IDLE_WAIT:         msg.data = "IDLE_WAIT"; break;
            case RobotState::MOVING_TO_INSPECT: msg.data = "MOVING_TO_INSPECT"; break;
            case RobotState::WAIT_LOADING:      msg.data = "WAIT_LOADING"; break;
            case RobotState::MOVING_TO_DEST:    msg.data = "MOVING_TO_DEST"; break;
            case RobotState::WAIT_UNLOADING:    msg.data = "WAIT_UNLOADING"; break;
            case RobotState::RETURNING_HOME:    msg.data = "RETURNING_HOME"; break;
        }
        pub_state_->publish(msg);
    }
};

int main(int argc, char **argv) {
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<PcMissionPlanner>());
    rclcpp::shutdown();
    return 0;
}