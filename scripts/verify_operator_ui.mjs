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
const browser = await chromium.launch({headless:true, channel:"chromium"});
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
let selfPhase = null;
let version = "1.0.8";
const runtime = "/var/lib/flamoris-updater/releases/" + "a".repeat(64);
const page = await context.newPage();
page.on("pageerror", error => errors.push(error.message));
await context.route("https://updater.example.invalid/**", async route => {
  const request = route.request();
  const url = new URL(request.url());
  const prefix = url.pathname.startsWith("/tools/updater/") ? "/tools/updater" : url.pathname.startsWith("/updater/") ? "/updater" : "";
  const endpoint = url.pathname.slice(prefix.length);
  if (endpoint === "/") {
    return route.fulfill({contentType:"text/html", body:(await readFile(path.join(staticRoot, "managed.html"), "utf8")).replaceAll("__UPDATER_BASE_PATH__", prefix)});
  }
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
    {application_id:generationID, installation:null, releases:[{release:"1.0.2", compatible_from:[], settings:[{key:"CONTROLLER_TOKEN", label:"Controllerトークン", secret:true, default:"", required:false, generate:true}]}]}
  ]});
  if (name === "updater_managed_history") return json({items:selfPhase ? [{application_id:"flamoris-updater", release:"1.0.9", job_id:"job-" + "b".repeat(32), action:"self_update", phase:selfPhase}] : []});
  if (name === "updater_self_status") return json({supported:true, installation:{release:version, runtime}, releases:[{release:"1.0.9", compatible_from:["1.0.8"]}]});
  if (name === "updater_catalogs_list") return json({items:[]});
  if (name === "updater_install_start") {
    if (delayStart) await new Promise(resolve => { releaseStart = resolve; });
    return json({started:true, application_id:appID, phase:"awaiting_setup"});
  }
  if (name === "updater_install_complete") {
    if (completeFails) return route.fulfill({status:409, json:{error:"health_failed", message:"テスト用ヘルス確認失敗"}});
    phase = "succeeded";
    return json({application_id:appID, phase});
  }
  if (name === "updater_self_update") {
    selfPhase = "accepted";
    if (selfResponseLost) return route.fulfill({status:502, contentType:"text/html", body:"<html>private-proxy-page</html>"});
    if (disconnectAfterAccept) failure = {name:"health", response:{status:502, contentType:"text/html", body:"<html>private-proxy-page</html>"}};
    return json({job_id:"job-" + "b".repeat(32), phase:selfPhase});
  }
  throw new Error("Unexpected fixture endpoint: " + endpoint);
});
try {
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
  await page.evaluate(() => poll());
  assert.equal(await page.locator("input[name='CONTROLLER_TOKEN']").inputValue(), "private-test-input");

  for (const f of [
    {name:"health", response:{status:502, contentType:"text/html", body:"<html>private-proxy-page</html>"}},
    {name:"updater_apps_list", response:{status:200, contentType:"text/html", body:"<html>private-proxy-page</html>"}},
    {name:"updater_managed_history", response:{status:200, contentType:"application/json", body:"{broken"}}
  ]) {
    failure = f;
    await page.evaluate(() => poll());
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
  await page.evaluate(() => poll());
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
  await page.evaluate(() => poll());
  await page.waitForFunction(() => document.getElementById("connection").textContent === "接続済み");

  const mutationBaseline = calls.filter(c => c.name === "updater_self_update").length;
  selfResponseLost = true;
  await page.getByRole("button", {name:"Updaterを更新", exact:true}).click();
  await page.locator("#message").waitFor({state:"visible"});
  assert.match(await page.locator("#error-text").textContent(), /HTTP 502.*自動再送しません/);
  await page.evaluate(() => poll());
  await page.evaluate(() => poll());
  assert.equal(calls.filter(c => c.name === "updater_self_update").length, mutationBaseline + 1, "Lost mutation response must never be replayed");
  assert.equal(await page.getByRole("button", {name:"Updaterを更新", exact:true}).isDisabled(), true);
  selfPhase = "succeeded";
  version = "1.0.9";
  await page.evaluate(() => poll());
  await page.waitForFunction(() => document.getElementById("version").textContent === "Updater 1.0.9");
  await page.waitForFunction(() => !document.getElementById("notice").textContent, null, {timeout:8000});
  assert.equal(calls.filter(c => c.name === "updater_self_update").length, mutationBaseline + 1);

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
  console.log("Operator UI passed: prefixes, host identity, per-host themes, setup feedback, token hint, HTML/invalid JSON reconnect, preserved action errors, lost update response without replay, refreshed assets, desktop/mobile layout.");
} finally {
  await context.close();
  await browser.close();
}
