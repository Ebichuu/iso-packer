
PAGE = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ISO Packer Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --sidebar-bg: #151923;
  --sidebar-text: #f8fafc;
  --sidebar-hover: #293241;
  --sidebar-active: #d43f5e;
  --main-bg: #f4f1ec;
  --card-bg: #ffffff;
  --text-main: #171717;
  --text-muted: #6f6a63;
  --border: #e7e0d6;
  --accent: #c73555;
  --accent-hover: #a82543;
  --success: #12805c;
  --warning: #b7791f;
  --danger: #c2413f;
  --plum: #e85d75;
  --plum-deep: #9f243f;
  --plum-pale: #ffd8df;
  --ink: #141820;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  background:
    linear-gradient(135deg, rgba(255,255,255,0.86), rgba(244,241,236,0.92)),
    radial-gradient(circle at 88% 8%, rgba(232, 93, 117, 0.16), transparent 28%),
    var(--main-bg);
  color: var(--text-main);
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* Sidebar */
.sidebar {
  width: 318px;
  background:
    linear-gradient(150deg, rgba(26,31,43,0.96) 0%, rgba(19,23,32,0.98) 54%, rgba(45,25,35,0.98) 100%),
    var(--ink);
  color: var(--sidebar-text);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: transform 0.3s ease;
  z-index: 100;
  position: relative;
  overflow: hidden;
  box-shadow: 18px 0 44px rgba(30, 24, 18, 0.12), inset -1px 0 0 rgba(255,255,255,0.08);
}
.sidebar::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 22% 12%, rgba(255,255,255,0.08), transparent 24%),
    radial-gradient(circle at 82% 2%, rgba(232,93,117,0.28), transparent 22%),
    linear-gradient(90deg, rgba(255,255,255,0.04), transparent 42%);
  pointer-events: none;
}
.sidebar::after {
  content: "";
  position: absolute;
  right: -34px;
  top: 74px;
  width: 178px;
  height: 250px;
  pointer-events: none;
  background:
    radial-gradient(circle at 38px 32px, #ffe4e8 0 6px, transparent 7px),
    radial-gradient(circle at 50px 20px, #f6a7b4 0 8px, transparent 9px),
    radial-gradient(circle at 63px 34px, #e85d75 0 8px, transparent 9px),
    radial-gradient(circle at 50px 49px, #ffc7d1 0 8px, transparent 9px),
    radial-gradient(circle at 33px 20px, #d94a65 0 7px, transparent 8px),
    radial-gradient(circle at 52px 35px, #f6c25d 0 2px, transparent 3px),
    radial-gradient(circle at 104px 104px, #ffe4e8 0 5px, transparent 6px),
    radial-gradient(circle at 115px 93px, #f6a7b4 0 7px, transparent 8px),
    radial-gradient(circle at 127px 106px, #e85d75 0 7px, transparent 8px),
    radial-gradient(circle at 114px 119px, #ffc7d1 0 7px, transparent 8px),
    radial-gradient(circle at 99px 93px, #d94a65 0 6px, transparent 7px),
    radial-gradient(circle at 117px 106px, #f6c25d 0 2px, transparent 3px);
  filter: drop-shadow(0 14px 22px rgba(0,0,0,0.2));
  opacity: 0.98;
}
.sidebar-header {
  padding: 24px 22px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  position: relative;
  z-index: 1;
}
.brand-mark {
  width: 48px;
  height: 48px;
  flex: 0 0 auto;
  border-radius: 8px;
  background: linear-gradient(145deg, rgba(255,255,255,0.18), rgba(255,255,255,0.06));
  border: 1px solid rgba(255,255,255,0.16);
  box-shadow: 0 16px 30px rgba(0,0,0,0.18);
}
.brand-copy { min-width: 0; }
.sidebar-header h1 {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
  letter-spacing: 0;
  background: linear-gradient(to right, #ffffff, #ffd8df 54%, #f6c25d);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.sidebar-header p {
  margin: 4px 0 0;
  color: rgba(255,255,255,0.58);
  font-size: 12px;
}
.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 18px;
  position: relative;
  z-index: 1;
  scrollbar-width: thin;
  scrollbar-color: rgba(255, 216, 223, 0.34) rgba(255,255,255,0.06);
}
.sidebar-content::-webkit-scrollbar {
  width: 10px;
}
.sidebar-content::-webkit-scrollbar-track {
  background: rgba(255,255,255,0.05);
  border-radius: 999px;
  margin: 10px 0;
}
.sidebar-content::-webkit-scrollbar-thumb {
  background:
    linear-gradient(180deg, rgba(255,216,223,0.42), rgba(232,93,117,0.34));
  border: 2px solid rgba(24, 28, 38, 0.72);
  border-radius: 999px;
}
.sidebar-content::-webkit-scrollbar-thumb:hover {
  background:
    linear-gradient(180deg, rgba(255,228,232,0.58), rgba(232,93,117,0.48));
}
.sidebar-footer {
  padding: 16px;
  font-size: 12px;
  color: rgba(255,255,255,0.56);
  border-top: 1px solid rgba(255,255,255,0.1);
  position: relative;
  z-index: 1;
}
.sidebar form {
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px;
  padding: 14px;
  background: linear-gradient(180deg, rgba(255,255,255,0.09), rgba(255,255,255,0.045));
  box-shadow: 0 18px 40px rgba(0,0,0,0.18);
  backdrop-filter: blur(14px);
}
.menu-alert {
  display: none;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  padding: 10px 12px;
  border: 1px solid rgba(16, 185, 129, 0.38);
  border-radius: 8px;
  background: rgba(16, 185, 129, 0.14);
  color: #d1fae5;
  font-size: 13px;
  font-weight: 600;
}
.menu-alert.show { display: flex; }
.menu-alert.error {
  border-color: rgba(248, 113, 113, 0.45);
  background: rgba(239, 68, 68, 0.16);
  color: #fee2e2;
}
.menu-alert-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
  box-shadow: 0 0 0 4px rgba(255,255,255,0.08);
}

/* Form Styles in Sidebar */
.form-group { margin-bottom: 12px; }
.form-group label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: rgba(255,255,255,0.62);
  margin-bottom: 6px;
  text-transform: uppercase;
}
.sidebar input[type=text], .sidebar input[type=number] {
  width: 100%;
  background: rgba(255,255,255,0.1);
  border: 1px solid rgba(255,255,255,0.13);
  border-radius: 6px;
  padding: 9px 11px;
  color: white;
  font-size: 14px;
  transition: all 0.2s;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
}
.sidebar input::placeholder { color: rgba(255,255,255,0.38); }
.sidebar input:focus {
  outline: none;
  border-color: rgba(255, 216, 223, 0.72);
  background: rgba(255,255,255,0.15);
  box-shadow: 0 0 0 3px rgba(232, 93, 117, 0.2);
}
.settings-options {
  margin: 16px 0 12px;
  border-top: 1px solid rgba(255,255,255,0.1);
  padding-top: 14px;
}
.checkbox-group {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  cursor: pointer;
  font-size: 13px;
  color: rgba(255,255,255,0.78);
}
.checkbox-group input {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
.button-stack { margin-top: 16px; }

/* Main Content */
.main {
  flex: 1;
  overflow-y: auto;
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.header-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 14px;
}
.stat-card {
  background: rgba(255,255,255,0.86);
  border: 1px solid rgba(231,224,214,0.92);
  padding: 18px;
  border-radius: 8px;
  box-shadow: 0 14px 36px rgba(55, 45, 35, 0.07);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-label { font-size: 12px; color: var(--text-muted); font-weight: 700; }
.stat-value { font-size: 24px; font-weight: 700; color: var(--text-main); }

/* Task Card */
.task-card {
  background: linear-gradient(135deg, rgba(255,255,255,0.96), rgba(255,248,246,0.92));
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 18px 46px rgba(71, 52, 38, 0.08);
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.task-title { font-size: 16px; font-weight: 600; }
.task-status {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

/* Progress Bars */
.progress-container { display: flex; flex-direction: column; gap: 8px; }
.progress-info { display: flex; justify-content: space-between; font-size: 13px; }
.progress-bar-bg {
  height: 9px;
  background: #ece6dd;
  border-radius: 4px;
  overflow: hidden;
}
.progress-bar-fill {
  height: 100%;
  background: var(--accent);
  width: 0%;
  transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}
.progress-bar-fill.total { background: linear-gradient(90deg, #c73555, #e86f58, #d6a34b); }

/* Table Section */
.card {
  background: rgba(255,255,255,0.9);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 16px 42px rgba(55, 45, 35, 0.07);
  overflow: hidden;
  flex: 0 0 auto;
}
.card-header {
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-header h2 { font-size: 16px; margin: 0; letter-spacing: 0; }
.live-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}
.live-badge::before {
  content: "";
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #22c55e;
  box-shadow: 0 0 0 4px rgba(34, 197, 94, 0.16);
}
.table-wrap { overflow-x: auto; }
.history-wrap {
  max-height: 520px;
  overflow: auto;
}
.history-wrap thead th {
  position: sticky;
  top: 0;
  z-index: 2;
}
.history-wrap th:last-child,
.history-wrap td:last-child {
  position: sticky;
  right: 0;
  min-width: 96px;
  text-align: center;
  background: #fffdfa;
  box-shadow: -10px 0 14px rgba(15, 23, 42, 0.06);
}
.history-wrap th:last-child {
  z-index: 3;
  background: #faf7f2;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th {
  background: #faf7f2;
  padding: 12px 24px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}
td {
  padding: 16px 24px;
  font-size: 14px;
  border-bottom: 1px solid var(--border);
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fff8f7; }
.table-progress {
  min-width: 210px;
  display: flex;
  flex-direction: column;
  gap: 7px;
}
.table-progress-track {
  height: 8px;
  background: #e8eef7;
  border-radius: 999px;
  overflow: hidden;
}
.table-progress-fill {
  height: 100%;
  width: 0%;
  background: #2563eb;
  border-radius: inherit;
  transition: width 0.35s ease;
}
.table-progress-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.3;
  white-space: nowrap;
}
.table-progress-percent {
  color: #1d4ed8;
  font-weight: 700;
}
.target-cell {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.target-text {
  min-width: 0;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}
.rerun-btn {
  flex: 0 0 auto;
  border: 1px solid #d8cfc3;
  border-radius: 6px;
  background: #fffaf2;
  color: #5f5040;
  font-size: 12px;
  font-weight: 700;
  padding: 6px 9px;
  cursor: pointer;
}
.rerun-btn:disabled { opacity: 0.55; cursor: wait; }
.rerun-btn:hover:not(:disabled) { background: #f7ead9; }

/* Status Badges */
.badge {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}
.badge-blue { background: #e8f1f4; color: #246478; }
.badge-green { background: #e6f4ed; color: #176447; }
.badge-yellow { background: #fff4d8; color: #875a13; }
.badge-red { background: #fde8e8; color: #a43a38; }
.badge-gray { background: #eee9e2; color: #5d5851; }

/* Logs Area */
.logs {
  background: #FFFFFF;
  color: #000000;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #dbe3ef;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 350px;
  min-height: 220px;
  overflow-y: auto;
  white-space: normal;
}
.logs::-webkit-scrollbar { width: 10px; }
.logs::-webkit-scrollbar-track { background: #f1f5f9; border-radius: 999px; }
.logs::-webkit-scrollbar-thumb { background: #94a3b8; border-radius: 999px; border: 2px solid #f1f5f9; }
.log-line {
  display: block;
  padding: 5px 0;
  border-bottom: 1px solid #eef0f3;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.log-line:last-child { border-bottom: none; }
.log-time {
  color: #000000;
}
.log-message {
  color: #000000;
}

/* Buttons */
.btn {
  border: none;
  border-radius: 6px;
  padding: 11px 16px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  width: 100%;
}
.btn:disabled { opacity: 0.62; cursor: wait; }
.btn-primary {
  background: linear-gradient(135deg, #c73555, #e85d75 58%, #d6a34b);
  color: white;
  margin-bottom: 8px;
  box-shadow: 0 10px 24px rgba(199, 53, 85, 0.28);
}
.btn-primary:hover { filter: brightness(1.06); transform: translateY(-1px); }
.btn-secondary { background: rgba(255,255,255,0.12); color: rgba(255,255,255,0.9); border: 1px solid rgba(255,255,255,0.12); }
.btn-secondary:hover { background: rgba(255,255,255,0.18); }

/* Responsive */
@media (max-width: 1024px) {
  body { display: block; height: auto; overflow: auto; }
  .sidebar { width: 100%; min-height: auto; }
  .sidebar-content { overflow: visible; }
  .main { padding: 18px; }
}
</style>
</head>
<body>
  <aside class="sidebar">
    <div class="sidebar-header">
      <svg class="brand-mark" viewBox="0 0 64 64" aria-hidden="true">
        <path d="M12 48 C24 38 35 25 51 13" fill="none" stroke="#7a4a2a" stroke-width="4" stroke-linecap="round"/>
        <path d="M27 31 C22 29 19 25 18 20" fill="none" stroke="#7a4a2a" stroke-width="2" stroke-linecap="round"/>
        <path d="M39 20 C43 23 47 24 52 23" fill="none" stroke="#7a4a2a" stroke-width="2" stroke-linecap="round"/>
        <g fill="#f7b6c1">
          <circle cx="24" cy="26" r="5"/><circle cx="30" cy="20" r="5"/><circle cx="37" cy="26" r="5"/><circle cx="31" cy="33" r="5"/><circle cx="29" cy="27" r="4"/>
        </g>
        <circle cx="31" cy="27" r="2.2" fill="#f2bf55"/>
        <g fill="#e85d75">
          <circle cx="45" cy="18" r="4"/><circle cx="50" cy="14" r="4"/><circle cx="55" cy="19" r="4"/><circle cx="50" cy="24" r="4"/><circle cx="49" cy="19" r="3"/>
        </g>
        <circle cx="50" cy="19" r="1.8" fill="#f2bf55"/>
      </svg>
      <div class="brand-copy">
        <h1>ISO PACKER</h1>
        <p>控制台</p>
      </div>
    </div>
    <div class="sidebar-content">
      <div class="menu-alert" id="settings-alert" role="status" aria-live="polite">
        <span class="menu-alert-dot"></span>
        <span id="settings-alert-text">设置已保存</span>
      </div>
      <form method="post" action="/settings" id="settings-form">
        <div class="form-group">
          <label>监控目录</label>
          <input name="watch_dir" type="text" value="{{cfg.watch_dir}}" required>
        </div>
        <div class="form-group">
          <label>输出目录</label>
          <input name="output_dir" type="text" value="{{cfg.output_dir}}" required>
        </div>
        <div class="form-group">
          <label>扫描间隔 (秒)</label>
          <input name="scan_interval_seconds" type="number" min="5" value="{{cfg.scan_interval_seconds}}">
        </div>
        <div class="form-group">
          <label>稳定时间 (秒)</label>
          <input name="stable_seconds" type="number" min="30" value="{{cfg.stable_seconds}}">
        </div>
        <div class="form-group">
          <label>最小空间 (GB)</label>
          <input name="min_free_space_gb" type="number" min="0" value="{{cfg.min_free_space_gb}}">
        </div>
        <div class="form-group">
          <label>CloudDrive2 挂载根目录</label>
          <input name="cd2_mount_root" type="text" value="{{cfg.cd2_mount_root}}">
        </div>
        <div class="form-group">
          <label>CloudDrive2 目标目录</label>
          <input name="cd2_target_dir" type="text" value="{{cfg.cd2_target_dir}}">
        </div>
        
        <div class="settings-options">
          <label class="checkbox-group">
            <input name="enabled" type="checkbox" {% if cfg.enabled %}checked{% endif %}>
            <span>启用监控</span>
          </label>
          <label class="checkbox-group">
            <input name="delete_source_after_success" type="checkbox" {% if cfg.delete_source_after_success %}checked{% endif %}>
            <span>成功后删除源</span>
          </label>
          <label class="checkbox-group">
            <input name="cd2_transfer_enabled" type="checkbox" {% if cfg.cd2_transfer_enabled %}checked{% endif %}>
            <span>启用 CD2 转移</span>
          </label>
          <input name="cd2_require_mount" type="hidden" value="1">
        </div>
        
        <div class="button-stack">
          <button class="btn btn-primary" type="submit" data-saving-text="保存中...">保存设置</button>
          <button class="btn btn-secondary" name="scan" value="1" type="submit" data-saving-text="保存并扫描中...">保存并扫描</button>
        </div>
      </form>
    </div>
    <div class="sidebar-footer">
      <div>Port: 15865</div>
      <div style="margin-top: 4px;">前端版本：实时刷新版</div>
      <div id="refresh-state" style="margin-top: 4px;">连接中...</div>
    </div>
  </aside>

  <main class="main">
    <div class="header-stats">
      <div class="stat-card">
        <div class="stat-label">最后扫描</div>
        <div class="stat-value" id="last-scan" style="font-size: 16px;">{{state.last_scan or '尚未扫描'}}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">任务数量</div>
        <div class="stat-value" id="task-count">{{items|length}}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">监控状态</div>
        <div class="stat-value" style="color: var(--success); font-size: 18px;">运行中</div>
      </div>
    </div>

    <div class="task-card" id="active-task-card" style="display: {% if state.active %}flex{% else %}none{% endif %};">
      <div class="task-header">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div class="task-title" id="active-source-name">{% if state.active %}{{state.active.source}}{% endif %}</div>
        </div>
        <div id="active-status-badge">{% if state.active %}<span class="badge badge-yellow">{{status_label(state.active.status)}}</span>{% endif %}</div>
      </div>
      
      <div class="progress-container" id="total-progress-container">
        <div class="progress-info">
          <span>总任务进度</span>
          <span id="total-percent-text">0%</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill total" id="total-progress-bar"></div>
        </div>
      </div>

      <div class="progress-container" id="phase-progress-container">
        <div class="progress-info">
          <span id="phase-label">当前阶段</span>
          <span id="phase-progress-text">0 / 0</span>
        </div>
        <div class="progress-bar-bg">
          <div class="progress-bar-fill" id="phase-progress-bar"></div>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2>任务列表</h2>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>源路径</th>
              <th>状态</th>
              <th>文件大小</th>
              <th>输出目标</th>
            </tr>
          </thead>
          <tbody id="items-body">
            {% for key,item in items %}
            <tr>
              <td style="font-weight: 500;">{{key}}</td>
              <td>
                <span class="badge {{badge_class(item.status)}}">{{status_label(item.status)}}</span>
              </td>
              <td style="color: var(--text-muted);">{{format_size(item.last_size or item.size or 0)}}</td>
              <td><span class="target-text" title="{{item.target or '-'}}">{{item.target or '-'}}</span></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2>&#23553;&#35013;&#21382;&#21490;&#35760;&#24405;</h2>
      </div>
      <div class="table-wrap history-wrap">
        <table>
          <thead>
            <tr>
              <th>&#28304;&#36335;&#24452;</th>
              <th>&#29366;&#24577;</th>
              <th>&#25991;&#20214;&#22823;&#23567;</th>
              <th>&#36755;&#20986;&#30446;&#26631;</th>
              <th>&#25805;&#20316;</th>
            </tr>
          </thead>
          <tbody id="history-body">
            {% for key,item in history_items %}
            <tr data-history-key="{{key}}">
              <td title="{{key}}">
                <div style="font-weight: 500;">{{key.split('/')[-1]}}</div>
                <div style="font-size: 11px; color: #94a3b8;">{{key}}</div>
              </td>
              <td><span class="badge {{badge_class(item.status)}}">{{status_label(item.status)}}</span></td>
              <td style="color: var(--text-muted);">{{format_size(item.last_size or item.size or 0)}}</td>
              <td><span class="target-text" title="{{item.target or '-'}}">{{item.target or '-'}}</span></td>
              <td><button class="rerun-btn" type="button" data-rerun-source="{{key}}">&#37325;&#26032;&#23553;&#35013;</button></td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2>系统日志</h2>
      </div>
      <div class="logs" id="events">
        {% for event in events %}
        <div class="log-line">{{event}}</div>
        {% endfor %}
      </div>
    </div>
  </main>

<script>
(function(){
const labels={watching:"\u76d1\u63a7\u4e2d",receiving:"\u63a5\u6536\u4e2d",waiting_stable:"\u7b49\u5f85\u7a33\u5b9a",waiting_partial:"\u7b49\u5f85\u4e0b\u8f7d\u5b8c\u6210",ready:"\u51c6\u5907\u6253\u5305",running:"\u6b63\u5728\u5c01\u88c5",done:"\u5df2\u5b8c\u6210",failed:"\u5931\u8d25",verify_failed:"\u9a8c\u8bc1\u5931\u8d25",uploading:"\u6b63\u5728\u4e0a\u4f20",upload_done:"\u4e0a\u4f20\u5b8c\u6210",upload_failed:"\u4e0a\u4f20\u5931\u8d25",transferring:"\u6b63\u5728\u79fb\u52a8\u5230 CD2",transfer_done:"\u5df2\u79fb\u52a8\u5230 CD2",transfer_failed:"\u79fb\u52a8\u5931\u8d25",removed:"\u6e90\u5df2\u79fb\u9664"};
const $=id=>document.getElementById(id);
let alertTimer;
const seenLogEvents = new Set();

function showSettingsAlert(message, isError=false) {
  const alert = $("settings-alert");
  const text = $("settings-alert-text");
  if(!alert || !text) return;
  clearTimeout(alertTimer);
  text.textContent = message;
  alert.classList.toggle("error", isError);
  alert.classList.add("show");
  alertTimer = setTimeout(() => alert.classList.remove("show"), 4500);
}

function setupTaskActions(){
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-rerun-source]");
    if(!button) return;
    const source = button.dataset.rerunSource;
    if(!source) return;
    if(!confirm("\u786e\u8ba4\u91cd\u65b0\u5c01\u88c5\u8fd9\u4e2a\u4efb\u52a1\uff1f")) return;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "\u6267\u884c\u4e2d...";
    try {
      const data = new FormData();
      data.set("source", source);
      const res = await fetch("/rerun", { method: "POST", body: data });
      const payload = await res.json().catch(() => ({}));
      if(!res.ok || payload.ok === false) throw new Error(payload.message || ("HTTP " + res.status));
      showSettingsAlert(payload.message || "\u5df2\u5f00\u59cb\u624b\u52a8\u5c01\u88c5");
      refresh();
    } catch(e) {
      showSettingsAlert(e.message || "\u624b\u52a8\u5c01\u88c5\u5931\u8d25", true);
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  });
}

function setupSettingsForm(){
  const form = $("settings-form");
  if(!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitter = event.submitter;
    const buttons = Array.from(form.querySelectorAll("button"));
    const originalText = submitter ? submitter.textContent : "";
    const data = new FormData(form);
    if(submitter && submitter.name) data.set(submitter.name, submitter.value);
    buttons.forEach(button => button.disabled = true);
    if(submitter) submitter.textContent = submitter.dataset.savingText || "保存中...";
    try {
      const res = await fetch(form.action, { method: "POST", body: data });
      if(!res.ok) throw new Error("HTTP " + res.status);
      showSettingsAlert(data.has("scan") ? "设置已保存，已开始扫描" : "设置已保存");
      refresh();
    } catch(e) {
      showSettingsAlert("设置保存失败，请检查服务状态", true);
    } finally {
      buttons.forEach(button => button.disabled = false);
      if(submitter) submitter.textContent = originalText;
    }
  });
}

function getBadgeClass(status) {
  if (['done', 'upload_done', 'transfer_done'].includes(status)) return 'badge-green';
  if (['failed', 'verify_failed', 'upload_failed', 'transfer_failed'].includes(status)) return 'badge-red';
  if (['running', 'uploading', 'transferring'].includes(status)) return 'badge-yellow';
  if (['skipped', 'removed'].includes(status)) return 'badge-gray';
  return 'badge-blue';
}

function label(s){return labels[s]||s||"未知"}
  function esc(v){return String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]))}

function statusBadgeText(status, item={}) {
  if (status === "running") return "\u6b63\u5728\u5c01\u88c5";
  if (status === "transferring") return "\u6b63\u5728\u79fb\u52a8\u5230 CD2";
  if (status === "uploading") return "\u6b63\u5728\u4e0a\u4f20";
  if (status === "transfer_done") return "\u5df2\u79fb\u52a8\u5230 CD2";
  if (status === "upload_done") return "\u5df2\u4e0a\u4f20\u5b8c\u6210";
  if (status === "done") return item.pack_iso === false ? "\u8df3\u8fc7\u5c01\u88c5" : "\u5df2\u5c01\u88c5 ISO";
  if (status === "skipped") return "\u8df3\u8fc7\u5c01\u88c5";
  return label(status);
}

function phaseStatusText(active) {
  const progress = (active && (active.progress || active.upload_progress || {})) || {};
  const phase = progress.phase || "";
  const status = active && active.status;
  if (phase === "packing" || status === "running") return "\u6b63\u5728\u5c01\u88c5";
  if (phase === "transfer" || status === "transferring") return "\u6b63\u5728\u79fb\u52a8\u5230 CD2";
  if (phase === "uploading" || status === "uploading") return "\u6b63\u5728\u4e0a\u4f20";
  return statusBadgeText(status, active || {});
}

function formatSize(value){
  let size=Number(value||0);
  if(size >= 1073741824) return (size/1073741824).toFixed(2)+" GB";
  if(size >= 1048576) return (size/1048576).toFixed(2)+" MB";
  return (size/1024).toFixed(2)+" KB";
}

function getTaskProgress(item, active, key) {
  const activeProgress = active && active.source === key ? (active.progress || active.upload_progress || {}) : {};
  const doneStatuses = ['done', 'upload_done', 'transfer_done'];
  const current = Number(
    activeProgress.current ?? activeProgress.uploaded ?? item.currentSize ?? item.current ?? item.last_size ?? item.size ?? 0
  );
  const total = Number(
    activeProgress.total ?? item.totalSize ?? item.total ?? item.size ?? item.last_size ?? current ?? 0
  );
  let percent = total > 0 ? (current / total) * 100 : 0;
  if (doneStatuses.includes(item.status)) percent = 100;
  percent = Math.max(0, Math.min(100, percent));
  return { current, total, percent };
}

function taskStatusText(item, active, key) {
  if(active && active.source === key) return phaseStatusText(active);
  return statusBadgeText((item || {}).status, item || {});
}

function renderTaskStatus(item, active, key) {
  const status = active && active.source === key ? active.status : (item || {}).status;
  return `<span class="badge ${getBadgeClass(status)}" data-task-status>${esc(taskStatusText(item, active, key))}</span>`;
}

function getEventTime(eventText) {
  const match = String(eventText || "").match(/^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]/);
  return match ? new Date(match[1].replace(" ", "T")).getTime() : 0;
}

function normalizeEvents(events) {
  const text = Array.isArray(events) ? events.join("\\n") : String(events || "");
  return text
    .replace(/\s*(?=\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\])/g, "\\n")
    .split("\\n")
    .map(line => line.trim())
    .filter(Boolean);
}

function renderEvents(events) {
  const logs = $("events");
  if(!logs) return;
  const latestFirstEvents = normalizeEvents(events)
    .slice(-120)
    .sort((a, b) => getEventTime(b) - getEventTime(a));

  seenLogEvents.clear();
  latestFirstEvents.forEach(eventText => seenLogEvents.add(eventText));
  logs.innerHTML = latestFirstEvents.map(eventText => {
    const match = String(eventText).match(/^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$/);
    const time = match ? match[1] : "";
    const message = match ? match[2] : eventText;
    return `<div class="log-line"><span class="log-time">${esc(time ? "[" + time + "] " : "")}</span><span class="log-message">${esc(message)}</span></div>`;
  }).join("");
}

function createLogLine(eventText) {
  const line = document.createElement("div");
  line.className = "log-line";
  const match = String(eventText).match(/^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$/);
  const time = document.createElement("span");
  time.className = "log-time";
  time.textContent = match ? `[${match[1]}] ` : "";
  const message = document.createElement("span");
  message.className = "log-message";
  message.textContent = match ? match[2] : String(eventText);
  line.append(time, message);
  return line;
}

function appendNewEvents(events) {
  const logs = $("events");
  if(!logs) return;
  const latestFirstEvents = normalizeEvents(events)
    .slice(-120)
    .sort((a, b) => getEventTime(b) - getEventTime(a));
  const freshEvents = latestFirstEvents
    .filter(eventText => !seenLogEvents.has(eventText))
    .sort((a, b) => getEventTime(a) - getEventTime(b));

  freshEvents.forEach(eventText => {
    seenLogEvents.add(eventText);
    logs.prepend(createLogLine(eventText));
  });

  while (logs.children.length > 120) {
    const last = logs.lastElementChild;
    if(!last) break;
    last.remove();
  }
}

function renderProgress(active){
  const card = $("active-task-card");
  if(!active) {
    card.style.display = "none";
    return;
  }
  card.style.display = "flex";
  
  const p = active.progress || active.upload_progress || {};
  const percent = Math.max(0, Math.min(100, Number(p.percent || 0)));
  const phase = phaseStatusText(active);
  
  $("active-source-name").textContent = active.source.split('/').pop();
  $("active-status-badge").innerHTML = `<span class="badge ${getBadgeClass(active.status)}">${phase}</span>`;
  
  let totalPercent = percent;
  if (active.status === "transferring" || active.status === "uploading") {
    totalPercent = 50 + (percent * 0.5);
  } else if (active.status === "running") {
    totalPercent = percent * 0.5;
  }
  
  $("total-percent-text").textContent = totalPercent.toFixed(1) + "%";
  $("total-progress-bar").style.width = totalPercent + "%";
  $("phase-label").textContent = phase;
  $("phase-progress-text").textContent = formatSize(p.current || p.uploaded || 0) + " / " + formatSize(p.total || 0);
  $("phase-progress-bar").style.width = percent + "%";
}

function renderTaskSummary(state) {
  const active = state.active;
  if(active) {
    renderProgress(active);
    return;
  }

  const card = $("active-task-card");
  const first = taskEntries(state.items || {}, null)[0];
  if(!first) {
    card.style.display = "none";
    return;
  }

  const [key, item] = first;
  const progress = getTaskProgress(item, null, key);
  const statusText = statusBadgeText(item.status, item);
  card.style.display = "flex";
  $("active-source-name").textContent = key.split('/').pop();
  $("active-status-badge").innerHTML = `<span class="badge ${getBadgeClass(item.status)}">${statusText}</span>`;
  $("total-percent-text").textContent = progress.percent.toFixed(1) + "%";
  $("total-progress-bar").style.width = progress.percent.toFixed(1) + "%";
  $("phase-label").textContent = statusText;
  $("phase-progress-text").textContent = formatSize(progress.current) + " / " + formatSize(progress.total);
  $("phase-progress-bar").style.width = progress.percent.toFixed(1) + "%";
}

function taskEntries(items, active) {
  const entries = Object.entries(items || {}).sort((a,b)=>String((b[1]||{}).first_seen||"").localeCompare(String((a[1]||{}).first_seen||"")));
  const activeKey = active && active.source;
  if(!activeKey) return entries.slice(0, 5);
  const index = entries.findIndex(([key]) => key === activeKey);
  if(index >= 0) {
    const activeEntry = entries.splice(index, 1)[0];
    return [activeEntry, ...entries].slice(0, 5);
  }
  const progress = (active.progress || active.upload_progress || {});
  const activeItem = {
    status: active.status,
    target: active.target,
    first_seen: active.started_at || "",
    last_size: progress.total || progress.current || progress.uploaded || 0,
    size: progress.total || 0
  };
  return [[activeKey, activeItem], ...entries].slice(0, 5);
}

function historyEntries(items, active) {
  const entries = Object.entries(items || {}).sort((a,b) => {
    const av = a[1] || {};
    const bv = b[1] || {};
    const at = av.done_at || av.manual_requested_at || av.last_changed || av.first_seen || "";
    const bt = bv.done_at || bv.manual_requested_at || bv.last_changed || bv.first_seen || "";
    return String(bt).localeCompare(String(at));
  });
  const activeKey = active && active.source;
  if(!activeKey) return entries;
  const index = entries.findIndex(([key]) => key === activeKey);
  if(index >= 0) {
    const activeEntry = entries.splice(index, 1)[0];
    return [activeEntry, ...entries];
  }
  const progress = (active.progress || active.upload_progress || {});
  const activeItem = {
    status: active.status,
    target: active.target,
    first_seen: active.started_at || "",
    last_changed: active.started_at || "",
    last_size: progress.total || progress.current || progress.uploaded || 0,
    size: progress.total || 0
  };
  return [[activeKey, activeItem], ...entries];
}

function renderHistory(items, active) {
  const body = $("history-body");
  if(!body) return;
  const entries = historyEntries(items, active);
  body.innerHTML = entries.map(([key, item]) => {
    const name = key.split('/').pop();
    const status = active && active.source === key ? active.status : (item || {}).status;
    return `<tr data-history-key="${esc(key)}">
      <td title="${esc(key)}">
        <div style="font-weight: 500;">${esc(name)}</div>
        <div style="font-size: 11px; color: #94a3b8;">${esc(key)}</div>
      </td>
      <td><span class="badge ${getBadgeClass(status)}">${esc(taskStatusText(item || {}, active, key))}</span></td>
      <td style="color: var(--text-muted);">${esc(formatSize((item || {}).last_size || (item || {}).size || 0))}</td>
      <td><span class="target-text" title="${esc((item || {}).target || "-")}">${esc((item || {}).target || "-")}</span></td>
      <td><button class="rerun-btn" type="button" data-rerun-source="${esc(key)}">&#37325;&#26032;&#23553;&#35013;</button></td>
    </tr>`;
  }).join("");
}

function renderItems(items, active){
  const body=$("items-body");
  if(!body) return;
  const entries = taskEntries(items, active);
  body.innerHTML=entries.map(([key,item])=> {
    const name = key.split('/').pop();
    return `<tr data-task-key="${esc(key)}">
      <td title="${esc(key)}">
        <div style="font-weight: 500;">${esc(name)}</div>
        <div style="font-size: 11px; color: #94a3b8;">${esc(key)}</div>
      </td>
      <td>${renderTaskStatus(item, active, key)}</td>
      <td style="color: var(--text-muted);">${esc(formatSize(item.last_size||item.size||0))}</td>
      <td><span class="target-text" title="${esc(item.target||"-")}">${esc(item.target||"-")}</span></td>
    </tr>`
  }).join("");
}

function updateTaskRow(row, item, active, key) {
  const status = active && active.source === key ? active.status : (item || {}).status;
  const badge = row.querySelector("[data-task-status]");
  if(!badge) return;
  badge.className = "badge " + getBadgeClass(status);
  badge.textContent = taskStatusText(item || {}, active, key);
}

function updateItems(items, active) {
  const body = $("items-body");
  if(!body) return;
  const entries = taskEntries(items, active);
  const existingRows = new Map(Array.from(body.querySelectorAll("tr[data-task-key]")).map(row => [row.dataset.taskKey, row]));

  if (entries.length !== existingRows.size || entries.some(([key]) => !existingRows.has(key))) {
    renderItems(items, active);
    return;
  }

  entries.forEach(([key, item]) => {
    const row = existingRows.get(key);
    if(row) updateTaskRow(row, item, active, key);
  });
}

async function refresh(){
  try{
    const res=await fetch("/api/status?_="+Date.now());
    const data = await res.json();
    const state = data.state;
    
    $("last-scan").textContent = state.last_scan || "尚未扫描";
    $("task-count").textContent = Object.keys(state.items || {}).length;
    
    renderTaskSummary(state);
    updateItems(state.items, state.active);
    renderHistory(state.items, state.active);
    appendNewEvents(state.events || []);
    
    $("refresh-state").textContent = "最后同步：" + new Date().toLocaleTimeString();
  }catch(e){
    $("refresh-state").textContent = "同步失败";
  }
}

setupSettingsForm();
setupTaskActions();
const initialLogText = $("events") ? $("events").textContent : "";
if(initialLogText.trim()) renderEvents(initialLogText);
setInterval(refresh, 2000);
refresh();
})();
</script>
</body>
</html>
"""
