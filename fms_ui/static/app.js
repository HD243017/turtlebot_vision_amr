(function () {
  var BOOT = window.BOOT;
  var app = document.getElementById('app');
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) { return String(s).replace(/[&<>"']/g, function (c) { return '&#' + c.charCodeAt(0) + ';'; }); };

  function api(method, url, body) {
    return fetch(url, {
      method: method,
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      if (r.ok) return r.json();
      return r.text().then(function (html) {
        // Flask abort(409, '이유') 의 HTML 응답에서 이유 문장만 꺼낸다
        var m = /<p>([^<]*)<\/p>/.exec(html), err = new Error('HTTP ' + r.status);
        err.status = r.status; err.reason = m ? m[1] : '';
        throw err;
      });
    });
  }

  var STATES = BOOT.states, KIND = BOOT.kinds, MISSIONS = BOOT.missions || {};

  // ---- 지도 (maps/map_test1.yaml 또는 FMS_MAP + config/zones.yaml) ----
  // 서버가 주는 좌표는 모두 지도 기준 미터(위쪽이 +y). toSvg 로 화면 좌표로 바꾼다.
  // 지도 크기와 상관없이 화면 폭을 640으로 맞춰서, 글자 · 아이콘 크기는 일정하게 둔다.
  var MAP = BOOT.map, ZONES = BOOT.zones || { zones: [], labels: [] };
  var MW = MAP ? MAP.width_m : 3.2, MH = MAP ? MAP.height_m : 2.2;
  var OX = MAP ? MAP.origin[0] : -0.1, OY = MAP ? MAP.origin[1] : -0.1;
  var VIEW_W = 640, S = VIEW_W / MW, VIEW_H = MH * S;   // S: 1 m 당 화면 단위
  function toSvg(x, y) { return [(x - OX) * S, (MH - (y - OY)) * S]; }
  function f1(n) { return n.toFixed(1); }
  function attrs(el, a) { for (var k in a) el.setAttribute(k, a[k]); }
  function zoneByMarker(m) { return ZONES.zones.filter(function (z) { return z.marker === m; })[0]; }

  function drawMap() {
    var full = { x: 0, y: 0, width: VIEW_W, height: f1(VIEW_H) };
    attrs($('mapSvg'), { viewBox: '0 0 ' + VIEW_W + ' ' + f1(VIEW_H) });
    attrs($('mapBg'), full); attrs($('mapOcc'), full); attrs($('mapMask'), full);
    if (MAP) attrs($('mapMaskImg'), Object.assign({ href: '/map/image.png' }, full));
    else { $('mapOcc').remove(); $('mapMissing').hidden = false; attrs($('mapMissing'), { x: VIEW_W / 2, y: f1(VIEW_H / 2) }); }

    // 격자: 작은 지도는 10 cm(굵은 선 50 cm), 중간은 50 cm(1 m), 큰 지도는 1 m(5 m)
    var g = MW <= 5 ? { step: 0.1, major: 0.5 } : (MW <= 15 ? { step: 0.5, major: 1 } : { step: 1, major: 5 });
    var step = g.step, every = Math.round(g.major / step), html = '', v, p, major;
    for (v = Math.ceil(OX / step) * step; v <= OX + MW + 1e-9; v += step) {
      major = Math.round(v / step) % every === 0; p = toSvg(v, 0)[0];
      html += '<line class="' + (major ? 'g-major' : 'g-minor') + '" x1="' + f1(p) + '" y1="0" x2="' + f1(p) + '" y2="' + f1(VIEW_H) + '"/>';
    }
    for (v = Math.ceil(OY / step) * step; v <= OY + MH + 1e-9; v += step) {
      major = Math.round(v / step) % every === 0; p = toSvg(0, v)[1];
      html += '<line class="' + (major ? 'g-major' : 'g-minor') + '" x1="0" y1="' + f1(p) + '" x2="' + VIEW_W + '" y2="' + f1(p) + '"/>';
    }
    $('grid').innerHTML = html;
    $('mapInfo').textContent = (MAP ? '지도 ' + MW.toFixed(1) + ' × ' + MH.toFixed(1) + ' m · ' : '') +
      '격자 ' + (step < 1 ? Math.round(step * 100) + ' cm' : step + ' m');

    // 구역 · 마커 · 이름표
    html = '';
    ZONES.zones.forEach(function (z) {
      if (z.rect) {
        var a = toSvg(z.rect[0], z.rect[3]), b = toSvg(z.rect[2], z.rect[1]);
        html += '<rect class="zone z-' + esc(z.kind) + '" x="' + f1(a[0]) + '" y="' + f1(a[1]) + '" width="' + f1(b[0] - a[0]) + '" height="' + f1(b[1] - a[1]) + '" rx="3"/>';
        if (z.kind === 'plan') {
          html += '<text class="zsub" x="' + f1(a[0] + 10) + '" y="' + f1(a[1] + 20) + '">' + esc(z.marker + ' · ' + z.name + (z.sub ? ' (' + z.sub + ')' : '')) + '</text>';
        } else {
          html += '<text class="zname" x="' + f1(a[0] + 10) + '" y="' + f1(a[1] + 22) + '">' + esc(z.marker + ' · ' + z.name) + '</text>';
          if (z.sub) html += '<text class="zsub" x="' + f1(a[0] + 10) + '" y="' + f1(a[1] + 37) + '">' + esc(z.sub) + '</text>';
        }
      }
      if (z.marker_at) {
        var m = toSvg(z.marker_at[0], z.marker_at[1]), side = z.marker_side || 'top', vert = side === 'left' || side === 'right';
        html += vert
          ? '<g transform="translate(' + f1(m[0] - 3) + ' ' + f1(m[1] - 9) + ')"><rect class="aruco-bg" width="6" height="18"/><rect class="aruco-fg" x="1.5" y="3" width="3" height="4"/><rect class="aruco-fg" x="1.5" y="11" width="3" height="4"/></g>'
          : '<g transform="translate(' + f1(m[0] - 9) + ' ' + f1(m[1] - 3) + ')"><rect class="aruco-bg" width="18" height="6"/><rect class="aruco-fg" x="3" y="1.5" width="4" height="3"/><rect class="aruco-fg" x="11" y="1.5" width="4" height="3"/></g>';
        var lx = side === 'right' ? m[0] - 10 : (vert ? m[0] + 10 : m[0] + 14);
        var ly = side === 'top' ? m[1] + 24 : (side === 'bottom' ? m[1] - 16 : m[1] + 26);
        html += '<text class="aruco-id" x="' + f1(lx) + '" y="' + f1(ly) + '"' + (side === 'right' ? ' text-anchor="end"' : '') + '>마커 ' + esc(z.marker) + '</text>';
      }
    });
    ZONES.labels.forEach(function (l) {
      var p = toSvg(l.at[0], l.at[1]);
      html += '<text class="obst-label" x="' + f1(p[0]) + '" y="' + f1(p[1] + 4) + '" text-anchor="middle">' + esc(l.text) + '</text>';
    });
    $('zones').innerHTML = html;

    // 축척 막대 (굵은 격자 한 칸 길이)
    var len = g.major * S, cx = VIEW_W / 2, y = VIEW_H - 14;
    $('scaleBar').innerHTML =
      '<line class="scale" x1="' + f1(cx - len / 2) + '" y1="' + f1(y) + '" x2="' + f1(cx + len / 2) + '" y2="' + f1(y) + '"/>' +
      '<line class="scale" x1="' + f1(cx - len / 2) + '" y1="' + f1(y - 5) + '" x2="' + f1(cx - len / 2) + '" y2="' + f1(y + 5) + '"/>' +
      '<line class="scale" x1="' + f1(cx + len / 2) + '" y1="' + f1(y - 5) + '" x2="' + f1(cx + len / 2) + '" y2="' + f1(y + 5) + '"/>' +
      '<text class="scale-t" x="' + f1(cx) + '" y="' + f1(y - 8) + '" text-anchor="middle">' + g.major + ' m</text>';

    // 로봇 아이콘: 기본 크기(56)는 1 m = 200 일 때 약 0.28 m. 지도가 커서 S가 작아지면
    // 실제 크기에 맞게 같이 줄인다 (작업 번호 글자는 그대로 두고 아이콘에 붙인다).
    var k = Math.min(1, S / 200);
    attrs(document.querySelector('#robot .robot-live'), { transform: 'scale(' + k.toFixed(3) + ')' });
    attrs($('robotTagG'), { transform: 'translate(0 ' + f1(40 * (1 - k)) + ')' });
    attrs($('robotLostT'), { transform: 'translate(0 ' + f1(-30 * (1 - k)) + ')' });
  }

  // ---- 작업 · 계획 경로 (미터) ----
  var plan = [], cum = [0], planLen = 0, jobKey = null;
  function applyJob(job) {
    var key = JSON.stringify(job || null);
    if (key === jobKey) return;
    jobKey = key; job = job || {};
    plan = job.plan || []; cum = [0];
    for (var i = 1; i < plan.length; i++) cum.push(cum[i - 1] + Math.hypot(plan[i][0] - plan[i - 1][0], plan[i][1] - plan[i - 1][1]));
    planLen = cum[cum.length - 1] || 0;
    var z = zoneByMarker(job.dest_marker);
    $('goal').style.display = z && z.goal ? '' : 'none';
    if (z && z.goal) { var g = toSvg(z.goal[0], z.goal[1]); attrs($('goal'), { transform: 'translate(' + f1(g[0]) + ' ' + f1(g[1]) + ')' }); }
    $('rgoal').textContent = z ? z.marker + ' ' + z.name + ' 구역' : '—';
    $('robotTag').textContent = job.id != null ? '작업 #' + job.id : '대기';
  }
  // 경로 시작에서 d 미터 지점의 [x, y, yaw]
  function pointAt(d) {
    if (!plan.length) return null;
    if (plan.length < 2) return [plan[0][0], plan[0][1], 0];
    d = Math.max(0, Math.min(planLen, d));
    for (var i = 1; i < plan.length - 1 && cum[i] < d; i++);
    var a = plan[i - 1], b = plan[i], t = (d - cum[i - 1]) / ((cum[i] - cum[i - 1]) || 1);
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, Math.atan2(b[1] - a[1], b[0] - a[0])];
  }
  // 로봇 위치를 경로 위에 투영했을 때 시작점에서의 거리
  function alongPlan(x, y) {
    var best = Infinity, along = 0;
    for (var i = 1; i < plan.length; i++) {
      var a = plan[i - 1], b = plan[i], dx = b[0] - a[0], dy = b[1] - a[1], l2 = dx * dx + dy * dy || 1;
      var t = Math.max(0, Math.min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / l2));
      var px = a[0] + dx * t, py = a[1] + dy * t, dist = Math.hypot(x - px, y - py);
      if (dist < best) { best = dist; along = cum[i - 1] + t * (cum[i] - cum[i - 1]); }
    }
    return along;
  }
  function pts(list) { return list.map(function (p) { var s = toSvg(p[0], p[1]); return f1(s[0]) + ',' + f1(s[1]); }).join(' '); }

  // 로봇 자세(지도 좌표 m, yaw rad)를 화면에 반영한다.
  // 실제 연동 때는 /robot/status 로 받은 x · y · yaw 로 이 함수만 부르면 된다.
  function setRobotPose(x, y, yaw) {
    var p = toSvg(x, y), ang = -yaw;   // 화면은 y가 아래로 커지므로 회전 방향이 반대
    attrs($('robot'), { transform: 'translate(' + f1(p[0]) + ' ' + f1(p[1]) + ')' });
    attrs($('robotBody'), { transform: 'rotate(' + f1(ang * 180 / Math.PI) + ')' });

    var d = alongPlan(x, y), done = [], rest = [[x, y]];
    for (var i = 0; i < plan.length; i++) (cum[i] <= d ? done : rest).push(plan[i]);
    done.push([x, y]);
    attrs($('routeDone'), { points: plan.length ? pts(done) : '' });
    attrs($('route'), { points: plan.length ? pts(rest) : '' });
    if (state !== 'lost') $('rleft').textContent = plan.length ? (planLen - d).toFixed(1) + ' m' : '—';

    // 안전 정지 화면용: 경로 0.42 m 앞의 사람, 전방 감지 부채꼴(반경 0.6 m)
    var ahead = pointAt(d + 0.42) || [x, y];
    var q = toSvg(ahead[0], ahead[1]);
    attrs($('person'), { transform: 'translate(' + f1(q[0]) + ' ' + f1(q[1]) + ')' });
    var R = 0.6 * S, half = 0.5;
    attrs($('fov'), { d: 'M' + f1(p[0]) + ' ' + f1(p[1]) +
      ' L' + f1(p[0] + R * Math.cos(ang - half)) + ' ' + f1(p[1] + R * Math.sin(ang - half)) +
      ' A' + f1(R) + ' ' + f1(R) + ' 0 0 1 ' + f1(p[0] + R * Math.cos(ang + half)) + ' ' + f1(p[1] + R * Math.sin(ang + half)) + ' Z' });
  }

  drawMap();
  applyJob(BOOT.status.job);

  // ---- 검사 결과 (세로 기판 스냅샷) ----
  // 검사 프로그램이 저장한 기판 사진(DB img_path)을 그대로 띄운다. 파일이 없으면 "사진 없음".
  var snapImg = $('snapImg');
  snapImg.addEventListener('load', function () { $('snap').classList.remove('no-photo'); });
  snapImg.addEventListener('error', function () { $('snap').classList.add('no-photo'); });
  // img_path 는 'logs/img_0001.jpg' 처럼 하위 폴더가 있을 수 있어 조각마다 인코딩한다
  function photoUrl(name, ver) { return '/snapshots/' + name.split('/').map(encodeURIComponent).join('/') + '?v=' + encodeURIComponent(ver || ''); }
  // 검사 번호+시각으로 새 결과인지 판단 (재촬영은 새 검사 번호로 들어온다)
  var lastInspKey = null;
  function inspKey(d) { return d ? d.id + '|' + d.time : 'none'; }
  function showInspection(d, recent) {
    lastInspKey = inspKey(d);
    if (!d) {
      // DB에 검사 기록이 하나도 없을 때 (seed.sql 없이 시작한 경우)
      snapImg.removeAttribute('src'); $('snap').classList.add('no-photo');
      $('verdict').textContent = '—'; $('verdict').className = 'verdict';
      $('inspId').textContent = '검사 기록 없음'; $('inspTime').textContent = '';
      $('inspDefect').innerHTML = '<span class="muted">—</span>'; $('inspDefect').title = '';
      $('inspParts').innerHTML = ''; $('inspDest').textContent = '—';
      $('recent').innerHTML = '<span>최근</span>';
      return;
    }
    if (d.image) snapImg.src = photoUrl(d.image, d.time);
    else { snapImg.removeAttribute('src'); $('snap').classList.add('no-photo'); }
    var v = $('verdict'); v.textContent = d.result; v.className = 'verdict ' + (d.fail ? 'ng' : 'ok');
    $('inspId').textContent = d.id;
    $('inspTime').textContent = d.time;
    // 불량이 여러 개면 한 줄 요약('… 외 2건')만 보이고, 마우스를 올리면 전체 목록
    $('inspDefect').innerHTML = d.defect ? esc(d.defect) : '<span class="muted">없음</span>';
    $('inspDefect').title = (d.defects || []).join('\n');
    // 부품 4개: 정상은 초록, 불량은 빨강 (마우스를 올리면 불량 내용)
    $('inspParts').innerHTML = (d.parts || []).map(function (p) {
      return '<span class="pchip ' + (p.ok ? 'ok' : 'ng') + '" title="' + esc(p.text) + '">' + esc(p.name) + '</span>';
    }).join('');
    $('inspDest').textContent = d.dest;
    $('recent').innerHTML = '<span>최근</span>' + recent.map(function (r) { return '<span class="r ' + (r[1] ? 'ok' : 'ng') + '" title="' + esc(r[0]) + '">' + (r[1] ? 'PASS' : 'FAIL') + '</span>'; }).join('');
  }

  // state / since 는 서버 값. since 는 서버 기준 상태 전환 시각(epoch 초)
  var state = 'normal', sinceAt = Date.now() / 1000, skew = 0;
  var fms = null;   // main.py /fms/status 값 (서버 /api/status 의 fms). null 이면 아직 못 받음 → 시안 애니메이션
  var progress = 0.42, last = performance.now();
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function elapsed() { return Math.max(0, Math.floor(Date.now() / 1000 + skew - sinceAt)); }
  function mmss(s) { return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }

  // 시안용: 실제 위치가 없으므로 계획 경로를 따라 progress(0~1) 지점에 로봇을 둔다
  function placeRobot() {
    var p = pointAt(planLen * progress);
    if (p) setRobotPose(p[0], p[1], p[2]);
  }

  // main.py /fms/status 값 표시. 못 받았으면 false 를 돌려줘서 시안 화면을 그대로 쓰게 한다
  function showFms() {
    if (!fms) return false;
    if (fms.x != null && fms.y != null) setRobotPose(fms.x, fms.y, (fms.yaw_deg || 0) * Math.PI / 180);
    if (state === 'lost') return true;          // 통신 끊김: 마지막 위치만 두고 수치는 render 의 '—' 그대로
    if (state === 'normal') $('badgeText').textContent = MISSIONS[fms.mission] || '주행 중';
    $('spd').textContent = fms.speed == null ? '—' : Math.abs(fms.speed).toFixed(2) + ' m/s';
    return true;
  }

  // ---- 통신 · 배터리 (서버 /api/status 의 robot. 기준은 app.py 의 COMM_DELAY_SEC / COMM_LOST_SEC) ----
  var link = BOOT.status.robot, linkAt = Date.now(), realLost = false;
  var COMM_TEXT = { none: '수신 없음', ok: '연결됨', delay: '지연', lost: '끊김' };
  function linkAge() { return link && link.age != null ? link.age + (Date.now() - linkAt) / 1000 : null; }
  function showLink() {
    var r = link || {}, comm = state === 'lost' ? 'lost' : (r.comm || 'none'), age = linkAge();
    $('lamp').className = 'lamp' + ({ ok: '', delay: ' warn', lost: ' bad', none: ' idle' })[comm];
    $('commText').textContent = COMM_TEXT[comm];
    $('commText').className = comm === 'lost' ? 'critv' : (comm === 'delay' ? 'warnv' : 'v');
    $('ping').textContent = comm === 'ok' ? '응답 ' + Math.round(r.age * 1000) + ' ms'
      : (age != null && comm !== 'none' ? Math.floor(age) + '초 무응답' : '');
    var pct = r.battery;
    $('battFill').style.width = (pct == null ? 0 : pct) + '%';
    $('battFill').classList.toggle('low', !!r.battery_low);
    $('battPct').textContent = pct == null ? '-' : pct + '%' + (comm === 'lost' ? ' (마지막 값)' : '');
  }

  function render() {
    var S = STATES[state], lost = state === 'lost', safety = state === 'safety';
    var tone = S.tone;
    app.dataset.state = state;
    app.classList.remove('tone-run', 'tone-warn', 'tone-crit');
    app.classList.add('tone-' + tone);

    $('badgeText').textContent = S.badge;
    $('stateCode').textContent = S.code;
    $('sensors').classList.toggle('stale', lost);
    $('spd').textContent = lost ? '—' : (safety ? '0.00 m/s' : '0.15 m/s');
    $('ramcl').textContent = lost ? '—' : '정상';
    if (lost) { $('rleft').textContent = '—'; }

    var yt = $('yoloTag');
    if (safety) { yt.textContent = '사람 감지'; yt.className = 'hud tr warn'; }
    else { yt.textContent = lost ? '감지 정보 없음' : '전방 감지 없음'; yt.className = 'hud tr'; }
    $('camLive').innerHTML = lost ? '<span style="color:#9aa">●</span> 전방 카메라 · 끊김' : '<span class="rec">●</span> 전방 카메라';

    // banner
    var b = $('banner');
    if (S.banner) {
      b.hidden = false; $('bannerTitle').textContent = S.banner[0]; $('bannerDetail').textContent = S.banner[1];
    } else b.hidden = true;

    if (lost) progress = 0.47;
    if (safety) progress = 0.45;
    if (!showFms()) placeRobot();
    tick();
  }

  function tick() {
    var S = STATES[state], since = elapsed();
    if (state === 'lost') {
      var age = realLost ? Math.floor(linkAge() || 0) : S.timerFrom + since;
      $('lostAgeMap').textContent = age;
      $('bannerTimer').textContent = '무응답 ' + mmss(age);
    } else if (state === 'safety') {
      $('bannerTimer').textContent = '정지 ' + mmss(S.timerFrom + since);
    }
    showLink();
  }

  function frame(t) {
    var dt = (t - last) / 1000; last = t;
    if (!fms && state === 'normal' && !reduce) {
      progress += dt * 0.006;
      if (progress > 0.86) progress = 0.32;
      placeRobot();
    }
    requestAnimationFrame(frame);
  }

  // 서버 상태 반영 (최초 로드 · 폴링 공용)
  function applyStatus(s) {
    skew = s.server_time - Date.now() / 1000;
    sinceAt = s.since;
    link = s.robot; linkAt = Date.now();
    fms = s.fms;
    // 실제 통신이 끊기면 (3초 넘게 무응답) 시안의 '통신 끊김' 화면을 그대로 쓴다.
    var next = (s.robot && s.robot.comm == 'lost' && s.state === 'normal' ) ? 'lost' : s.state;
    realLost = next === 'lost' && s.state !== 'lost';
    var changed = next !== state;
    if (next !== state && next === 'normal') progress = 0.42;
    state = next;
    applyJob(s.job);

    if (inspKey(s.inspection) !== lastInspKey) showInspection(s.inspection, s.recent);
    $('todayTotal').textContent = s.today.total + '건';
    $('todayOk').textContent = 'PASS ' + s.today.pass_rate + '%';
    $('todayAvg').textContent = s.today.avg;

    if (changed) render(); else { tick(); showFms(); }
  }
  function poll() { api('GET', '/api/status').then(applyStatus).catch(function () {}); }

  // 이벤트 기록 창 (서버 조회)
  function queryEvents() {
    var q = new URLSearchParams({ date: $('evDate').value, kind: $('evKind').value });
    $('evCount').textContent = '조회 중…';
    api('GET', '/api/events?' + q.toString()).then(function (res) {
      $('evBody').innerHTML = res.rows.map(function (e) {
        var k = KIND[e.kind] || [e.kind, ''];
        return '<tr><td class="tm">' + esc(e.time) + '</td><td><span class="kind ' + k[1] + '">' + esc(k[0]) + '</span></td><td>' + esc(e.text) + '</td></tr>';
      }).join('');
      $('evCount').textContent = res.rows.length + '건 · 조회 ' + res.queried_at;
    }).catch(function (err) { $('evCount').textContent = '조회 실패 · ' + err.message; });
  }

  var lastFocus = null;
  $('openEvents').addEventListener('click', function () { lastFocus = this; queryEvents(); $('eventsModal').hidden = false; $('closeEvents').focus(); });
  function closeEv() { $('eventsModal').hidden = true; if (lastFocus) lastFocus.focus(); }
  $('closeEvents').addEventListener('click', closeEv);
  $('eventsModal').addEventListener('click', function (e) { if (e.target === this) closeEv(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !$('eventsModal').hidden) closeEv(); });
  $('evQuery').addEventListener('click', queryEvents);

  $('projToggle').addEventListener('click', function () {
    var on = !document.body.classList.contains('proj');
    document.body.classList.toggle('proj', on);
    this.setAttribute('aria-pressed', String(on));
  });

  // 전방 카메라 (web_video_server MJPEG). 영상이 실제로 들어올 때만 화면에 보이고,
  // 끊기면 "영상 신호 없음"을 띄운 채 5초마다 다시 연결한다.
  var cam = $('camImg'), feed = cam.parentNode, CAM_URL = cam.getAttribute('src');
  function camFail() {
    feed.classList.add('cam-off');
    setTimeout(function () { cam.src = CAM_URL + '&t=' + Date.now(); }, 5000);
  }
  cam.addEventListener('error', camFail);
  // 첫 화면이 실제로 들어오면(가로 크기가 생기면) "영상 신호 없음"을 끈다
  setInterval(function () { if (cam.naturalWidth > 0) feed.classList.remove('cam-off'); }, 1000);
  // 이 코드가 실행되기 전에 이미 연결이 실패했으면 바로 처리
  if (cam.complete && cam.naturalWidth === 0) camFail();

  setInterval(tick, 1000);
  setInterval(poll, 2000);
  applyStatus(BOOT.status);
  render();
  requestAnimationFrame(frame);
})();
