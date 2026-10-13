"use strict";
const basePath = document.querySelector('meta[name="updater-base-path"]').content;
let refreshRequested = false;
let busy = false, appSnapshot = "", selfSnapshot = "", pendingActions = 0;
let selfUpdating = false, pageVersion = "", reloadScheduled = false;
const $ = id => document.getElementById(id);
const searchView = !!$("history-search");
const boundaryValue = document.querySelector('meta[name="history-boundary"]')?.content;
let historyBoundary = /^\d+$/.test(boundaryValue || "") ? Number(boundaryValue) : null;
let historyCursor = null, historyBack = [], historyQuery = {}, historyBusy = false;
let detailJob = null, eventAfter = 0, detailRequest = 0, eventsBusy = false;

const labels = {accepted:"受付済み", intent:"処理中", running:"処理中", awaiting_setup:"初回設定待ち", succeeded:"完了", recovery_required:"処理の確認が必要", failed_safe:"失敗（安全に停止）", failed:"失敗"};
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
    if (!searchView) poll();
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
function releaseChoices(releases, installed) {
  return releases.filter(r => !installed || (newer(r.release, installed.release) && r.compatible_from.includes(installed.release)))
    .sort((a, b) => newer(a.release, b.release) ? -1 : newer(b.release, a.release) ? 1 : 0);
}
function displayTime(seconds) {
  return Number.isFinite(seconds) ? new Date(seconds * 1000).toLocaleString() : "日時なし";
}
const actions = {install:"インストール", update:"更新", self_update:"Updater本体の更新", outputs_configure:"保存先・共有フォルダ設定", configure_outputs:"保存先・共有フォルダ設定"};
async function loadHistory(report = true) {
  if (historyBusy) return;
  historyBusy = true;
  if (searchView) $("history-search").querySelector("button").disabled = true;
  try {
    const args = {limit:20, ...historyQuery};
    if (!searchView) args.after_sequence = historyBoundary;
    if (historyCursor) args.cursor = historyCursor;
    const result = await tool("updater_managed_history", args);
    if (!searchView) selfUpdating = !!result.active_self_update;
    $("history").replaceChildren();
    if (!result.items.length) element("p", searchView ? "条件に一致するジョブはありません。" : "この画面を開いてからのジョブはありません。", $("history"));
    for (const job of result.items) {
      const row = element("div", undefined, $("history"));
      row.className = "history-row";
      const info = element("div", undefined, row);
      element("strong", (job.application_id || "アプリ未指定") + " " + (job.release || ""), info);
      element("p", (actions[job.action] || job.action || "管理操作") + " · " + displayTime(job.created_at) + " · " + (labels[job.phase] || job.phase) + (job.step ? " · " + job.step : "") + (job.cleanup_pending ? " · 旧版の整理待ち" : ""), info);
      const link = element("a", job.job_id, info);
      link.href = basePath + "/jobs?job=" + encodeURIComponent(job.job_id);
      link.className = "job-link";
      if (searchView) link.addEventListener("click", event => { event.preventDefault(); showJob(job.job_id).catch(showError); });
    }
    $("history-pages").replaceChildren();
    if (historyBack.length) button("前のページ", $("history-pages"), async () => { historyCursor = historyBack.pop(); await loadHistory(); });
    if (result.next_cursor) button("次のページ", $("history-pages"), async () => { historyBack.push(historyCursor); historyCursor = result.next_cursor; await loadHistory(); });
    if (searchView) $("search-status").textContent = "新しい順 · " + result.items.length + "件を表示";
  } catch (error) {
    if (report) showError(error);
    else throw error;
  } finally { historyBusy = false; if (searchView) $("history-search").querySelector("button").disabled = false; }
}
async function showJob(identity) {
  const request = ++detailRequest;
  const job = await tool("updater_managed_job_get", {job_id:identity});
  if (request !== detailRequest) return;
  detailJob = job;
  eventAfter = 0;
  $("job-summary").replaceChildren();
  element("p", job.job_id + " · " + (job.application_id || "アプリ未指定") + " · " + (actions[job.action] || job.action || "管理操作"), $("job-summary"));
  element("p", displayTime(job.created_at) + " · " + (labels[job.phase] || job.phase) + " · " + (job.step || ""), $("job-summary"));
  $("job-events").replaceChildren();
  $("more-events").hidden = true;
  $("job-detail").hidden = false;
  if (job.application_id) await loadEvents(true);
  else element("p", "アプリ未指定の記録です。", $("job-events"));
  if (request === detailRequest) $("job-detail").scrollIntoView({block:"start"});
}
async function loadEvents(initial = false) {
  if (!detailJob || (eventsBusy && !initial)) return;
  const request = detailRequest, job = detailJob, after = eventAfter || 0;
  eventsBusy = true;
  $("more-events").disabled = true;
  try {
    const result = await tool("updater_managed_log_get", {application_id:job.application_id, job_id:job.job_id, after, limit:25});
    if (request !== detailRequest) return;
    if (!result.items.length && !after) element("p", "経過の記録はありません。", $("job-events"));
    for (const event of result.items) {
      const row = element("p", displayTime(event.time_ms / 1000) + " · " + (event.operation || event.step || "処理") + " · " + (event.outcome || ""), $("job-events"));
      row.className = "step";
    }
    eventAfter = result.next_after;
    $("more-events").hidden = !result.has_more;
  } finally { if (request === detailRequest) { eventsBusy = false; $("more-events").disabled = false; } }
}
async function initializeSearch() {
  try {
    const health = await api("/health");
    $("hostname").textContent = health.hostname || location.hostname;
    $("version").textContent = "Updater " + health.version;
    themeFor(health.hostname || location.hostname);
    $("connection").textContent = "接続済み";
    const info = await tool("updater_history_begin");
    for (const id of info.applications || []) element("option", id, $("history-app")).value = id;
    $("timezone").textContent = "時刻はこのブラウザーのタイムゾーン（" + Intl.DateTimeFormat().resolvedOptions().timeZone + "）。開始を含み、終了は含みません。";
    await loadHistory();
    const job = new URLSearchParams(location.search).get("job");
    if (job) await showJob(job);
  } catch (error) { showError(error); }
}
if (searchView) {
  $("history-search").addEventListener("submit", async event => {
    event.preventDefault();
    if (historyBusy) return;
    const query = {};
    const app = $("history-app").value;
    if (app === "__unassigned__") query.unassigned = true;
    else if (app) query.application_id = app;
    for (const [id, key] of [["history-from", "created_from"], ["history-to", "created_to"]]) {
      const value = $(id).value;
      if (value) {
        const time = Math.floor(new Date(value).getTime() / 1000);
        if (!Number.isFinite(time) || time < 0) { showError(new Error("有効な日時を入力してください。")); return; }
        query[key] = time;
      }
    }
    if (query.created_from !== undefined && query.created_to !== undefined && query.created_from >= query.created_to) {
      showError(new Error("終了日時は開始日時より後にしてください。")); return;
    }
    detailRequest++;
    detailJob = null;
    eventsBusy = false;
    $("job-detail").hidden = true;
    historyQuery = query;
    historyCursor = null;
    historyBack = [];
    $("search-status").textContent = "検索中…";
    await loadHistory();
  });
  $("more-events").addEventListener("click", () => loadEvents().catch(showError));
}
function renderApplication(app) {
  const card = element("article", undefined, $("applications"));
  card.className = "card";
  element("h2", app.application_id, card);
  const installed = app.installation;
  const check = app.catalog_check;
  if (check) {
    const message = !check.url ? "配布元を確認できません。カタログ管理から登録してください。"
      : check.error ? (check.error === "github_access_required" ? "GitHubの読み取りアクセスが必要です。" : "カタログ取得失敗・保存済み情報を表示中")
      : check.suppressed ? "配布元の自動確認は登録解除されています。"
      : !check.registered ? "更新確認用の配布元は未登録です。"
      : check.checked_at ? "カタログ確認済み: " + displayTime(check.checked_at) : "保存済みカタログ・最新確認日時なし";
    element("p", message, card).className = "hint";
  }
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
  if (installed?.phase === "succeeded" && app.application_id === "flamoris-generation-mcp" && installed.profile?.components?.["flamoris-generation-controller"] && !newer("1.0.1", installed.profile.components["flamoris-generation-controller"])) {
    const outputForm = element("form", undefined, card);
    const label = element("label", "YuE2の出力先", outputForm);
    const input = element("input", undefined, label);
    input.name = "yue2_output_directory";
    input.type = "text";
    input.maxLength = 4096;
    input.value = installed.profile.output_directories?.yue2 || "";
    input.placeholder = "既存フォルダの絶対パス";
    element("small", "生成が完了してから変更してください。空欄にすると公開コピーを停止します。", label).className = "hint";
    const save = element("button", "出力先を保存", outputForm);
    save.type = "submit";
    outputForm.addEventListener("submit", event => {
      event.preventDefault();
      runAction(save, async () => {
        const result = await tool("updater_outputs_configure", {application_id:app.application_id, request_key:crypto.randomUUID(), directories:{yue2:input.value}});
        showNotice("出力先の変更を受け付けました。ジョブ: " + result.job_id);
      }, "受付中…");
    });
  }
  if (installed?.phase === "succeeded" && app.application_id === "flamoris-generation-mcp" && installed.profile?.components?.["flamoris-generation-controller"] && !newer("1.0.3", installed.profile.components["flamoris-generation-controller"])) {
    const inputForm = element("form", undefined, card);
    const label = element("label", "参照画像の共有フォルダ", inputForm);
    const input = element("input", undefined, label);
    input.name = "comfyui_input_directory";
    input.type = "text";
    input.maxLength = 4096;
    input.value = installed.profile.input_directories?.comfyui || "";
    input.placeholder = "ComfyUIで設定済みの入力フォルダの絶対パス";
    element("small", "ComfyUIと同じ既存フォルダを指定してください。空欄で接続を解除します。画像は削除しません。", label).className = "hint";
    const save = element("button", "共有フォルダを保存", inputForm);
    save.type = "submit";
    inputForm.addEventListener("submit", event => {
      event.preventDefault();
      runAction(save, async () => {
        const result = await tool("updater_outputs_configure", {application_id:app.application_id, request_key:crypto.randomUUID(), directories:{comfyui:input.value}});
        showNotice("共有フォルダの接続を受け付けました。ジョブ: " + result.job_id);
      }, "受付中…");
    });
  }
  const choices = releaseChoices(app.releases, installed);
  if (!choices.length) {
    element("p", installed ? "現在利用できる互換更新はありません。" : "インストール可能なリリースがありません。", card);
    return;
  }
  if (installed && choices.length > 1) element("p", "最新の互換更新を選択しています。ほかの候補はバージョン欄で確認できます。", card).className = "hint";
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
  if (busy) { if (releases) refreshRequested = true; return; }
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
    if (historyBoundary === null) historyBoundary = (await tool("updater_history_begin")).after_sequence;
    if (releases) $("release-status").textContent = $("catalog-status").textContent = "カタログを確認中…";
    const apps = await tool("updater_apps_list", {refresh:releases, discover:releases});
    const failures = apps.catalog_errors || [];
    $("catalog-status").textContent = failures.length ? "取得に失敗した配布元があります。保存済み情報を表示中です。" : releases ? "カタログを確認しました。" : "保存済みのカタログを表示しています。";
    if (releases || failures.length) $("release-status").textContent = failures.length ? "一部のカタログを取得できません。カタログ管理で配布元を確認してください。" : "カタログの確認が完了しました。";
    if (failures.length) {
      for (const item of failures) element("p", item.url + " · " + (item.error === "github_access_required" ? "GitHubの読み取りアクセスが必要です。" : "取得失敗・保存済み情報を使用"), $("catalog-status")).className = "hint";
    }
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
        if (!draft) continue;
        if (select && [...select.options].some(o => o.value === draft.release)) {
          select.value = draft.release;
          select.dispatchEvent(new Event("change"));
        }
        for (const input of card.querySelectorAll("input")) if (Object.hasOwn(draft.values, input.name)) input.value = draft.values[input.name];
      }
      appSnapshot = snapshot;
    }
    await loadHistory(false);
    const self = await tool("updater_self_status");
    const selfJson = JSON.stringify(self);
    if (selfJson !== selfSnapshot) {
      $("self-update").replaceChildren();
      $("self-section").hidden = false;
      const current = self.installation;
      element("p", current ? "現在のバージョン: " + current.release : "自己更新には対応するbootstrapが必要です。", $("self-update"));
      const choices = self.supported && current ? releaseChoices(self.releases, current) : [];
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
  } finally { busy = false; if (refreshRequested) { refreshRequested = false; queueMicrotask(() => poll(true)); } }
}
async function refreshCatalogs() {
  const catalogs = await tool("updater_catalogs_list");
  $("catalog-count").textContent = "（" + catalogs.items.length + "件" + (catalogs.items.some(i => i.error) ? "・取得失敗あり" : "") + "）";
  $("catalogs").replaceChildren();
  for (const item of catalogs.items) {
    const row = element("div", undefined, $("catalogs"));
    row.className = "history-row";
    const info = element("div", undefined, row);
    element("span", item.url, info);
    if (item.applications?.length) element("p", item.applications.join(" · "), info).className = "hint";
    element("small", item.error ? (item.error === "github_access_required" ? "GitHubの読み取りアクセスが必要です。保存済み情報を表示中" : "取得失敗・保存済み情報を表示中") : item.checked_at ? "確認済み: " + displayTime(item.checked_at) : "保存済み情報・最新確認日時なし", info).className = "hint";
    button("登録解除", row, async () => {
      if (!confirm("このカタログだけが提供する更新候補は表示されなくなります。アプリ・設定・データ・履歴は残ります。登録を解除しますか？")) return;
      await tool("updater_catalog_remove", {url:item.url});
      showNotice("カタログの登録を解除しました。アプリと履歴は保持しています。");
    });
  }
}
$("catalog-form")?.addEventListener("submit", event => {
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
if (searchView) {
  initializeSearch();
} else {
  $("refresh").addEventListener("click", () => poll(true));
  // Show retained information immediately; one external check per opening, never per progress poll.
  (async () => { await poll(); await poll(true); })();
  setInterval(() => poll(), 3000);
}
