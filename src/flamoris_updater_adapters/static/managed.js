"use strict";
const basePath = document.querySelector('meta[name="updater-base-path"]').content;
let busy = false, appSnapshot = "", selfSnapshot = "", pendingActions = 0;
let selfUpdating = false, pageVersion = "", reloadScheduled = false;
const $ = id => document.getElementById(id);
const labels = {accepted:"受付済み", intent:"処理中", running:"処理中", awaiting_setup:"初回設定待ち", succeeded:"完了", recovery_required:"処理の確認が必要"};
const themes = ["green", "blue", "purple", "amber"];
let themeKey = "";
function themeFor(hostname) {
  themeKey = "flamoris-updater-theme:" + location.origin + basePath + ":" + hostname;
  let saved;
  try { saved = localStorage.getItem(themeKey); } catch { /* Browser storage may be disabled. */ }
  const theme = themes.includes(saved) ? saved : "green";
  document.documentElement.dataset.theme = theme;
  $("theme").value = theme;
}
$("theme").addEventListener("change", () => {
  const theme = $("theme").value;
  if (!themes.includes(theme)) return;
  document.documentElement.dataset.theme = theme;
  try { if (themeKey) localStorage.setItem(themeKey, theme); } catch { /* Keep the current view. */ }
});
function showNotice(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
}
function showError(error) {
  $("error-text").textContent = error.message + (error.connectionFailure ? " 操作の結果は実行状況・履歴で確認してください。操作は自動再送しません。" : "");
  $("message").hidden = false;
}
$("dismiss-error").addEventListener("click", () => { $("message").hidden = true; });
function connectionError(message) {
  return Object.assign(new Error(message), {connectionFailure:true});
}
async function api(path, data) {
  let response;
  try {
    response = await fetch(basePath + path, {
      method: data === undefined ? "GET" : "POST",
      credentials: "same-origin",
      headers: data === undefined ? {} : {"Content-Type":"application/json"},
      body: data === undefined ? undefined : JSON.stringify(data)
    });
  } catch { throw connectionError("Updaterに接続できません。接続の回復を待っています。"); }
  const detail = "HTTP " + response.status + " · " + basePath + path;
  if (!["application/json"].includes((response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase())) {
    throw connectionError("JSON形式の応答を受信できませんでした（" + detail + "）。更新中は一時的に接続できなくなります。");
  }
  let body;
  try { body = await response.json(); }
  catch { throw connectionError("JSON応答を読み取れませんでした（" + detail + "）。"); }
  if (!response.ok) {
    const error = new Error((typeof body?.message === "string" ? body.message : typeof body?.error === "string" ? body.error : "処理に失敗しました") + "（" + detail + "）");
    error.connectionFailure = [502, 503, 504].includes(response.status);
    throw error;
  }
  return body;
}
const tool = (name, args = {}) => api("/api/v1/tools/" + name, args);
function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}
async function runAction(b, fn, pendingText) {
  if (pendingActions) return;
  pendingActions++;
  const original = b.textContent;
  b.disabled = true;
  b.setAttribute("aria-busy", "true");
  b.textContent = pendingText;
  try { await fn(); }
  catch (error) { showError(error); }
  finally {
    pendingActions--;
    b.disabled = selfUpdating && b.parentElement?.id === "self-update";
    b.removeAttribute("aria-busy");
    b.textContent = original;
    poll();
  }
}
function button(text, parent, fn, pendingText = "処理中…") {
  const b = element("button", text, parent);
  b.type = "button";
  b.addEventListener("click", () => runAction(b, fn, pendingText));
  return b;
}
function newer(candidate, current) {
  const a = candidate.split(".").map(BigInt), b = current.split(".").map(BigInt);
  for (let i = 0; i < 3; i++) if (a[i] !== b[i]) return a[i] > b[i];
  return false;
}
function renderApplication(app) {
  const card = element("article", undefined, $("applications"));
  card.className = "card";
  element("h2", app.application_id, card);
  const installed = app.installation;
  element("p", installed ? installed.release + " · " + (labels[installed.phase] || installed.phase) : "未インストール", card);
  if (installed?.previous) {
    element("p", "保持中の旧版: " + installed.previous.release, card);
    button("保持中の旧版を削除", card, async () => {
      if (!confirm("旧版の実行ファイルを削除します。設定とデータは保持します。")) return;
      await tool("updater_previous_delete", {application_id:app.application_id});
    });
  }
  if (installed?.phase === "awaiting_setup") {
    element("p", "アプリを開いて初回設定を行った後、動作を確認してください。", card);
    const actions = element("div", undefined, card);
    actions.className = "setup-actions";
    const status = element("p", undefined, card);
    status.setAttribute("role", "status");
    button("アプリを起動して初回設定を開始", actions, async () => {
      status.textContent = "アプリを起動しています…";
      try { await tool("updater_install_start", {application_id:app.application_id}); }
      catch (error) { status.textContent = "起動処理の完了を確認できませんでした。エラー表示と実行記録を確認してください。"; throw error; }
      status.textContent = "起動処理が完了しました。アプリ自身の初回設定後に、動作確認ボタンを押してください。";
    }, "起動中…");
    button("初回設定後の動作を確認", actions, async () => {
      status.textContent = "起動状態とヘルスを確認しています…";
      try { await tool("updater_install_complete", {application_id:app.application_id}); }
      catch (error) { status.textContent = "動作確認は完了していません。エラー表示を確認してください。"; throw error; }
      showNotice(app.application_id + ": 初回設定後の起動状態・ヘルスを確認しました。");
    }, "確認中…");
    return;
  }
  const choices = app.releases.filter(r => !installed || (newer(r.release, installed.release) && r.compatible_from.includes(installed.release)));
  if (!choices.length) {
    element("p", installed ? "現在利用できる互換更新はありません。" : "インストール可能なリリースがありません。", card);
    return;
  }
  const form = element("form", undefined, card);
  const select = element("select", undefined, form);
  select.setAttribute("aria-label", "導入するバージョン");
  for (const release of choices) element("option", release.release, select).value = release.release;
  const fields = element("div", undefined, form);
  function renderSettings() {
    fields.replaceChildren();
    if (installed) return;
    const release = choices.find(r => r.release === select.value);
    for (const setting of release.settings) {
      const label = element("label", setting.label, fields);
      const input = element("input", undefined, label);
      input.name = setting.key;
      input.type = setting.secret ? "password" : "text";
      input.value = setting.default;
      input.required = setting.required;
      input.maxLength = 4096;
      input.autocomplete = setting.secret ? "new-password" : "off";
      if (setting.generate) {
        const hint = element("small", "空欄の場合は自動生成します。", label);
        hint.className = "hint";
        hint.id = "hint-" + app.application_id + "-" + setting.key;
        input.setAttribute("aria-describedby", hint.id);
      }
    }
  }
  select.addEventListener("change", renderSettings);
  renderSettings();
  const submit = element("button", installed ? "アップデート" : "インストール", form);
  submit.type = "submit";
  form.addEventListener("submit", event => {
    event.preventDefault();
    const settings = {};
    for (const input of fields.querySelectorAll("input")) settings[input.name] = input.value;
    runAction(submit, async () => {
      const result = await tool(installed ? "updater_update" : "updater_install", {application_id:app.application_id, release:select.value, request_key:crypto.randomUUID(), settings});
      fields.replaceChildren();
      showNotice("処理を受け付けました。ジョブ: " + result.job_id);
    }, "受付中…");
  });
}
async function refresh(releases = false) {
  if (busy) return;
  busy = true;
  try {
    const health = await api("/health");
    const hostname = health.hostname || location.hostname;
    $("hostname").textContent = hostname;
    $("version").textContent = "Updater " + health.version;
    if (!themeKey || !themeKey.endsWith(":" + hostname)) themeFor(hostname);
    if (pageVersion && pageVersion !== health.version && !reloadScheduled) {
      reloadScheduled = true;
      showNotice("Updaterの更新を確認しました。画面を読み直します。");
      setTimeout(() => location.reload(), 1000);
    }
    pageVersion = health.version;
    const apps = await tool("updater_apps_list", {refresh:releases});
    if (releases && apps.catalog_errors.length) showError(new Error("カタログを再取得できません: " + apps.catalog_errors.map(item => item.url).join(", ")));
    // Progress polling must not replace inputs while the operator is typing.
    const snapshot = JSON.stringify(apps.items);
    if (snapshot !== appSnapshot) {
      const drafts = [...$("applications").querySelectorAll("article")].map(card => ({
        app:card.querySelector("h2").textContent,
        release:card.querySelector("select")?.value,
        values:Object.fromEntries([...card.querySelectorAll("input")].map(i => [i.name, i.value]))
      }));
      $("applications").replaceChildren();
      for (const app of apps.items) renderApplication(app);
      for (const card of $("applications").querySelectorAll("article")) {
        const draft = drafts.find(d => d.app === card.querySelector("h2").textContent);
        const select = card.querySelector("select");
        if (!draft || !select || ![...select.options].some(o => o.value === draft.release)) continue;
        select.value = draft.release;
        select.dispatchEvent(new Event("change"));
        for (const input of card.querySelectorAll("input")) if (Object.hasOwn(draft.values, input.name)) input.value = draft.values[input.name];
      }
      appSnapshot = snapshot;
    }
    const history = await tool("updater_managed_history");
    selfUpdating = history.items.some(j => j.action === "self_update" && ["accepted", "running", "intent"].includes(j.phase));
    $("history").replaceChildren();
    for (const job of history.items) {
      const row = element("div", undefined, $("history"));
      row.className = "history-row";
      element("span", job.application_id + " " + job.release + " · " + (labels[job.phase] || job.phase) + " · " + (job.step || "") + (job.cleanup_pending ? " · 旧版の整理待ち" : ""), row);
      element("code", job.job_id, row);
    }
    const self = await tool("updater_self_status");
    const selfJson = JSON.stringify(self);
    if (selfJson !== selfSnapshot) {
      $("self-update").replaceChildren();
      $("self-section").hidden = false;
      const current = self.installation;
      element("p", current ? "現在のバージョン: " + current.release : "自己更新には対応するbootstrapが必要です。", $("self-update"));
      const choices = self.releases.filter(r => self.supported && current && newer(r.release, current.release) && r.compatible_from.includes(current.release));
      if (choices.length) {
        const select = element("select", undefined, $("self-update"));
        select.setAttribute("aria-label", "Updaterの更新バージョン");
        for (const release of choices) element("option", release.release, select).value = release.release;
        button("Updaterを更新", $("self-update"), async () => {
          selfUpdating = true;
          $("connection").textContent = "Updaterを更新中。接続は自動回復します。";
          const result = await tool("updater_self_update", {release:select.value, request_key:crypto.randomUUID()});
          showNotice("Updaterの更新を受け付けました。ジョブ: " + result.job_id);
        }, "更新を受付中…");
      } else element("p", "現在利用できる互換更新はありません。", $("self-update"));
      selfSnapshot = selfJson;
    }
    $("root").textContent = "アプリの保存先: " + apps.root;
    const runtime = self.installation?.runtime || health.runtime_root?.replace(/\/site-packages$/, "");
    let placement = $("runtime-placement");
    if (!placement) { placement = element("p", undefined, $("self-update")); placement.id = "runtime-placement"; placement.className = "hint"; }
    placement.textContent = "Updaterの実行ファイル: " + (runtime || "配置情報なし") + "。自己更新版は状態ディレクトリ内に配置されます。元のsupervisor配置は保持します。";
    await refreshCatalogs();
    $("connection").textContent = selfUpdating ? "Updaterを更新中。接続は自動回復します。" : "接続済み";
    $("connection").classList.remove("disconnected");
    const updateButton = $("self-update").querySelector("button");
    if (updateButton) updateButton.disabled = selfUpdating;
  } finally { busy = false; }
}
async function refreshCatalogs() {
  const catalogs = await tool("updater_catalogs_list");
  $("catalogs").replaceChildren();
  for (const item of catalogs.items) {
    const row = element("div", undefined, $("catalogs"));
    row.className = "history-row";
    element("span", item.url, row);
    button("登録解除", row, async () => {
      await tool("updater_catalog_remove", {url:item.url});
    });
  }
}
$("catalog-form").addEventListener("submit", event => {
  event.preventDefault();
  const form = event.target;
  const args = Object.fromEntries(new FormData(form));
  runAction(form.querySelector("button"), async () => {
    await tool("updater_catalog_add", args);
    form.reset();
    showNotice("カタログを登録しました。");
  }, "登録中…");
});
async function poll(releases = false) {
  if (pendingActions && !releases) return;
  try { await refresh(releases); }
  catch (error) {
    if (error.connectionFailure) {
      $("connection").textContent = (selfUpdating ? "Updater更新中 · " : "") + error.message;
      $("connection").classList.add("disconnected");
    } else showError(error);
  }
}
$("refresh").addEventListener("click", () => poll(true));
poll();
setInterval(() => poll(), 3000);
