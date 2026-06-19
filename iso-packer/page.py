
PAGE_LOGIN = """
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ISO Packer 登录</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0f1218;
  --panel: rgba(18, 22, 30, 0.9);
  --panel-border: rgba(255,255,255,0.1);
  --text: #f8fafc;
  --muted: rgba(248,250,252,0.68);
  --accent: #e85d75;
  --accent-deep: #c73555;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  display: grid;
  place-items: center;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  color: var(--text);
  background:
    linear-gradient(145deg, rgba(7,10,15,0.94), rgba(18,22,30,0.92)),
    linear-gradient(125deg, rgba(232,93,117,0.16), transparent 42%),
    var(--bg);
}
.login-shell {
  width: min(980px, calc(100vw - 32px));
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 18px;
}
.login-hero, .login-panel {
  min-height: 560px;
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: var(--panel);
  box-shadow: 0 28px 80px rgba(0,0,0,0.34);
  overflow: hidden;
}
.login-hero {
  padding: 34px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  position: relative;
}
.login-hero::before {
  content: "";
  position: absolute;
  inset: 0;
  background:
    radial-gradient(circle at 18% 18%, rgba(255,255,255,0.08), transparent 24%),
    radial-gradient(circle at 82% 22%, rgba(232,93,117,0.18), transparent 26%);
  pointer-events: none;
}
.login-brand {
  display: flex;
  align-items: center;
  gap: 16px;
  position: relative;
  z-index: 1;
}
.login-mark {
  width: 54px;
  height: 54px;
  border-radius: 12px;
  background: linear-gradient(145deg, rgba(255,255,255,0.16), rgba(255,255,255,0.05));
  border: 1px solid rgba(255,255,255,0.12);
}
.login-brand h1 {
  margin: 0;
  font-size: 26px;
  letter-spacing: 0;
}
.login-brand p,
.login-copy p,
.login-foot {
  margin: 0;
  color: var(--muted);
  line-height: 1.6;
}
.login-copy {
  position: relative;
  z-index: 1;
  max-width: 34ch;
}
.login-copy h2 {
  margin: 18px 0 12px;
  font-size: 40px;
  line-height: 1.05;
}
.login-copy p { font-size: 14px; }
.login-foot {
  position: relative;
  z-index: 1;
  font-size: 12px;
}
.login-panel {
  padding: 34px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.login-kicker {
  margin: 0 0 10px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.login-title {
  margin: 0;
  font-size: 30px;
  line-height: 1.12;
}
.login-subtitle {
  margin: 10px 0 26px;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.7;
}
.login-alert {
  margin-bottom: 18px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(232,93,117,0.22);
  background: rgba(232,93,117,0.12);
  color: #ffd8df;
  font-size: 13px;
}
.login-form { display: grid; gap: 14px; }
.login-field label {
  display: block;
  margin-bottom: 7px;
  font-size: 12px;
  color: var(--muted);
  font-weight: 600;
}
.login-field input {
  width: 100%;
  height: 48px;
  padding: 0 14px;
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.12);
  background: rgba(255,255,255,0.04);
  color: var(--text);
  font-size: 15px;
}
.login-field input:focus {
  outline: none;
  border-color: rgba(232,93,117,0.58);
  box-shadow: 0 0 0 3px rgba(232,93,117,0.16);
}
.login-submit {
  margin-top: 6px;
  height: 48px;
  border: none;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--accent-deep), var(--accent));
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}
.login-submit:hover { filter: brightness(1.04); }
@media (max-width: 900px) {
  .login-shell { grid-template-columns: 1fr; }
  .login-hero, .login-panel { min-height: auto; }
  .login-copy h2 { font-size: 32px; }
}
</style>
</head>
<body>
  <main class="login-shell">
    <section class="login-hero" aria-hidden="true">
      <div class="login-brand">
        <svg class="login-mark" viewBox="0 0 64 64">
          <path d="M12 48 C24 38 35 25 51 13" fill="none" stroke="#f8fafc" stroke-width="4" stroke-linecap="round"/>
          <g fill="#e85d75">
            <circle cx="24" cy="26" r="5"/><circle cx="30" cy="20" r="5"/><circle cx="37" cy="26" r="5"/><circle cx="31" cy="33" r="5"/>
          </g>
        </svg>
        <div>
          <h1>ISO Packer</h1>
          <p>任务封装控制台</p>
        </div>
      </div>
      <div class="login-copy">
        <p class="login-kicker">{% if first_setup %}首次设置密码{% else %}登录控制台{% endif %}</p>
        <h2>把打包、上传和目录监控放在一个地方。</h2>
        <p>{{ login_hint|default('输入 Web 密码后继续。首次进入时会要求你先设置密码。') }}</p>
      </div>
      <div class="login-foot">ISO Packer Dashboard</div>
    </section>
    <section class="login-panel">
      {% if message|default('') %}
      <div class="login-alert">{{ message }}</div>
      {% endif %}
      <form class="login-form" method="post" action="/login">
        <input name="next" type="hidden" value="{{ next_path|default('/') }}">
        <div class="login-field">
          <label>Web 密码</label>
          <input name="web_password" type="password" autocomplete="{% if first_setup %}new-password{% else %}current-password{% endif %}" placeholder="{% if first_setup %}设置一个密码{% else %}请输入密码{% endif %}" required>
        </div>
        {% if first_setup %}
        <div class="login-field">
          <label>确认密码</label>
          <input name="web_password_confirm" type="password" autocomplete="new-password" placeholder="再次输入密码" required>
        </div>
        {% endif %}
        <button class="login-submit" type="submit">{% if first_setup %}保存并进入{% else %}登录{% endif %}</button>
      </form>
    </section>
  </main>
</body>
</html>
"""

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
.sidebar input[type=text],
.sidebar input[type=number],
.sidebar input[type=password],
.sidebar input[type=url],
.sidebar textarea,
.sidebar select {
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
.sidebar textarea {
  min-height: 70px;
  resize: vertical;
  line-height: 1.45;
}
.sidebar select { color-scheme: dark; }
.sidebar input::placeholder { color: rgba(255,255,255,0.38); }
.sidebar input:focus,
.sidebar textarea:focus,
.sidebar select:focus {
  outline: none;
  border-color: rgba(255, 216, 223, 0.72);
  background: rgba(255,255,255,0.15);
  box-shadow: 0 0 0 3px rgba(232, 93, 117, 0.2);
}
.path-picker-row {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 6px;
}
.path-picker-btn {
  border: 1px solid rgba(255,255,255,0.13);
  border-radius: 6px;
  background: rgba(255,255,255,0.12);
  color: rgba(255,255,255,0.9);
  font-size: 12px;
  font-weight: 700;
  padding: 0 10px;
  cursor: pointer;
}
.path-picker-btn:hover { background: rgba(255,255,255,0.18); }
.settings-options {
  margin: 16px 0 12px;
  border-top: 1px solid rgba(255,255,255,0.1);
  padding-top: 14px;
}
.settings-section-title {
  margin: 16px 0 10px;
  padding-top: 14px;
  border-top: 1px solid rgba(255,255,255,0.1);
  color: rgba(255,255,255,0.86);
  font-size: 12px;
  font-weight: 700;
}
.settings-help {
  margin: -3px 0 10px;
  color: rgba(255,255,255,0.48);
  font-size: 11px;
  line-height: 1.5;
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
.task-meta-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.task-meta {
  border: 1px solid #eadfd5;
  border-radius: 8px;
  padding: 10px 12px;
  background: rgba(255,255,255,0.62);
}
.task-meta-label {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
}
.task-meta-value {
  margin-top: 4px;
  color: var(--text-main);
  font-size: 14px;
  font-weight: 700;
}

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
.small-muted {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.5;
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

/* Browser */
.browser-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.browser-tabs {
  display: inline-flex;
  border: 1px solid #ddd4c8;
  border-radius: 8px;
  overflow: hidden;
  background: #fffaf4;
}
.browser-tab,
.browser-btn {
  border: none;
  background: transparent;
  color: #5f5040;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  min-height: 34px;
  padding: 0 12px;
}
.browser-tab.active {
  background: #c73555;
  color: #fff;
}
.browser-btn {
  border: 1px solid #d8cfc3;
  border-radius: 7px;
  background: #fffdfa;
}
.browser-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.browser-path {
  padding: 10px 24px;
  border-bottom: 1px solid var(--border);
  color: var(--text-muted);
  font-size: 12px;
  overflow-wrap: anywhere;
}
.browser-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.browser-kind {
  color: #246478;
  font-size: 12px;
  font-weight: 700;
}
.browser-empty {
  padding: 28px 24px;
  color: var(--text-muted);
  text-align: center;
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

/* Directory Picker */
.dir-modal {
  position: fixed;
  inset: 0;
  display: none;
  align-items: center;
  justify-content: center;
  background: rgba(12, 10, 10, 0.42);
  z-index: 1000;
  padding: 14px;
}
.dir-modal.open { display: flex; }
.dir-dialog {
  width: min(958px, calc(100vw - 28px));
  height: min(732px, calc(100vh - 28px));
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 28px 90px rgba(15, 23, 42, 0.35);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.dir-header {
  height: 64px;
  padding: 0 20px 0 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #eef0f4;
}
.dir-title { font-size: 18px; color: #252525; font-weight: 500; }
.dir-close {
  width: 38px;
  height: 38px;
  border: none;
  background: transparent;
  color: #333;
  font-size: 34px;
  line-height: 34px;
  cursor: pointer;
}
.dir-path {
  margin: 14px 20px 0;
  padding: 9px 12px;
  border: 1px solid #d9e2f6;
  border-radius: 6px;
  color: #51627f;
  background: #f7f9fe;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dir-list {
  margin: 14px 20px;
  flex: 1;
  overflow: auto;
  border-radius: 4px;
}
.dir-row {
  min-height: 40px;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 0 82px;
  color: #111827;
  cursor: pointer;
  user-select: none;
}
.dir-row:hover,
.dir-row.selected { background: #e7eefc; color: #2563eb; }
.dir-row.disabled { color: #a3a8b4; cursor: not-allowed; }
.dir-icon {
  width: 22px;
  height: 16px;
  border-radius: 3px;
  background: #88a8e8;
  position: relative;
  flex: 0 0 auto;
}
.dir-icon::before {
  content: "";
  position: absolute;
  left: 2px;
  top: -5px;
  width: 10px;
  height: 6px;
  border-radius: 3px 3px 0 0;
  background: #88a8e8;
}
.dir-footer {
  height: 58px;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 26px;
  padding: 0 28px;
  border-top: 1px solid #eef0f4;
}
.dir-action {
  border: none;
  background: transparent;
  color: #2563eb;
  font-size: 14px;
  cursor: pointer;
  padding: 8px 0;
}
.dir-empty { padding: 40px; color: #7b8497; text-align: center; }

/* Responsive */
@media (max-width: 1024px) {
  body { display: block; height: auto; overflow: auto; }
  .sidebar { width: 100%; min-height: auto; }
  .sidebar-content { overflow: visible; }
  .main { padding: 18px; }
}

@media (max-width: 640px) {
  body {
    background: var(--main-bg);
    font-size: 14px;
  }

  .sidebar {
    box-shadow: 0 10px 28px rgba(30, 24, 18, 0.14);
  }
  .sidebar::after {
    opacity: 0.28;
    right: -92px;
    top: 38px;
  }
  .sidebar-header {
    padding: 16px;
    gap: 12px;
  }
  .brand-mark {
    width: 42px;
    height: 42px;
  }
  .sidebar-header h1 { font-size: 18px; }
  .sidebar-content { padding: 14px; }
  .sidebar form {
    padding: 12px;
    box-shadow: none;
  }
  .form-group { margin-bottom: 10px; }
  .path-picker-row {
    grid-template-columns: minmax(0, 1fr) 64px;
  }
  .path-picker-btn,
  .btn,
  .rerun-btn,
  .dir-action {
    min-height: 42px;
  }

  .main {
    padding: 12px;
    gap: 12px;
  }
  .header-stats {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .stat-card {
    padding: 14px;
  }
  .stat-value { font-size: 21px; }

  .task-card {
    padding: 16px;
    gap: 14px;
  }
  .task-header {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }
  .task-title {
    width: 100%;
    font-size: 15px;
    line-height: 1.45;
    overflow-wrap: anywhere;
  }
  .task-status {
    align-self: flex-start;
  }
  .progress-info {
    gap: 6px;
    flex-wrap: wrap;
    line-height: 1.4;
  }

  .card-header {
    padding: 14px 16px;
    gap: 10px;
    align-items: flex-start;
    flex-direction: column;
  }
  .live-badge {
    min-height: 24px;
  }
  .table-wrap {
    -webkit-overflow-scrolling: touch;
  }
  table {
    min-width: 760px;
  }
  th,
  td {
    padding: 12px 16px;
  }
  .history-wrap {
    max-height: 420px;
  }
  .target-text {
    max-width: 180px;
  }
  .table-progress {
    min-width: 230px;
  }

  .logs {
    min-height: 160px;
    max-height: 260px;
    padding: 12px;
    font-size: 11px;
  }

  .dir-modal {
    padding: 8px;
    align-items: stretch;
  }
  .dir-dialog {
    width: calc(100vw - 16px);
    height: calc(100vh - 16px);
    border-radius: 8px;
  }
  .dir-header {
    height: 56px;
    padding: 0 12px 0 16px;
  }
  .dir-title { font-size: 16px; }
  .dir-close {
    width: 42px;
    height: 42px;
    font-size: 32px;
  }
  .dir-path {
    margin: 10px 12px 0;
  }
  .dir-list {
    margin: 10px 12px;
  }
  .dir-row {
    min-height: 44px;
    padding: 0 14px;
    gap: 12px;
  }
  .dir-footer {
    height: 56px;
    padding: 0 16px;
    gap: 18px;
  }
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
          <div class="path-picker-row">
            <input name="watch_dir" type="text" value="{{cfg.watch_dir}}" required>
            <button class="path-picker-btn" type="button" data-pick-dir="watch_dir">选择</button>
          </div>
        </div>
        <div class="form-group">
          <label>输出目录</label>
          <div class="path-picker-row">
            <input name="output_dir" type="text" value="{{cfg.output_dir}}" required>
            <button class="path-picker-btn" type="button" data-pick-dir="output_dir">选择</button>
          </div>
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
          <div class="path-picker-row">
            <input name="cd2_mount_root" type="text" value="{{cfg.cd2_mount_root}}">
            <button class="path-picker-btn" type="button" data-pick-dir="cd2_mount_root">选择</button>
          </div>
        </div>
        <div class="form-group">
          <label>CD2 最终 ISO 目标路径</label>
          <div class="path-picker-row">
            <input name="cd2_target_dir" type="text" value="{{cfg.cd2_target_dir}}">
            <button class="path-picker-btn" type="button" data-pick-dir="cd2_target_dir">选择</button>
          </div>
        </div>

        <div class="settings-section-title">Web 访问</div>
        <div class="settings-help">密码留空表示不修改现有值。</div>
        <div class="form-group">
          <label>Web 密码</label>
          <input name="web_password" type="password" value="" autocomplete="new-password" placeholder="留空不修改">
        </div>
        <div class="form-group">
          <label>确认 Web 密码</label>
          <input name="web_password_confirm" type="password" value="" autocomplete="new-password" placeholder="再次输入密码">
        </div>

        <div class="settings-section-title">CD2 API</div>
        <div class="checkbox-group" style="margin-top: 0;">
          <input name="cd2_api_enabled" type="checkbox" {% if cfg.cd2_api_enabled %}checked{% endif %}>
          <span>启用 CD2 API</span>
        </div>
        <div class="form-group">
          <label>CD2 认证方式</label>
          <select name="cd2_auth_mode" id="cd2-auth-mode">
            <option value="api_token" {% if cfg.cd2_auth_mode != 'password' %}selected{% endif %}>API Token</option>
            <option value="password" {% if cfg.cd2_auth_mode == 'password' %}selected{% endif %}>用户名密码</option>
          </select>
        </div>
        <div class="form-group">
          <label>CD2 API 地址</label>
          <input name="cd2_api_addr" type="text" value="{{cfg.cd2_api_addr}}" placeholder="host.docker.internal:19798">
        </div>
        <div class="form-group" id="cd2-username-group">
          <label>CD2 API 用户名</label>
          <input name="cd2_api_username" type="text" value="{{cfg.cd2_api_username}}" placeholder="API Token 模式可留空">
        </div>
        <div class="form-group">
          <label id="cd2-secret-label">CD2 API Token</label>
          <input name="cd2_api_password" type="password" value="" autocomplete="new-password" placeholder="留空不修改">
        </div>
        <div class="form-group">
          <label>CD2 轮询秒数</label>
          <input name="cd2_queue_poll_seconds" type="number" min="1" value="{{cfg.cd2_queue_poll_seconds}}">
        </div>
        <div class="form-group">
          <label>CD2 路径别名</label>
          <textarea name="cd2_path_aliases_text" spellcheck="false" placeholder="/CloudNAS/CloudDrive=/115">{{cfg.cd2_path_aliases_text}}</textarea>
          <div class="settings-help">每行一组：本地挂载路径=CD2 网盘路径。用于匹配上传进度和任务门禁。</div>
        </div>
        <div class="form-group">
          <label>上传队列匹配</label>
          <select name="cd2_upload_match_mode">
            <option value="alias_then_suffix" {% if cfg.cd2_upload_match_mode != 'alias_only' %}selected{% endif %}>路径别名优先，允许同名兜底</option>
            <option value="alias_only" {% if cfg.cd2_upload_match_mode == 'alias_only' %}selected{% endif %}>仅路径别名 / 完整路径匹配</option>
          </select>
          <div class="settings-help">严格模式会关闭同名文件兜底，适合目标目录里可能存在同名 ISO 的情况。</div>
        </div>
        <div class="form-group">
          <label>CD2 归档监控路径</label>
          <textarea name="cd2_remote_source_dirs_text" spellcheck="false" placeholder="/115/03-PT">{{cfg.cd2_remote_source_dirs_text}}</textarea>
          <div class="settings-help">类似 SA 的监控路径，每行一个 CD2 网盘源目录；自动拉取开启后，会从这里发现原盘候选并拉到本地 watch。</div>
        </div>
        <div class="form-group">
          <label>归档监控递归层级</label>
          <input name="cd2_remote_scan_depth" type="number" min="1" value="{{cfg.cd2_remote_scan_depth}}">
          <div class="settings-help">默认 1，只看监控路径下一级目录；填 2 可识别分类目录下的影片原盘。</div>
        </div>
        <label class="checkbox-group">
          <input name="cd2_manual_pull_enabled" type="checkbox" {% if cfg.cd2_manual_pull_enabled %}checked{% endif %}>
          <span>启用 CD2 手动拉取</span>
        </label>
        <label class="checkbox-group">
          <input name="cd2_auto_pull_enabled" type="checkbox" {% if cfg.cd2_auto_pull_enabled %}checked{% endif %}>
          <span>启用 CD2 自动拉取</span>
        </label>
        <div class="form-group">
          <label>每轮自动拉取任务数</label>
          <input name="cd2_auto_pull_max_tasks_per_scan" type="number" min="1" value="{{cfg.cd2_auto_pull_max_tasks_per_scan}}">
          <div class="settings-help">默认 1，调大后每次扫描可连续创建多个 CD2 拉取任务。</div>
        </div>
        <div class="form-group">
          <label>同时自动拉取任务数</label>
          <input name="cd2_auto_pull_max_active_tasks" type="number" min="1" value="{{cfg.cd2_auto_pull_max_active_tasks}}">
          <div class="settings-help">默认 1，已有自动拉取任务未完成时暂停创建新的自动拉取任务。</div>
        </div>
        <div class="form-group">
          <label>自动拉取包含关键词</label>
          <textarea name="cd2_auto_pull_include_keywords" spellcheck="false" placeholder="CHDBits&#10;UHD">{{cfg.cd2_auto_pull_include_keywords}}</textarea>
          <div class="settings-help">留空表示不过滤；每行或逗号分隔一个关键词，名称或路径命中才会自动拉取。</div>
        </div>
        <div class="form-group">
          <label>自动拉取排除关键词</label>
          <textarea name="cd2_auto_pull_exclude_keywords" spellcheck="false" placeholder="sample&#10;trailer">{{cfg.cd2_auto_pull_exclude_keywords}}</textarea>
          <div class="settings-help">名称或路径命中时跳过自动拉取；手动拉取不受影响。</div>
        </div>
        <div class="form-group">
          <label>自动拉取失败冷却秒数</label>
          <input name="cd2_auto_pull_failure_cooldown_seconds" type="number" min="0" value="{{cfg.cd2_auto_pull_failure_cooldown_seconds}}">
        </div>
        <div class="form-group">
          <label>CD2 本地拉取目录</label>
          <div class="path-picker-row">
            <input name="cd2_local_pull_dir" type="text" value="{{cfg.cd2_local_pull_dir}}">
            <button class="path-picker-btn" type="button" data-pick-dir="cd2_local_pull_dir">选择</button>
          </div>
        </div>
        <div class="form-group">
          <label>CD2 拉取目标路径</label>
          <input name="cd2_remote_pull_dest_dir" type="text" value="{{cfg.cd2_remote_pull_dest_dir}}" placeholder="/115/Download">
          <div class="settings-help">CD2 网盘路径；留空时尝试用路径别名把本地拉取目录转换为网盘路径。</div>
        </div>
        <div class="settings-section-title">CD2 事件</div>
        <label class="checkbox-group" style="margin-top: 0;">
          <input name="cd2_webhook_enabled" type="checkbox" {% if cfg.cd2_webhook_enabled %}checked{% endif %}>
          <span>启用 CD2 Webhook</span>
        </label>
        <div class="form-group">
          <label>Webhook 共享密钥</label>
          <input name="cd2_webhook_secret" type="password" value="" autocomplete="new-password" placeholder="留空不修改">
        </div>
        <div class="form-group">
          <label>事件来源</label>
          <select name="cd2_event_source">
            <option value="cd2" {% if cfg.cd2_event_source != 'symedia' %}selected{% endif %}>CD2</option>
            <option value="symedia" {% if cfg.cd2_event_source == 'symedia' %}selected{% endif %}>SA/Symedia</option>
          </select>
        </div>
        <div class="form-group">
          <label>事件防抖 (秒)</label>
          <input name="cd2_event_debounce_seconds" type="number" min="0" value="{{cfg.cd2_event_debounce_seconds}}">
        </div>
        <div class="form-group">
          <label>事件去重 TTL (秒)</label>
          <input name="cd2_event_dedupe_ttl_seconds" type="number" min="0" value="{{cfg.cd2_event_dedupe_ttl_seconds}}">
        </div>
        <div class="form-group">
          <label>CD2 确认延迟 (秒)</label>
          <input name="cd2_confirm_delay_seconds" type="number" min="0" value="{{cfg.cd2_confirm_delay_seconds}}">
        </div>
        <div class="form-group">
          <label>CD2 确认次数</label>
          <input name="cd2_confirm_stable_checks" type="number" min="1" value="{{cfg.cd2_confirm_stable_checks}}">
        </div>
        <label class="checkbox-group">
          <input name="cd2_refresh_enabled" type="checkbox" {% if cfg.cd2_refresh_enabled %}checked{% endif %}>
          <span>启用 CD2 目录刷新</span>
        </label>
        <label class="checkbox-group">
          <input name="cd2_refresh_after_source_event" type="checkbox" {% if cfg.cd2_refresh_after_source_event %}checked{% endif %}>
          <span>Webhook 后刷新源目录</span>
        </label>
        <label class="checkbox-group">
          <input name="cd2_refresh_after_transfer" type="checkbox" {% if cfg.cd2_refresh_after_transfer %}checked{% endif %}>
          <span>转移后刷新目标目录</span>
        </label>
        <div class="settings-help">Webhook 只触发重新检查，不能直接证明文件已经下载完成。</div>
        
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
          <label class="checkbox-group">
            <input name="cd2_wait_upload_complete" type="checkbox" {% if cfg.cd2_wait_upload_complete %}checked{% endif %}>
            <span>转移后等待 CD2 云端上传完成</span>
          </label>
          <input name="cd2_require_mount" type="hidden" value="1">
        </div>
        <div class="settings-help">等待上传完成需要同时启用 CD2 转移和 CD2 API，并确保 Token 可读取上传队列、路径别名能匹配目标目录。</div>
        
        <div class="button-stack">
          <button class="btn btn-primary" type="submit" data-saving-text="保存中...">保存设置</button>
          <button class="btn btn-secondary" name="scan" value="1" type="submit" data-saving-text="保存并扫描中...">保存并扫描</button>
          <button class="btn btn-secondary" id="cd2-test-btn" type="button">测试 CD2 连接</button>
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
      <div class="stat-card">
        <div class="stat-label">任务耗时</div>
        <div class="stat-value" id="task-duration">--</div>
      </div>
    </div>

    <div class="task-card" id="active-task-card" style="display: {% if state.active %}flex{% else %}none{% endif %};">
      <div class="task-header">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div class="task-title" id="active-source-name">{% if state.active %}{{state.active.source}}{% endif %}</div>
        </div>
        <div id="active-status-badge">{% if state.active %}<span class="badge badge-yellow">{{status_label(state.active.status)}}</span>{% endif %}</div>
      </div>

      <div class="task-meta-grid">
        <div class="task-meta">
          <div class="task-meta-label">已耗时</div>
          <div class="task-meta-value" id="active-duration">--</div>
        </div>
        <div class="task-meta">
          <div class="task-meta-label">CD2 上传进度</div>
          <div class="task-meta-value" id="active-cd2-upload">--</div>
        </div>
        <div class="task-meta">
          <div class="task-meta-label">阶段</div>
          <div class="task-meta-value" id="active-phase-label">--</div>
        </div>
        <div class="task-meta">
          <div class="task-meta-label">CD2 状态</div>
          <div class="task-meta-value" id="cd2-status-detail">--</div>
        </div>
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
              <th>进度</th>
              <th>耗时</th>
              <th>CD2 上传</th>
              <th>原因</th>
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
              <td class="small-muted">-</td>
              <td class="small-muted">{{item.timings.human if item.timings and item.timings.human else (item.timings.duration if item.timings and item.timings.duration else '-')}}</td>
              <td class="small-muted">{{item.cd2_upload.human if item.cd2_upload and item.cd2_upload.human else '-'}}</td>
              <td class="small-muted">{{item.error or '-'}}</td>
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
              <th>进度</th>
              <th>耗时</th>
              <th>CD2 上传</th>
              <th>原因</th>
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
              <td class="small-muted">-</td>
              <td class="small-muted">{{item.timings.human if item.timings and item.timings.human else (item.timings.duration if item.timings and item.timings.duration else '-')}}</td>
              <td class="small-muted">{{item.cd2_upload.human if item.cd2_upload and item.cd2_upload.human else '-'}}</td>
              <td class="small-muted">{{item.error or '-'}}</td>
              <td><span class="target-text" title="{{item.target or '-'}}">{{item.target or '-'}}</span></td>
              <td><button class="rerun-btn" type="button" data-rerun-source="{{key}}" {% if state.active %}disabled{% endif %}>{% if state.active %}任务运行中{% else %}重新封装{% endif %}</button></td>
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

    <div class="card">
      <div class="card-header">
        <h2>CD2 远程候选</h2>
        <div class="browser-toolbar">
          <button class="browser-btn" type="button" id="remote-refresh">刷新远程</button>
        </div>
      </div>
      <div class="browser-path" id="remote-status">未加载</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>远程路径</th>
              <th>来源目录</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="remote-body">
            <tr><td colspan="6" class="browser-empty">正在加载...</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2>目录观察</h2>
        <div class="browser-toolbar">
          <div class="browser-tabs" role="tablist" aria-label="目录根">
            <button class="browser-tab active" type="button" data-browse-root="watch">watch</button>
            <button class="browser-tab" type="button" data-browse-root="output">output</button>
            <button class="browser-tab" type="button" data-browse-root="cd2">cd2</button>
          </div>
          <button class="browser-btn" type="button" id="browser-up">返回上级</button>
          <button class="browser-btn" type="button" id="browser-refresh">刷新</button>
        </div>
      </div>
      <div class="browser-path" id="browser-path">/</div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>名称</th>
              <th>类型</th>
              <th>大小</th>
              <th>修改时间</th>
            </tr>
          </thead>
          <tbody id="browser-body">
            <tr><td colspan="4" class="browser-empty">正在加载...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <div class="dir-modal" id="dir-modal" aria-hidden="true">
    <div class="dir-dialog" role="dialog" aria-modal="true" aria-labelledby="dir-title">
      <div class="dir-header">
        <div class="dir-title" id="dir-title">选择目录</div>
        <button class="dir-close" type="button" id="dir-close" aria-label="关闭">&times;</button>
      </div>
      <div class="dir-path" id="dir-current-path">/</div>
      <div class="dir-list" id="dir-list"></div>
      <div class="dir-footer">
        <button class="dir-action" type="button" id="dir-cancel">取消</button>
        <button class="dir-action" type="button" id="dir-confirm">确认</button>
      </div>
    </div>
  </div>

<script>
(function(){
const labels={watching:"\u76d1\u63a7\u4e2d",receiving:"\u63a5\u6536\u4e2d",waiting_cd2_confirm:"\u7b49\u5f85 CD2 \u786e\u8ba4",waiting_cd2_pull:"\u7b49\u5f85 CD2 \u62c9\u53d6",waiting_stable:"\u7b49\u5f85\u7a33\u5b9a",waiting_partial:"\u7b49\u5f85\u4e0b\u8f7d\u5b8c\u6210",ready:"\u51c6\u5907\u6253\u5305",running:"\u6b63\u5728\u5c01\u88c5",done:"\u5df2\u5b8c\u6210",failed:"\u5931\u8d25",verify_failed:"\u9a8c\u8bc1\u5931\u8d25",transferring:"\u6b63\u5728\u79fb\u52a8\u5230 CD2",refreshing_cd2_dir:"\u6b63\u5728\u5237\u65b0 CD2 \u76ee\u5f55",waiting_cd2_upload:"\u7b49\u5f85 CD2 \u4e0a\u4f20\u5b8c\u6210",transfer_done:"\u5df2\u4ea4\u7ed9 CD2",transfer_failed:"\u79fb\u52a8\u5931\u8d25",removed:"\u6e90\u5df2\u79fb\u9664"};
const $=id=>document.getElementById(id);
let alertTimer;
const seenLogEvents = new Set();
let currentBrowseRoot = "watch";
let currentBrowsePath = "/";
function browseRootPath(root) {
  if(root === "watch") return document.querySelector('[name="watch_dir"]')?.value || "/";
  if(root === "output") return document.querySelector('[name="output_dir"]')?.value || "/";
  return document.querySelector('[name="cd2_target_dir"]')?.value || "/";
}
function normalizeBrowsePath(path) {
  return String(path || "/").replace(/\\/+$/, "") || "/";
}

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

function isAuthFailure(res, payload) {
  return (res && res.status === 401) || (payload && (payload.code === 401 || payload.error === "unauthorized"));
}

function goLogin() {
  window.location.href = "/login";
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const payload = await res.json().catch(() => ({}));
  if(isAuthFailure(res, payload)) {
    goLogin();
    throw new Error("unauthorized");
  }
  if(!res.ok || payload.ok === false) throw new Error(payload.message || ("HTTP " + res.status));
  return payload;
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
      let res = await fetch("/rerun", { method: "POST", body: data });
      let payload = await res.json().catch(() => ({}));
      if(isAuthFailure(res, payload)) return goLogin();
      if(res.status === 409 && /CD2/.test(payload.message || "") && confirm((payload.message || "CD2 队列仍显示未完成") + "\\n\\n文件已手动补齐的话，可以忽略 CD2 队列门禁强制封装。继续？")) {
        const forceData = new FormData();
        forceData.set("source", source);
        forceData.set("force_cd2", "1");
        res = await fetch("/rerun", { method: "POST", body: forceData });
        payload = await res.json().catch(() => ({}));
        if(isAuthFailure(res, payload)) return goLogin();
      }
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
  const cd2Mode = $("cd2-auth-mode");
  const cd2UsernameGroup = $("cd2-username-group");
  const cd2SecretLabel = $("cd2-secret-label");
  const updateCd2AuthUi = () => {
    const mode = cd2Mode ? cd2Mode.value : "api_token";
    if(cd2UsernameGroup) cd2UsernameGroup.style.display = mode === "password" ? "" : "none";
    if(cd2SecretLabel) cd2SecretLabel.textContent = mode === "password" ? "CD2 密码" : "CD2 API Token";
  };
  if(cd2Mode) {
    cd2Mode.addEventListener("change", updateCd2AuthUi);
    updateCd2AuthUi();
  }
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
      const payload = await res.json().catch(() => ({}));
      if(isAuthFailure(res, payload)) return goLogin();
      if(!res.ok) throw new Error(payload.message || ("HTTP " + res.status));
      showSettingsAlert(data.has("scan") ? "设置已保存，已开始扫描" : "设置已保存");
      refresh();
    } catch(e) {
      showSettingsAlert("设置保存失败，请检查服务状态", true);
    } finally {
      buttons.forEach(button => button.disabled = false);
      if(submitter) submitter.textContent = originalText;
    }
  });
  const cd2TestButton = $("cd2-test-btn");
  if(cd2TestButton) {
    cd2TestButton.addEventListener("click", async () => {
      const originalText = cd2TestButton.textContent;
      cd2TestButton.disabled = true;
      cd2TestButton.textContent = "测试中...";
      try {
        const payload = await fetchJson("/api/cd2/test", { method: "POST", body: new FormData(form) });
        showSettingsAlert(payload.message || "CD2 连接成功");
        refresh();
      } catch(e) {
        showSettingsAlert(e.message || "CD2 连接失败", true);
      } finally {
        cd2TestButton.disabled = false;
        cd2TestButton.textContent = originalText;
      }
    });
  }
}

function getBadgeClass(status) {
  if (['done', 'transfer_done'].includes(status)) return 'badge-green';
  if (['failed', 'verify_failed', 'transfer_failed'].includes(status)) return 'badge-red';
  if (['running', 'transferring', 'refreshing_cd2_dir', 'waiting_cd2_upload', 'waiting_cd2_confirm', 'waiting_cd2_pull'].includes(status)) return 'badge-yellow';
  if (['skipped', 'removed'].includes(status)) return 'badge-gray';
  return 'badge-blue';
}

function label(s){return labels[s]||s||"未知"}
  function esc(v){return String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]))}

let dirPickerTarget = null;
let dirPickerPath = "/";

function dirname(path) {
  const value = String(path || "/").replace(/\\/+$/, "") || "/";
  if(value === "@roots") return "@roots";
  if(value === "/") return "/";
  const index = value.lastIndexOf("/");
  return index <= 0 ? "/" : value.slice(0, index);
}

function closeDirectoryPicker() {
  const modal = $("dir-modal");
  if(modal) {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
  }
  dirPickerTarget = null;
}

function setDirectoryValue() {
  if(!dirPickerTarget) return;
  dirPickerTarget.value = dirPickerPath || "/";
  closeDirectoryPicker();
}

async function loadDirectory(path) {
  const list = $("dir-list");
  const current = $("dir-current-path");
  if(list) list.innerHTML = `<div class="dir-empty">\u6b63\u5728\u8bfb\u53d6...</div>`;
  try {
    const scope = dirPickerTarget?.name || "";
    const payload = await fetchJson("/api/directories?scope=" + encodeURIComponent(scope) + "&path=" + encodeURIComponent(path || "@roots"));
    dirPickerPath = payload.path || "@roots";
    if(current) current.textContent = payload.display_path || dirPickerPath;
    const rows = [];
    if(payload.parent) {
      rows.push(`<div class="dir-row" data-dir-path="${esc(payload.parent)}"><span class="dir-icon"></span><span>..</span></div>`);
    }
    (payload.entries || []).forEach(entry => {
      rows.push(`<div class="dir-row${entry.readable ? "" : " disabled"}" data-dir-path="${esc(entry.path)}"><span class="dir-icon"></span><span>${esc(entry.name)}</span></div>`);
    });
    if(list) list.innerHTML = rows.join("") || `<div class="dir-empty">\u6ca1\u6709\u53ef\u9009\u5b50\u76ee\u5f55</div>`;
  } catch(e) {
    if(list) list.innerHTML = `<div class="dir-empty">${esc(e.message || "\u8bfb\u53d6\u76ee\u5f55\u5931\u8d25")}</div>`;
  }
}

function openDirectoryPicker(input) {
  dirPickerTarget = input;
  const modal = $("dir-modal");
  if(!modal) return;
  modal.classList.add("open");
  modal.setAttribute("aria-hidden", "false");
  const startPath = input.value || input.getAttribute("value") || "@roots";
  loadDirectory(startPath);
}

function setupDirectoryPicker() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-pick-dir]");
    if(button) {
      const input = document.querySelector(`[name="${button.dataset.pickDir}"]`);
      if(input) openDirectoryPicker(input);
      return;
    }
    const row = event.target.closest("[data-dir-path]");
    if(row && !row.classList.contains("disabled")) {
      loadDirectory(row.dataset.dirPath);
    }
  });
  const close = $("dir-close");
  const cancel = $("dir-cancel");
  const confirm = $("dir-confirm");
  if(close) close.addEventListener("click", closeDirectoryPicker);
  if(cancel) cancel.addEventListener("click", closeDirectoryPicker);
  if(confirm) confirm.addEventListener("click", setDirectoryValue);
  const modal = $("dir-modal");
  if(modal) {
    modal.addEventListener("click", (event) => {
      if(event.target === modal) closeDirectoryPicker();
    });
  }
  document.addEventListener("keydown", (event) => {
    if(event.key === "Escape" && $("dir-modal")?.classList.contains("open")) closeDirectoryPicker();
  });
}

function formatDuration(value) {
  if(value == null || value === "") return "--";
  if(typeof value === "string" && value.trim()) return value;
  const seconds = Number(value);
  if(!Number.isFinite(seconds) || seconds < 0) return "--";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if(h) return `${h}时${String(m).padStart(2, "0")}分${String(s).padStart(2, "0")}秒`;
  if(m) return `${m}分${String(s).padStart(2, "0")}秒`;
  return `${s}秒`;
}

function pickTiming(item) {
  const timings = (item && item.timings) || {};
  return timings.human || timings.duration_human || timings.duration_text || formatDuration(timings.duration ?? timings.seconds ?? timings.elapsed ?? timings.total_seconds);
}

function pickCd2Upload(item) {
  const up = (item && item.cd2_upload) || {};
  if(typeof up === "string" || typeof up === "number") return String(up);
  if(up.human) return up.human;
  const percent = up.percent != null ? Number(up.percent) : null;
  const current = up.current ?? up.uploaded ?? 0;
  const total = up.total ?? up.size ?? 0;
  if(percent != null && Number.isFinite(percent)) {
    const body = `${Math.max(0, Math.min(100, percent)).toFixed(1)}%`;
    return total ? `${body} (${formatSize(current)} / ${formatSize(total)})` : body;
  }
  if(current || total) return `${formatSize(current)} / ${formatSize(total)}`;
  return "--";
}

function pickErrorReason(item) {
  const value = (item && (item.error || item.reason || item.last_error)) || "";
  return value ? String(value) : "-";
}

function rowItem(item, active, key) {
  if(active && active.source === key) {
    return {
      ...(item || {}),
      status: active.status,
      target: active.target || (item || {}).target,
      progress: active.progress || (item || {}).progress || {},
      timings: active.timings || (item || {}).timings || {},
      cd2_upload: active.cd2_upload || (item || {}).cd2_upload || {},
      error: active.error || "",
      reason: active.reason || "",
      last_error: active.last_error || ""
    };
  }
  return item || {};
}

function formatCd2Status(status) {
  if(!status) return "--";
  const parts = [];
  if(status.auth_mode) parts.push(status.auth_mode === "password" ? "用户名密码" : "API Token");
  if(status.human) parts.push(status.human);
  if(!status.human) {
    if(status.upload_count != null) parts.push(String(status.upload_count) + " 项上传");
    if(status.download_count != null) parts.push(String(status.download_count) + " 项下载");
    if(status.copy_task_count != null) parts.push(String(status.copy_task_count) + " 项复制");
  }
  if(status.last_success_at) parts.push("最后成功 " + status.last_success_at);
  if(status.last_error) parts.push("错误 " + status.last_error);
  if(!parts.length && status.checked_at) parts.push("最后检查 " + status.checked_at);
  return parts.join(" / ") || "--";
}

function formatCd2AutoPullStatus(cd2State) {
  const result = cd2State && cd2State.auto_pull && cd2State.auto_pull.last_result;
  if(!result) return "";
  if(result.created) {
    if(Number(result.created_count || 0) > 1) return "自动拉取本轮已创建 " + result.created_count + " 个任务";
    return "自动拉取已创建 " + (result.source_path || result.local_path || "");
  }
  if(result.candidate_count != null) {
    const suffix = result.skipped && result.skipped.length ? "，跳过 " + result.skipped.length + " 个" : "";
    return "自动拉取未创建，候选 " + result.candidate_count + " 个" + suffix + (result.message ? "，" + result.message : "");
  }
  return result.message ? "自动拉取：" + result.message : "";
}

function statusBadgeText(status, item={}) {
  if (status === "running") return "\u6b63\u5728\u5c01\u88c5";
  if (status === "transferring") return "\u6b63\u5728\u79fb\u52a8\u5230 CD2";
  if (status === "refreshing_cd2_dir") return "\u6b63\u5728\u5237\u65b0 CD2 \u76ee\u5f55";
  if (status === "waiting_cd2_upload") return "\u7b49\u5f85 CD2 \u4e0a\u4f20\u5b8c\u6210";
  if (status === "transfer_done") return "\u5df2\u4ea4\u7ed9 CD2";
  if (status === "done") return item.pack_iso === false ? "\u8df3\u8fc7\u5c01\u88c5" : "\u5df2\u5c01\u88c5 ISO";
  if (status === "skipped") return "\u8df3\u8fc7\u5c01\u88c5";
  return label(status);
}

function phaseStatusText(active) {
  const progress = (active && (active.progress || {})) || {};
  const phase = progress.phase || "";
  const status = active && active.status;
  if (phase === "packing" || status === "running") return "\u6b63\u5728\u5c01\u88c5";
  if (phase === "transfer" || status === "transferring") return "\u6b63\u5728\u79fb\u52a8\u5230 CD2";
  if (phase === "refresh_cd2_dir" || status === "refreshing_cd2_dir") return "\u6b63\u5728\u5237\u65b0 CD2 \u76ee\u5f55";
  if (status === "waiting_cd2_upload") return "\u7b49\u5f85 CD2 \u4e0a\u4f20\u5b8c\u6210";
  return statusBadgeText(status, active || {});
}

function formatSize(value){
  let size=Number(value||0);
  if(size >= 1073741824) return (size/1073741824).toFixed(2)+" GB";
  if(size >= 1048576) return (size/1048576).toFixed(2)+" MB";
  return (size/1024).toFixed(2)+" KB";
}

function getTaskProgress(item, active, key) {
  const activeProgress = active && active.source === key ? (active.progress || {}) : ((item || {}).progress || {});
  if ((item || {}).status === "waiting_cd2_upload") {
    const up = (item && item.cd2_upload) || {};
    const current = Number(up.current ?? up.uploaded ?? 0);
    const total = Number(up.total ?? up.size ?? 0);
    let percent = up.percent != null ? Number(up.percent) : (total > 0 ? (current / total) * 100 : 0);
    if (!Number.isFinite(percent)) percent = 0;
    return { current, total, percent: Math.max(0, Math.min(100, percent)) };
  }
  const doneStatuses = ['done', 'transfer_done'];
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

function renderTableProgress(item, active, key) {
  item = rowItem(item, active, key);
  const status = (item || {}).status;
  const visibleStatuses = ["running", "transferring", "refreshing_cd2_dir", "waiting_cd2_upload", "done", "transfer_done"];
  if(!visibleStatuses.includes(status)) return `<span class="small-muted">--</span>`;
  const progress = getTaskProgress(item, active, key);
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  const hasTotal = Number(progress.total || 0) > 0;
  const meta = item.status === "waiting_cd2_upload"
    ? pickCd2Upload(item)
    : (hasTotal ? `${formatSize(progress.current)} / ${formatSize(progress.total)}` : "--");
  return `<div class="table-progress" data-task-progress>
    <div class="table-progress-track"><div class="table-progress-fill" style="width: ${percent.toFixed(1)}%"></div></div>
    <div class="table-progress-meta">
      <span>${esc(meta)}</span>
      <span class="table-progress-percent">${percent.toFixed(1)}%</span>
    </div>
  </div>`;
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
  const match = String(eventText || "").match(/^\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})\\]/);
  return match ? new Date(match[1].replace(" ", "T")).getTime() : 0;
}

function normalizeEvents(events) {
  const text = Array.isArray(events) ? events.join("\\n") : String(events || "");
  return text
    .replace(/\\s*(?=\\[\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}\\])/g, "\\n")
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
    const match = String(eventText).match(/^\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})\\]\\s*(.*)$/);
    const time = match ? match[1] : "";
    const message = match ? match[2] : eventText;
    return `<div class="log-line"><span class="log-time">${esc(time ? "[" + time + "] " : "")}</span><span class="log-message">${esc(message)}</span></div>`;
  }).join("");
}

function createLogLine(eventText) {
  const line = document.createElement("div");
  line.className = "log-line";
  const match = String(eventText).match(/^\\[(\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2})\\]\\s*(.*)$/);
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
    if($("active-duration")) $("active-duration").textContent = "--";
    if($("active-cd2-upload")) $("active-cd2-upload").textContent = "--";
    return;
  }
  card.style.display = "flex";
  
  const p = active.progress || {};
  const percent = Math.max(0, Math.min(100, Number(p.percent || 0)));
  const phase = phaseStatusText(active);
  
  $("active-source-name").textContent = active.source.split('/').pop();
  $("active-status-badge").innerHTML = `<span class="badge ${getBadgeClass(active.status)}">${phase}</span>`;
  $("active-phase-label").textContent = phase;
  $("active-duration").textContent = pickTiming(active);
  $("active-cd2-upload").textContent = pickCd2Upload(active);
  $("task-duration").textContent = pickTiming(active);
  
  let totalPercent = percent;
  if (active.status === "transferring") {
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
  $("active-phase-label").textContent = statusText;
  $("active-duration").textContent = pickTiming(item);
  $("active-cd2-upload").textContent = pickCd2Upload(item);
  $("task-duration").textContent = pickTiming(item);
  $("total-percent-text").textContent = progress.percent.toFixed(1) + "%";
  $("total-progress-bar").style.width = progress.percent.toFixed(1) + "%";
  $("phase-label").textContent = statusText;
  $("phase-progress-text").textContent = item.status === "waiting_cd2_upload" ? pickCd2Upload(item) : formatSize(progress.current) + " / " + formatSize(progress.total);
  $("phase-progress-bar").style.width = progress.percent.toFixed(1) + "%";
}

function taskEntries(items, active) {
  const entries = Object.entries(items || {}).sort((a,b)=>String((b[1]||{}).first_seen||"").localeCompare(String((a[1]||{}).first_seen||"")));
  const activeKey = active && active.source;
  if(!activeKey) return entries.slice(0, 5);
  const index = entries.findIndex(([key]) => key === activeKey);
  if(index >= 0) {
    const [key, item] = entries.splice(index, 1)[0];
    return [[key, rowItem(item, active, key)], ...entries].slice(0, 5);
  }
  const progress = (active.progress || {});
  const activeItem = {
    status: active.status,
    target: active.target,
    first_seen: active.started_at || "",
    last_size: progress.total || progress.current || progress.uploaded || 0,
    size: progress.total || 0,
    timings: active.timings || {},
    cd2_upload: active.cd2_upload || {}
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
    const [key, item] = entries.splice(index, 1)[0];
    return [[key, rowItem(item, active, key)], ...entries];
  }
  const progress = (active.progress || {});
  const activeItem = {
    status: active.status,
    target: active.target,
    first_seen: active.started_at || "",
    last_changed: active.started_at || "",
    last_size: progress.total || progress.current || progress.uploaded || 0,
    size: progress.total || 0,
    timings: active.timings || {},
    cd2_upload: active.cd2_upload || {}
  };
  return [[activeKey, activeItem], ...entries];
}

function renderHistory(items, active) {
  const body = $("history-body");
  if(!body) return;
  const entries = historyEntries(items, active);
  body.innerHTML = entries.map(([key, item]) => {
    const name = key.split('/').pop();
    item = rowItem(item, active, key);
    const status = item.status;
    return `<tr data-history-key="${esc(key)}">
      <td title="${esc(key)}">
        <div style="font-weight: 500;">${esc(name)}</div>
        <div style="font-size: 11px; color: #94a3b8;">${esc(key)}</div>
      </td>
      <td><span class="badge ${getBadgeClass(status)}">${esc(taskStatusText(item, active, key))}</span></td>
      <td style="color: var(--text-muted);">${esc(formatSize(item.last_size || item.size || 0))}</td>
      <td>${renderTableProgress(item, active, key)}</td>
      <td class="small-muted">${esc(pickTiming(item))}</td>
      <td class="small-muted">${esc(pickCd2Upload(item))}</td>
      <td class="small-muted">${esc(pickErrorReason(item))}</td>
      <td><span class="target-text" title="${esc(item.target || "-")}">${esc(item.target || "-")}</span></td>
      <td><button class="rerun-btn" type="button" data-rerun-source="${esc(key)}"${active ? " disabled" : ""}>${active ? "任务运行中" : "重新封装"}</button></td>
    </tr>`;
  }).join("");
}

function renderItems(items, active){
  const body=$("items-body");
  if(!body) return;
  const entries = taskEntries(items, active);
  body.innerHTML=entries.map(([key,item])=> {
    item = rowItem(item, active, key);
    const name = key.split('/').pop();
    return `<tr data-task-key="${esc(key)}">
      <td title="${esc(key)}">
        <div style="font-weight: 500;">${esc(name)}</div>
        <div style="font-size: 11px; color: #94a3b8;">${esc(key)}</div>
      </td>
      <td>${renderTaskStatus(item, active, key)}</td>
      <td style="color: var(--text-muted);">${esc(formatSize(item.last_size||item.size||0))}</td>
      <td>${renderTableProgress(item, active, key)}</td>
      <td class="small-muted">${esc(pickTiming(item || {}))}</td>
      <td class="small-muted">${esc(pickCd2Upload(item || {}))}</td>
      <td class="small-muted">${esc(pickErrorReason(item || {}))}</td>
      <td><span class="target-text" title="${esc(item.target||"-")}">${esc(item.target||"-")}</span></td>
    </tr>`
  }).join("");
}

function updateTaskRow(row, item, active, key) {
  item = rowItem(item, active, key);
  const status = item.status;
  const badge = row.querySelector("[data-task-status]");
  if(!badge) return;
  badge.className = "badge " + getBadgeClass(status);
  badge.textContent = taskStatusText(item, active, key);
  const cells = row.querySelectorAll("td");
  if(cells[3]) cells[3].innerHTML = renderTableProgress(item, active, key);
  if(cells[4]) cells[4].textContent = pickTiming(item);
  if(cells[5]) cells[5].textContent = pickCd2Upload(item);
  if(cells[6]) cells[6].textContent = pickErrorReason(item);
  const targetText = cells[7] ? cells[7].querySelector(".target-text") : null;
  if(targetText) {
    const target = (item || {}).target || "-";
    targetText.textContent = target;
    targetText.title = target;
  }
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

function updateBrowserRows(items) {
  const body = $("browser-body");
  if(!body) return;
  if(!items || !items.length) {
    body.innerHTML = `<tr><td colspan="4" class="browser-empty">没有内容</td></tr>`;
    return;
  }
  body.innerHTML = items.map(item => {
    const isDir = item.is_dir === true || item.type === "dir" || item.type === "directory";
    const name = item.name || item.filename || item.path || "-";
    const type = isDir ? "目录" : (item.type || "文件");
    const size = isDir ? "-" : (item.size != null ? formatSize(item.size) : "-");
    const mtime = item.mtime || item.modified_at || item.modified || "-";
    return `<tr${isDir ? ' data-browser-dir="1"' : ""} data-browser-path="${esc(item.path || "")}">
      <td><span class="browser-name">${esc(name)}</span></td>
      <td><span class="browser-kind">${esc(type)}</span></td>
      <td style="color: var(--text-muted);">${esc(size)}</td>
      <td style="color: var(--text-muted);">${esc(mtime)}</td>
    </tr>`;
  }).join("");
}

function updateRemoteRows(items, pullEnabled=false) {
  const body = $("remote-body");
  if(!body) return;
  if(!items || !items.length) {
    body.innerHTML = `<tr><td colspan="6" class="browser-empty">没有远程原盘候选</td></tr>`;
    return;
  }
  body.innerHTML = items.map(item => {
    const path = item.path || "";
    const status = item.pull_status_label || "新候选";
    const action = pullEnabled
      ? `<button class="browser-btn" type="button" data-remote-pull-path="${esc(path)}">拉取</button>`
      : `<span class="browser-kind">未启用</span>`;
    return `<tr>
      <td><span class="browser-name">${esc(item.name || "-")}</span></td>
      <td><span class="browser-kind">${esc(item.disc_type || "-")}</span></td>
      <td><span class="target-text" title="${esc(item.path || "-")}">${esc(item.path || "-")}</span></td>
      <td><span class="target-text" title="${esc(item.root || "-")}">${esc(item.root || "-")}</span></td>
      <td><span class="browser-kind" title="${esc(item.pull_error || item.local_path || "")}">${esc(status)}</span></td>
      <td>${action}</td>
    </tr>`;
  }).join("");
}

async function pullRemoteCandidate(button) {
  const path = button.dataset.remotePullPath || "";
  if(!path) return;
  if(!confirm("确认让 CD2 拉取这个远程原盘？")) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "提交中...";
  try {
    const data = new FormData();
    data.set("path", path);
    const payload = await fetchJson("/api/cd2/pull", { method: "POST", body: data });
    showSettingsAlert(payload.message || "CD2 拉取任务已创建");
    loadRemoteCandidates(true);
    loadBrowser("watch", "/");
    refresh();
  } catch(e) {
    showSettingsAlert(e.message || "CD2 拉取失败", true);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function loadRemoteCandidates(force=false) {
  const status = $("remote-status");
  if(status) status.textContent = force ? "正在强制刷新..." : "正在读取远程目录...";
  try {
    const payload = await fetchJson("/api/cd2/remote-candidates?force=" + (force ? "1" : "0") + "&_=" + Date.now());
    updateRemoteRows(payload.candidates || [], payload.manual_pull_enabled === true);
    const parts = [payload.message || "远程目录已读取"];
    parts.push(payload.auto_pull_enabled === true ? "自动拉取已启用" : "自动拉取未启用");
    if(payload.checked_at) parts.push(payload.checked_at);
    if(payload.errors && payload.errors.length) parts.push(String(payload.errors.length) + " 个目录读取失败");
    if(status) status.textContent = parts.join(" / ");
  } catch(e) {
    updateRemoteRows([]);
    if(status) status.textContent = e.message || "读取远程目录失败";
  }
}

async function loadBrowser(root = currentBrowseRoot, path = currentBrowsePath) {
  currentBrowseRoot = root || "watch";
  if(!path || path === "/") {
    currentBrowsePath = browseRootPath(currentBrowseRoot);
  } else {
    currentBrowsePath = path;
  }
  document.querySelectorAll("[data-browse-root]").forEach(tab => {
    tab.classList.toggle("active", tab.dataset.browseRoot === currentBrowseRoot);
  });
  const pathNode = $("browser-path");
  if(pathNode) pathNode.textContent = `${currentBrowseRoot}:${currentBrowsePath}`;
  try {
    const payload = await fetchJson("/api/browse?root=" + encodeURIComponent(currentBrowseRoot) + "&path=" + encodeURIComponent(currentBrowsePath));
    currentBrowsePath = payload.path || currentBrowsePath || "/";
    if(pathNode) pathNode.textContent = `${currentBrowseRoot}:${currentBrowsePath}`;
    updateBrowserRows(payload.entries || payload.items || []);
  } catch(e) {
    const body = $("browser-body");
    if(body) body.innerHTML = `<tr><td colspan="4" class="browser-empty">${esc(e.message || "读取目录失败")}</td></tr>`;
  }
}

function setupBrowser() {
  document.addEventListener("click", (event) => {
    const pullButton = event.target.closest("[data-remote-pull-path]");
    if(pullButton) {
      pullRemoteCandidate(pullButton);
      return;
    }
    const tab = event.target.closest("[data-browse-root]");
    if(tab) {
      loadBrowser(tab.dataset.browseRoot || "watch", "/");
      return;
    }
    const row = event.target.closest("#browser-body tr[data-browser-path]");
    if(row && row.dataset.browserDir === "1" && row.dataset.browserPath) {
      loadBrowser(currentBrowseRoot, row.dataset.browserPath);
    }
  });
  const up = $("browser-up");
  const refreshButton = $("browser-refresh");
  const remoteRefreshButton = $("remote-refresh");
  if(up) up.addEventListener("click", () => {
    const current = normalizeBrowsePath(currentBrowsePath);
    const rootPath = normalizeBrowsePath(browseRootPath(currentBrowseRoot));
    if(current === "/" || current === rootPath) return;
    const index = current.lastIndexOf("/");
    loadBrowser(currentBrowseRoot, index <= 0 ? "/" : current.slice(0, index));
  });
  if(refreshButton) refreshButton.addEventListener("click", () => loadBrowser(currentBrowseRoot, currentBrowsePath));
  if(remoteRefreshButton) remoteRefreshButton.addEventListener("click", () => loadRemoteCandidates(true));
}

async function refresh(){
  try{
    const data = await fetchJson("/api/status?_="+Date.now());
    const state = data.state || data;
    
    $("last-scan").textContent = state.last_scan || "尚未扫描";
    $("task-count").textContent = Object.keys(state.items || {}).length;
    const firstItem = Object.values(state.items || {})[0];
    $("task-duration").textContent = state.active ? pickTiming(state.active) : (firstItem ? pickTiming(firstItem) : "--");
    
    renderTaskSummary(state);
    updateItems(state.items, state.active);
    renderHistory(state.items, state.active);
    appendNewEvents(state.events || []);
    if(state.cd2_status && !state.active && !firstItem && $("active-cd2-upload")) {
      $("active-cd2-upload").textContent = state.cd2_status.human || state.cd2_status.status || "--";
    }
    if($("cd2-status-detail")) {
      const cd2Parts = [formatCd2Status(state.cd2_status || data.cd2_status)];
      const autoPullText = formatCd2AutoPullStatus(state.cd2 || {});
      if(autoPullText) cd2Parts.push(autoPullText);
      $("cd2-status-detail").textContent = cd2Parts.filter(Boolean).join(" / ");
    }
    if(!state.active && firstItem && $("active-duration")) {
      $("active-duration").textContent = pickTiming(firstItem);
    }
    
    $("refresh-state").textContent = "最后同步：" + new Date().toLocaleTimeString();
  }catch(e){
    $("refresh-state").textContent = "同步失败";
  }
}

setupSettingsForm();
setupTaskActions();
setupDirectoryPicker();
setupBrowser();
const initialLogText = $("events") ? $("events").textContent : "";
if(initialLogText.trim()) renderEvents(initialLogText);
setInterval(refresh, 2000);
loadBrowser();
loadRemoteCandidates();
refresh();
})();
</script>
</body>
</html>
"""
