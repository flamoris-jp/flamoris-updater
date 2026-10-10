"use strict";
const basePath = document.querySelector('meta[name="updater-base-path"]').content;
let csrf = "", busy = false, appSnapshot = "", selfSnapshot = "", integrationSnapshot = "";
const $ = id => document.getElementById(id);
const labels = {accepted:"受付済み", intent:"処理中", running:"処理中", awaiting_setup:"初回設定待ち", succeeded:"完了", recovery_required:"処理の確認が必要"};
function showError(error) {
  $("message").textContent = error.message;
  $("message").hidden = false;
}
async function api(path, data) {
  const response = await fetch(basePath + path, {
    method: data === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: data === undefined ? {} : {"Content-Type":"application/json", "X-CSRF-Token":csrf},
    body: data === undefined ? undefined : JSON.stringify(data)
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.message || body.error || "処理に失敗しました");
  return body;
}
const tool = (name, args = {}) => api("/api/v1/tools/" + name, args);
function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}
function button(text, parent, fn) {
  const b = element("button", text, parent);
  b.type = "button";
  b.addEventListener("click", () => fn().catch(showError));
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
      await refresh();
    });
  }
  if (installed?.phase === "awaiting_setup") {
    element("p", "アプリを開いて初回設定を行った後、動作を確認してください。", card);
    button("アプリを起動して初回設定を開始", card, async () => {
      await tool("updater_install_start", {application_id:app.application_id});
    });
    button("初回設定後の動作を確認", card, async () => {
      await tool("updater_install_complete", {application_id:app.application_id});
      await refresh();
    });
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
    submit.disabled = true;
    tool(installed ? "updater_update" : "updater_install", {application_id:app.application_id, release:select.value, request_key:crypto.randomUUID(), settings})
      .then(() => { fields.replaceChildren(); return refresh(); })
      .catch(showError).finally(() => { submit.disabled = false; });
  });
}
async function refresh(releases = false) {
  if (busy) return;
  busy = true;
  try {
    const apps = await tool("updater_apps_list", {refresh:releases});
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
          await tool("updater_self_update", {release:select.value, request_key:crypto.randomUUID()});
          await refresh();
        });
      } else element("p", "現在利用できる互換更新はありません。", $("self-update"));
      selfSnapshot = selfJson;
    }
    await refreshIntegrations();
  } finally { busy = false; }
}
async function start() {
  const setup = await api("/api/v1/setup");
  if (setup.setup_required) {
    $("root").textContent = "アプリの保存先: " + setup.root;
    $("setup").hidden = false;
    return;
  }
  try {
    const session = await api("/api/v1/session");
    csrf = session.csrf_token;
    $("identity").textContent = session.subject;
    $("workspace").hidden = false;
    $("logout").hidden = false;
    $("integrations-section").hidden = false;
    await refresh();
  } catch {
    $("login").hidden = false;
    const init = await api("/api/v1/bootstrap");
    csrf = init.csrf_token;
  }
}
$("setup-form").addEventListener("submit", event => {
  event.preventDefault();
  api("/api/v1/setup", Object.fromEntries(new FormData(event.target))).then(() => location.reload()).catch(showError);
});
$("login-form").addEventListener("submit", event => {
  event.preventDefault();
  api("/api/v1/login", Object.fromEntries(new FormData(event.target))).then(() => location.reload()).catch(showError);
});
$("logout").addEventListener("click", () => api("/api/v1/logout", {}).then(() => location.reload()).catch(showError));
$("refresh").addEventListener("click", () => refresh(true).catch(showError));
$("token").addEventListener("click", () => api("/api/v1/token", {}).then(result => {
  $("access-token").textContent = result.token + "\n有効期限: 24時間。安全なファイルに保存してください。";
  $("access-token").hidden = false;
}).catch(showError));
function showIntegrationKey(result) {
  $("integration-secret").textContent = result.token + "\n失効するまで有効です。連携先の秘密情報設定に保存してください。";
  $("integration-secret").hidden = false;
}
async function refreshIntegrations() {
  const result = await api("/api/v1/integrations");
  const snapshot = JSON.stringify(result);
  if (snapshot === integrationSnapshot) return;
  $("integrations").replaceChildren();
  for (const item of result.items) {
    const row = element("div", undefined, $("integrations"));
    row.className = "history-row";
    element("span", item.label + " · " + (item.revoked ? "失効済み" : item.roles.includes("execute") ? "読み取り・実行" : "読み取りのみ"), row);
    if (!item.revoked) {
      button("キーを更新", row, async () => {
        if (!confirm("現在のキーを失効し、新しいキーを発行します。連携先の設定を更新してください。")) return;
        showIntegrationKey(await api("/api/v1/integrations/" + item.integration_id + "/rotate", {label:item.label, execute:item.roles.includes("execute")}));
        await refreshIntegrations();
      });
      button("失効", row, async () => {
        if (!confirm("この連携キーを失効します。")) return;
        await api("/api/v1/integrations/" + item.integration_id + "/revoke", {});
        await refreshIntegrations();
      });
    }
  }
  integrationSnapshot = snapshot;
}
$("integration-form").addEventListener("submit", event => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.target));
  api("/api/v1/integrations", {label:values.label, execute:values.execute === "true"})
    .then(result => { showIntegrationKey(result); return refreshIntegrations(); }).catch(showError);
});
start().catch(showError);
setInterval(() => { if (!$("workspace").hidden) refresh().catch(showError); }, 3000);
