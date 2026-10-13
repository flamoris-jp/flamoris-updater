// Exercise the shipped HTML/JS/CSS against bounded, disposable API fixtures.
// No production services, application runtimes or providers are contacted.
import assert from "node:assert/strict";
import {readFile, mkdir} from "node:fs/promises";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import path from "node:path";
const {chromium} = createRequire(import.meta.url)("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const staticRoot = path.join(root, "src/flamoris_updater_adapters/static");
const browser = await chromium.launch({headless:true, ...(process.env.UI_BROWSER_EXECUTABLE ? {executablePath:process.env.UI_BROWSER_EXECUTABLE} : {channel:"chromium"})});
const context = await browser.newContext();
const appID = "example-runtime";
const generationID = "example-generation";
const errors = [];
const calls = [];
let releaseStart;
let delayStart = false;
let completeFails = false;
let selfResponseLost = false;
let disconnectAfterAccept = false;
let failure = null;
let hostname = "node-a";
let phase = "awaiting_setup";
let outputInstalled = false;
let outputDirectory = "";
let inputDirectory = "";
let selfPhase = null;
let version = "1.0.8";
let sequence = 1;
const pastJob = {job_id:"job-" + "1".repeat(32), application_id:appID, release:"1.0.0", created_at:100, phase:"running", action:"update", sequence:1};
let jobs = [pastJob];
let selfJob = null;
let catalogs = Array.from({length:30}, (_, n) => ({url:"https://catalog.example.invalid/snapshot-" + n + "/catalog.json", applications:[appID], checked_at:100, error:null}));
const runtime = "/var/lib/flamoris-updater/releases/" + "a".repeat(64);
const page = await context.newPage();
page.on("pageerror", error => errors.push(error.message));
await context.route("https://updater.example.invalid/**", async route => {
  const request = route.request();
  const url = new URL(request.url());
  const prefix = url.pathname.startsWith("/tools/updater/") ? "/tools/updater" : url.pathname.startsWith("/updater/") ? "/updater" : "";
  const endpoint = url.pathname.slice(prefix.length);
  if (endpoint === "/") {
    return route.fulfill({contentType:"text/html", body:(await readFile(path.join(staticRoot, "managed.html"), "utf8")).replaceAll("__UPDATER_BASE_PATH__", prefix).replaceAll("__HISTORY_BOUNDARY__", String(sequence))});
  }
  if (endpoint === "/jobs") return route.fulfill({contentType:"text/html", body:(await readFile(path.join(staticRoot, "jobs.html"), "utf8")).replaceAll("__UPDATER_BASE_PATH__", prefix)});
  if (endpoint.startsWith("/static/")) {
    const filename = path.basename(endpoint);
    return route.fulfill({contentType:filename.endsWith(".js") ? "application/javascript" : "text/css", body:await readFile(path.join(staticRoot, filename), "utf8")});
  }
  const name = endpoint.startsWith("/api/v1/tools/") ? endpoint.split("/").at(-1) : "health";
  const input = request.method() === "POST" ? request.postDataJSON() : {};
  calls.push({name, input});
  if (failure && name === failure.name) return route.fulfill(failure.response);
  const json = data => route.fulfill({json:data});
  if (name === "health") return json({hostname, version, runtime_root:runtime + "/site-packages"});
  if (name === "updater_apps_list") return json({root:"/srv/flamoris/apps", catalog_errors:[], items:[
    {application_id:appID, installation:{release:"1.0.0", phase}, releases:[]},
    ...(outputInstalled ? [{application_id:"flamoris-generation-mcp", installation:{release:"1.0.4", phase:"succeeded", profile:{components:{"flamoris-generation-controller":"1.0.3"}, output_directories:{yue2:outputDirectory}, input_directories:{comfyui:inputDirectory}}}, releases:[]}] : []),
    {application_id:generationID, installation:null, releases:["1.0.1", "1.0.3", "1.0.2"].map(release => ({release, compatible_from:[], settings:[{key:"CONTROLLER_TOKEN", label:"Controllerトークン", secret:true, default:"", required:false, generate:true}]}))}
  ]});
  if (name === "updater_history_begin") return json({after_sequence:sequence, applications:[appID, generationID, "flamoris-updater"]});
  if (name === "updater_managed_history") {
    const ceiling = input.cursor?.ceiling || sequence;
    const all = [...jobs, ...(selfJob ? [{...selfJob, phase:selfPhase}] : [])];
    const filtered = all.filter(j => j.sequence <= ceiling && (input.after_sequence === undefined || j.sequence > input.after_sequence)
      && (!input.application_id || j.application_id === input.application_id) && (!input.unassigned || !j.application_id)
      && (input.created_from === undefined || j.created_at >= input.created_from) && (input.created_to === undefined || j.created_at < input.created_to)
      && (!input.cursor || j.created_at < input.cursor.created_at || (j.created_at === input.cursor.created_at && j.job_id < input.cursor.job_id)))
      .sort((a,b) => b.created_at - a.created_at || b.job_id.localeCompare(a.job_id));
    const items = filtered.slice(0, input.limit || 100);
    const last = items.at(-1);
    return json({items, active_self_update:["accepted","running","intent","recovery_required"].includes(selfPhase), next_cursor:filtered.length > items.length ? {created_at:last.created_at, job_id:last.job_id, ceiling} : null});
  }
  if (name === "updater_managed_job_get") return json(jobs.find(j => j.job_id === input.job_id));
  if (name === "updater_managed_log_get") return json({items:[{time_ms:100000, operation:"fixture.verify", outcome:"verified", sequence:1}], next_after:null, has_more:false});
  if (name === "updater_self_status") return json({supported:true, installation:{release:version, runtime}, releases:[{release:"1.0.9", compatible_from:["1.0.8"]}]});
  if (name === "updater_catalogs_list") return json({items:catalogs});
  if (name === "updater_catalog_remove") { catalogs = catalogs.filter(c => c.url !== input.url); return json({removed:true}); }
  if (name === "updater_install_start") {
    if (delayStart) await new Promise(resolve => { releaseStart = resolve; });
    return json({started:true, application_id:appID, phase:"awaiting_setup"});
  }
  if (name === "updater_install_complete") {
    if (completeFails) return route.fulfill({status:409, json:{error:"health_failed", message:"テスト用ヘルス確認失敗"}});
    phase = "succeeded";
    return json({application_id:appID, phase});
  }
  if (name === "updater_outputs_configure") {
    if (Object.hasOwn(input.directories, "yue2")) outputDirectory = input.directories.yue2;
    if (Object.hasOwn(input.directories, "comfyui")) inputDirectory = input.directories.comfyui;
    return json({job_id:"job-" + "c".repeat(32), phase:"accepted"});
  }
  if (name === "updater_self_update") {
    selfPhase = "accepted";
    selfJob = {application_id:"flamoris-updater", release:"1.0.9", job_id:"job-" + "b".repeat(32), action:"self_update", created_at:200, sequence:++sequence};
    if (selfResponseLost) return route.fulfill({status:502, contentType:"text/html", body:"<html>private-proxy-page</html>"});
    if (disconnectAfterAccept) failure = {name:"health", response:{status:502, contentType:"text/html", body:"<html>private-proxy-page</html>"}};
    return json({job_id:"job-" + "b".repeat(32), phase:selfPhase});
  }
  throw new Error("Unexpected fixture endpoint: " + endpoint);
});
try {
  outputInstalled = true;
  await page.goto("https://updater.example.invalid/updater/");
  await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");
  assert.equal(await page.locator("#catalog-management").getAttribute("open"), null);
  assert.match(await page.locator("#catalog-count").textContent(), /30/);
  assert.equal(await page.locator("#history .history-row").count(), 0, "Past active jobs must be hidden from the current view");
  assert.ok(calls.some(c => c.name === "updater_apps_list" && c.input.refresh && c.input.discover));
  const initialRefreshes = calls.filter(c => c.name === "updater_apps_list" && c.input.refresh).length;
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(calls.filter(c => c.name === "updater_apps_list" && c.input.refresh).length, initialRefreshes);
  assert.equal(await page.locator("article").filter({has:page.getByRole("heading", {name:generationID, exact:true})}).locator("select").inputValue(), "1.0.3");
  await page.locator("#catalog-management summary").click();
  assert.equal(await page.getByRole("button", {name:"登録解除", exact:true}).count(), 30);
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", {name:"登録解除", exact:true}).first().click();
  await page.waitForFunction(() => document.getElementById("catalog-count").textContent.includes("29"));
  assert.ok(await page.locator("#catalog-management").getAttribute("open") !== null, "Polling must preserve the expanded management state");
  await page.locator("#catalog-management summary").click();
  const output = page.locator("input[name='yue2_output_directory']");
  await output.fill("/srv/media/music");
  await page.waitForTimeout(3200);
  assert.equal(await output.inputValue(), "/srv/media/music");
  await page.getByRole("button", {name:"出力先を保存", exact:true}).click();
  await page.waitForFunction(() => document.getElementById("notice").textContent.includes("出力先の変更を受け付けました"));
  const outputCall = calls.find(c => c.name === "updater_outputs_configure");
  assert.equal(outputCall.input.application_id, "flamoris-generation-mcp");
  assert.deepEqual(outputCall.input.directories, {yue2:"/srv/media/music"});
  assert.ok(outputCall.input.request_key);
  const sharedInput = page.locator("input[name='comfyui_input_directory']");
  await sharedInput.fill("/srv/media/comfy-input");
  await page.waitForTimeout(3200);
  assert.equal(await sharedInput.inputValue(), "/srv/media/comfy-input");
  await page.getByRole("button", {name:"共有フォルダを保存", exact:true}).click();
  await page.waitForFunction(() => document.getElementById("notice").textContent.includes("共有フォルダの接続を受け付けました"));
  const inputCall = calls.find(c => c.name === "updater_outputs_configure" && Object.hasOwn(c.input.directories, "comfyui"));
  assert.deepEqual(inputCall.input.directories, {comfyui:"/srv/media/comfy-input"});
  assert.equal(outputDirectory, "/srv/media/music");
  outputInstalled = false;
  for (const prefix of ["", "/updater", "/tools/updater"]) {
    await page.goto("https://updater.example.invalid" + prefix + "/");
    await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");
    assert.equal(await page.locator("#hostname").textContent(), "node-a");
    assert.equal(await page.locator("#version").textContent(), "Updater 1.0.8");
    assert.match(await page.locator("#runtime-placement").textContent(), /releases\/a{64}/);
    const input = page.locator("input[name='CONTROLLER_TOKEN']");
    assert.equal(await input.getAttribute("required"), null);
    assert.match(await page.locator("#" + await input.getAttribute("aria-describedby")).textContent(), /空欄.*自動生成/);
  }
  await page.locator("#theme").selectOption("blue");
  await page.reload();
  await page.waitForFunction(() => document.documentElement.dataset.theme === "blue");
  hostname = "node-b";
  await page.reload();
  await page.waitForFunction(() => document.getElementById("hostname").textContent === "node-b");
  assert.equal(await page.locator("#theme").inputValue(), "green");
  hostname = "node-a";
  await page.reload();
  await page.waitForFunction(() => document.documentElement.dataset.theme === "blue");
  await page.locator("input[name='CONTROLLER_TOKEN']").fill("private-test-input");
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(await page.locator("input[name='CONTROLLER_TOKEN']").inputValue(), "private-test-input");

  for (const f of [
    {name:"health", response:{status:502, contentType:"text/html", body:"<html>private-proxy-page</html>"}},
    {name:"updater_apps_list", response:{status:200, contentType:"text/html", body:"<html>private-proxy-page</html>"}},
    {name:"updater_managed_history", response:{status:200, contentType:"application/json", body:"{broken"}}
  ]) {
    failure = f;
    await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
    assert.match(await page.locator("#connection").textContent(), /JSON/);
    assert.equal(await page.locator("#message").isVisible(), false);
    assert.doesNotMatch(await page.locator("body").textContent(), /Unexpected token|private-proxy-page/);
    failure = null;
    // The normal read-only polling loop must clear its own connection error.
    await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み", null, {timeout:8000});
  }
  delayStart = true;
  const start = page.getByRole("button", {name:"アプリを起動して初回設定を開始", exact:true});
  await start.click();
  await page.getByRole("button", {name:"起動中…", exact:true}).waitFor();
  assert.equal(await page.getByRole("button", {name:"起動中…", exact:true}).isDisabled(), true);
  const startDeadline = Date.now() + 5000;
  while (!releaseStart && Date.now() < startDeadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.ok(releaseStart, "Start request must reach the fixture within five seconds");
  assert.equal(calls.filter(c => c.name === "updater_install_start").length, 1);
  releaseStart();
  await page.getByText("起動処理が完了しました。", {exact:false}).waitFor();
  const verify = page.getByRole("button", {name:"初回設定後の動作を確認", exact:true});
  const a = await start.boundingBox(), b = await verify.boundingBox();
  assert.ok(b.y >= a.y + a.height + 10, "Setup buttons need a visible gap");
  completeFails = true;
  await verify.click();
  await page.getByText("テスト用ヘルス確認失敗", {exact:false}).waitFor();
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(await page.locator("#message").isVisible(), true, "A successful poll must not erase an operation failure");
  await page.getByRole("button", {name:"閉じる", exact:true}).click();
  assert.equal(await page.locator("#message").isVisible(), false);
  completeFails = false;
  await verify.click();
  await page.getByText(appID + ": 初回設定後の起動状態・ヘルスを確認しました。", {exact:true}).waitFor();

  disconnectAfterAccept = true;
  await page.getByRole("button", {name:"Updaterを更新", exact:true}).click();
  await page.waitForFunction(() => document.getElementById("connection").textContent.includes("HTTP 502"));
  assert.equal(await page.locator("#message").isVisible(), false, "Accepted update plus a failed read is a connection issue, not a mutation failure");
  assert.match(await page.locator("#notice").textContent(), /更新を受け付けました.*ジョブ/);
  assert.equal(calls.filter(c => c.name === "updater_self_update").length, 1);
  disconnectAfterAccept = false;
  failure = null;
  selfPhase = null;
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");

  const mutationBaseline = calls.filter(c => c.name === "updater_self_update").length;
  selfResponseLost = true;
  await page.getByRole("button", {name:"Updaterを更新", exact:true}).click();
  await page.locator("#message").waitFor({state:"visible"});
  assert.match(await page.locator("#error-text").textContent(), /HTTP 502.*自動再送しません/);
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(calls.filter(c => c.name === "updater_self_update").length, mutationBaseline + 1, "Lost mutation response must never be replayed");
  assert.equal(await page.getByRole("button", {name:"Updaterを更新", exact:true}).isDisabled(), true);
  selfPhase = "succeeded";
  version = "1.0.9";
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  await page.waitForFunction(() => document.getElementById("version").textContent === "Updater 1.0.9");
  await page.waitForFunction(() => !document.getElementById("notice").textContent, null, {timeout:8000});
  assert.equal(calls.filter(c => c.name === "updater_self_update").length, mutationBaseline + 1);

  jobs.push({job_id:"job-" + "2".repeat(32), application_id:appID, release:"1.0.0", action:"update", phase:"accepted", created_at:100, sequence:++sequence});
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(await page.locator("#history .history-row").count(), 1);
  pastJob.phase = "failed_safe";
  await page.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(await page.locator("#history .history-row").count(), 1);
  await page.reload();
  await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");
  assert.equal(await page.locator("#history .history-row").count(), 0);
  const otherTab = await context.newPage();
  await otherTab.goto("https://updater.example.invalid/updater/");
  await otherTab.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");
  jobs.push({job_id:"job-" + "3".repeat(32), application_id:appID, release:"1.0.0", action:"update", phase:"accepted", created_at:100, sequence:++sequence});
  await otherTab.evaluate(async () => { while (busy) await new Promise(resolve => setTimeout(resolve, 10)); await poll(); });
  assert.equal(await otherTab.locator("#history .history-row").count(), 1);
  await otherTab.close();
  for (let n = 3; n <= 46; n++) jobs.push({job_id:"job-" + n.toString(16).padStart(32,"0"), application_id:n % 2 ? appID : generationID, release:"1.0.0", action:"update", phase:"succeeded", created_at:1000+n, sequence:++sequence});
  await page.getByRole("link", {name:"過去のジョブを検索", exact:true}).click();
  await page.waitForFunction(() => document.getElementById("search-status").textContent.includes("20件"));
  assert.equal(await page.locator("#history .history-row").count(), 20);
  await page.getByRole("button", {name:"次のページ", exact:true}).click();
  assert.equal(await page.locator("#history .history-row").count(), 20);
  await page.getByRole("button", {name:"前のページ", exact:true}).click();
  await page.waitForFunction(() => !historyBusy && !pendingActions);
  await page.locator("#history-app").selectOption(appID);
  await page.getByRole("button", {name:"検索", exact:true}).click();
  await page.waitForFunction(() => document.querySelector("#history .history-row").textContent.includes("example-runtime"));
  await page.locator("#history .job-link").first().click();
  await page.getByText("fixture.verify", {exact:false}).waitFor();
  await page.locator("#history-from").fill("2026-10-13T01:00");
  await page.locator("#history-to").fill("2026-10-12T01:00");
  await page.getByRole("button", {name:"検索", exact:true}).click();
  assert.match(await page.locator("#error-text").textContent(), /終了日時/);
  await page.locator("#history-from").fill("");
  await page.locator("#history-to").fill("");
  await page.locator("#history-app").selectOption("__unassigned__");
  await page.getByRole("button", {name:"検索", exact:true}).click();
  await page.getByText("条件に一致するジョブはありません。", {exact:true}).waitFor();
  if (process.env.UI_SCREENSHOTS) {
    await page.locator("#history-app").selectOption("");
    await page.getByRole("button", {name:"検索", exact:true}).click();
    await page.waitForFunction(() => !historyBusy);
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height:900});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS, "search-" + width + ".png"), fullPage:true});
    }
  }
  await page.getByRole("link", {name:"アプリの管理へ", exact:true}).click();
  await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");

  for (const viewport of [{width:1440, height:900}, {width:390, height:844}]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => scrollTo(0, document.body.scrollHeight));
    const header = await page.locator("header").boundingBox();
    assert.equal(header.y, 0, "Header must stay visible when scrolling");
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "No horizontal overflow");
    if (process.env.UI_SCREENSHOTS) {
      await mkdir(process.env.UI_SCREENSHOTS, {recursive:true});
      await page.evaluate(() => scrollTo(0, 0));
      await page.screenshot({path:path.join(process.env.UI_SCREENSHOTS, "operator-" + viewport.width + ".png"), fullPage:true});
    }
  }
  assert.deepEqual(errors, []);
  console.log("Operator UI passed: prefixes, host identity, per-host themes, setup feedback, token hint, HTML/invalid JSON reconnect, preserved action errors, lost update response without replay, refreshed assets, compact catalogs/removal, newest release default, insertion boundaries, tab/reload, paged application search, Job effects, invalid periods, empty results, desktop/mobile layout.");
} finally {
  await context.close();
  await browser.close();
}
