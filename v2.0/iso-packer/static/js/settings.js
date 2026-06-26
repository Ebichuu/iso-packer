(function () {
  const DIRECTORY_ROOT = "@roots";
  const helper = () => window.IsoPacker;

  document.addEventListener("DOMContentLoaded", () => {
    const form = helper().qs("#system-config-form");
    if (!form) return;

    const dirtyState = helper().qs("#settings-dirty-state");
    let dirty = false;
    function setDirty(value) {
      dirty = value;
      if (dirtyState) dirtyState.textContent = dirty ? "有未保存修改" : "未修改";
    }

    form.addEventListener("input", () => setDirty(true));
    form.addEventListener("change", () => setDirty(true));
    form.addEventListener("reset", () => window.setTimeout(() => setDirty(false), 0));
    form.addEventListener("submit", () => setDirty(false));
    helper().qs("[data-settings-reset]")?.addEventListener("click", () => {
      window.location.reload();
    });
    window.addEventListener("beforeunload", (event) => {
      if (!dirty) return;
      event.preventDefault();
      event.returnValue = "";
    });

    const authMode = form.elements.cd2_auth_mode;
    const identityLabel = helper().qs("#cd2-identity-label");
    const identityHelp = helper().qs("#cd2-identity-help");
    const secretLabel = helper().qs("#cd2-secret-label");
    const testButton = helper().qs("#cd2-test-btn");
    const testResult = helper().qs("#cd2-test-result");
    const tmdbTestButton = helper().qs("[data-tmdb-test]");
    const tmdbTestResult = helper().qs("#tmdb-test-result");

    function updateCd2AuthLabels() {
      if (!authMode) return;
      const passwordMode = authMode.value === "password";
      if (identityLabel) identityLabel.textContent = passwordMode ? "CD2 用户名" : "Token 备注 / 用户名（可空）";
      if (identityHelp) identityHelp.textContent = passwordMode
        ? "账号密码模式下这里必须填写 CD2 登录用户名。"
        : "API Token 模式下这里可留空；Token 请填到下方密钥框。";
      if (secretLabel) secretLabel.textContent = passwordMode ? "CD2 密码" : "CD2 API Token";
    }

    function showCd2TestResult(message, isError) {
      if (!testResult) return;
      testResult.textContent = message || (isError ? "CD2 连接失败" : "CD2 连接成功");
      testResult.className = isError
        ? "mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[11px] font-bold text-red-700"
        : "mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] font-bold text-emerald-700";
      testResult.classList.remove("hidden");
    }

    async function testCd2Connection() {
      if (!testButton) return;
      const originalText = testButton.textContent;
      testButton.disabled = true;
      testButton.textContent = "正在测试...";
      showCd2TestResult("正在使用当前表单配置测试 CD2 连接。", false);
      try {
        const payload = await helper().fetchJson("/api/cd2/test", {
          method: "POST",
          body: new FormData(form),
        });
        showCd2TestResult(payload.message || "CD2 连接成功", false);
      } catch (error) {
        showCd2TestResult(error.message || "CD2 连接失败，请检查地址、认证方式和登录信息。", true);
      } finally {
        testButton.disabled = false;
        testButton.textContent = originalText;
      }
    }

    function showTmdbTestResult(message, isError) {
      if (!tmdbTestResult) return;
      tmdbTestResult.textContent = message || (isError ? "TMDB 测试失败" : "TMDB 连接正常");
      tmdbTestResult.className = isError
        ? "text-[11px] font-bold leading-5 text-red-700"
        : "text-[11px] font-bold leading-5 text-emerald-700";
    }

    async function testTmdbConnection() {
      if (!tmdbTestButton) return;
      const originalText = tmdbTestButton.textContent;
      tmdbTestButton.disabled = true;
      tmdbTestButton.textContent = "正在测试...";
      showTmdbTestResult("正在使用当前表单配置测试 TMDB。", false);
      try {
        const payload = await helper().fetchJson("/api/tmdb/test", {
          method: "POST",
          body: new FormData(form),
        });
        const sizes = Array.isArray(payload.poster_sizes) ? payload.poster_sizes.slice(0, 3).join(" / ") : "";
        showTmdbTestResult(sizes ? `${payload.message || "TMDB 连接正常"} · 海报尺寸 ${sizes}` : (payload.message || "TMDB 连接正常"), false);
      } catch (error) {
        showTmdbTestResult(error.message || "TMDB 测试失败，请检查域名和 API Token。", true);
      } finally {
        tmdbTestButton.disabled = false;
        tmdbTestButton.textContent = originalText;
      }
    }

    updateCd2AuthLabels();
    if (authMode) authMode.addEventListener("change", updateCd2AuthLabels);
    if (testButton) testButton.addEventListener("click", testCd2Connection);
    if (tmdbTestButton) tmdbTestButton.addEventListener("click", testTmdbConnection);

    const picker = helper().qs("#directory-picker");
    if (!picker) return;
    const pickerTitle = helper().qs("#directory-picker-title");
    const pickerPath = helper().qs("#directory-picker-path");
    const pickerList = helper().qs("#directory-picker-list");
    const pickerUp = helper().qs("#directory-picker-up");
    const pickerUse = helper().qs("#directory-picker-use");
    const pickerState = {
      target: null,
      scope: "",
      provider: "local",
      append: false,
      valueMode: "",
      path: DIRECTORY_ROOT,
      parent: null,
      lastFocus: null,
    };

    function renderPickerMessage(text) {
      if (!pickerList) return;
      const empty = document.createElement("div");
      empty.className = "empty-state slim";
      empty.textContent = text;
      pickerList.replaceChildren(empty);
    }

    function renderDirectoryEntries(payload) {
      pickerState.path = payload.path || DIRECTORY_ROOT;
      pickerState.parent = payload.parent || null;
      helper().setText(pickerPath, payload.display_path || pickerState.path);
      if (pickerUp) pickerUp.disabled = !pickerState.parent;
      if (pickerUse) pickerUse.disabled = pickerState.path === DIRECTORY_ROOT || pickerState.path === "/";
      if (!pickerList) return;

      helper().clearNode(pickerList);
      const entries = Array.isArray(payload.entries) ? payload.entries : [];
      if (!entries.length) {
        renderPickerMessage("没有可选子目录。");
        return;
      }

      entries.forEach((entry) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "directory-row";
        row.dataset.dirPath = entry.path || "";
        row.disabled = entry.readable === false;

        const kind = document.createElement("span");
        kind.className = "file-kind";
        kind.textContent = "DIR";

        const main = document.createElement("span");
        main.className = "directory-main";
        const name = document.createElement("strong");
        name.textContent = entry.name || entry.path || "未命名目录";
        const path = document.createElement("small");
        path.textContent = entry.path || "";
        main.append(name, path);

        const state = document.createElement("span");
        state.className = "soft-pill";
        state.textContent = entry.readable === false ? "不可读" : "可进入";

        row.append(kind, main, state);
        pickerList.appendChild(row);
      });
    }

    async function loadDirectory(path, fallbackToRoots) {
      renderPickerMessage("正在读取目录。");
      try {
        const targetPath = path || (pickerState.provider === "cd2" ? "/" : DIRECTORY_ROOT);
        const payload = pickerState.provider === "cd2"
          ? await helper().fetchJson(`/api/cd2/directories?path=${encodeURIComponent(targetPath)}`, {
              method: "POST",
              body: new FormData(form),
            })
          : await helper().fetchJson(`/api/directories?scope=${encodeURIComponent(pickerState.scope)}&path=${encodeURIComponent(targetPath)}`);
        renderDirectoryEntries(payload);
      } catch (error) {
        const rootPath = pickerState.provider === "cd2" ? "/" : DIRECTORY_ROOT;
        if (fallbackToRoots && path !== rootPath) {
          await loadDirectory(rootPath, false);
          helper().notify(error.message || "当前目录不可读取，已回到可选目录。", true);
          return;
        }
        renderPickerMessage(error.message || "目录读取失败。");
      }
    }

    function closePicker() {
      picker.classList.add("hidden");
      document.body.classList.remove("has-modal");
      if (pickerState.lastFocus) pickerState.lastFocus.focus();
    }

    function pickerValueForTarget() {
      return pickerState.path;
    }

    function openPicker(button) {
      const target = document.getElementById(button.dataset.dirTarget || "");
      if (!target) return;
      const field = button.closest(".field") || button.closest(".space-y-1\\.5") || button.parentElement;
      const label = field && field.querySelector("label");
      pickerState.target = target;
      pickerState.scope = button.dataset.dirScope || button.dataset.dirTarget || "";
      pickerState.provider = button.dataset.dirProvider || "local";
      pickerState.append = button.dataset.dirAppend === "true";
      pickerState.path = pickerState.provider === "cd2" ? "/" : DIRECTORY_ROOT;
      pickerState.parent = null;
      pickerState.lastFocus = button;
      helper().setText(pickerTitle, label ? `选择${label.textContent.replace(/（.*?）/g, "").trim()}` : "选择目录");
      picker.classList.remove("hidden");
      document.body.classList.add("has-modal");
      const currentValue = (target.value || "").trim();
      const initialPath = pickerState.append ? (pickerState.provider === "cd2" ? "/" : DIRECTORY_ROOT) : (currentValue || pickerState.path);
      loadDirectory(initialPath, true);
      if (pickerUse) pickerUse.focus();
    }

    document.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-dir-picker]");
      if (trigger) openPicker(trigger);
      if (event.target.closest("[data-dir-close]")) closePicker();
    });

    picker.addEventListener("click", (event) => {
      if (event.target === picker) closePicker();
      const row = event.target.closest("[data-dir-path]");
      if (row && !row.disabled) loadDirectory(row.dataset.dirPath, false);
    });

    pickerUp?.addEventListener("click", () => {
      if (pickerState.parent) loadDirectory(pickerState.parent, false);
    });

    pickerUse?.addEventListener("click", () => {
      if (!pickerState.target || pickerState.path === DIRECTORY_ROOT || pickerState.path === "/") return;
      const value = pickerValueForTarget();
      if (pickerState.append && pickerState.target.tagName === "TEXTAREA") {
        const lines = pickerState.target.value
          .split(/\r?\n/)
          .map((line) => line.trim())
          .filter(Boolean);
        if (!lines.includes(value)) {
          lines.push(value);
        }
        pickerState.target.value = lines.join("\n");
      } else {
        pickerState.target.value = value;
      }
      pickerState.target.dispatchEvent(new Event("input", { bubbles: true }));
      closePicker();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !picker.classList.contains("hidden")) closePicker();
    });
  });
})();
