import { chromium } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
import path from "node:path";

const origin = "https://localhost:3443";
const docker = process.env.DOCKER_BIN || (process.platform === "win32" ? "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe" : "docker");
const ownerEmail = "owner@mv-validation.example.test";
const password = "MV private validation password 2026!";
const output = path.resolve("artifacts/production-validation");
await mkdir(output, {recursive: true});
const browser = await chromium.launch();
const context = await browser.newContext({ignoreHTTPSErrors: true, viewport: {width:1440,height:1000}});
const page = await context.newPage();
const errors = [];
page.on("pageerror", e => errors.push(e.message));
const checks = [];
const pass = (name) => checks.push(name);
async function scan(label) {
  const violations = (await new AxeBuilder({page}).withTags(["wcag2a","wcag2aa","wcag21aa"]).analyze()).violations;
  assert.deepEqual(violations, [], `${label}: ${violations.map(v=>v.id).join(", ")}`);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,label+" overflow");
  await page.screenshot({path:path.join(output,label+".png"),fullPage:true});
}
async function post(action, body, active=context) {
  return active.request.post(origin+action,{headers:{Origin:origin},data:body});
}
async function navigate(name, mobile=false) {
  if(mobile) await page.getByRole("button",{name:"Open navigation",exact:true}).click();
  await page.getByRole("navigation",{name:"Main navigation",exact:true}).getByRole("button",{name,exact:false}).click();
}
try {
  await page.goto(origin+"/");
  assert.equal(new URL(page.url()).pathname,"/login");
  assert.equal((await context.request.get(origin+"/api/signals")).status(),401);
  pass("Anonymous page/API access rejected");
  await scan("login-desktop");
  const signIn=await post("/api/auth/login",{email:ownerEmail,password});
  if(signIn.status()===401) {
    const result=JSON.parse(execFileSync(docker,["exec","mv-signal-validation-api-1","python","-m","app.auth","bootstrap","--email",ownerEmail],{encoding:"utf8"}));
    const token=new URL(result.accept_url).hash.split("#invite=")[1];
    await page.goto(origin+"/login#invite="+token);
    await page.getByLabel("Your name",{exact:true}).fill("Validation owner");
    await page.getByLabel("Email address",{exact:true}).fill(ownerEmail);
    await page.getByLabel("Password",{exact:true}).fill(password);
    await page.getByRole("button",{name:"Create account",exact:true}).click();
    assert.equal((await post("/api/auth/accept",{token,email:ownerEmail,name:"Reuse",password})).status(),400);
    pass("Real bootstrap/invitation single use and token stripping");
  } else { assert.equal(signIn.status(),200); const body=await signIn.json(); assert.equal(body.token,undefined);assert.equal(body.user.password_hash,undefined); await page.goto(origin+"/"); pass("Server-bootstrap account signs in without returning a browser token"); }
  await page.getByRole("heading",{name:"Market overview",exact:true}).waitFor();
  const cookie=(await context.cookies()).find(c=>c.name==="__Host-mv_session");
  assert.ok(cookie?.httpOnly&&cookie.secure&&cookie.sameSite==="Strict"&&cookie.path==="/");
  assert.equal(await page.evaluate(()=>document.cookie.includes("mv_session")),false);
  assert.equal(await page.evaluate(()=>localStorage.getItem("mv_session")),null);
  pass("HTTPS HttpOnly/Secure/Strict host cookie and SSR private gate");
  await scan("overview-desktop");
  assert.equal((await context.request.put(origin+"/api/watchlist",{headers:{Origin:"https://foreign.example"},data:{symbols:["BTCUSDT"]}})).status(),403);
  assert.equal((await context.request.post(origin+"/api/auth/password",{headers:{Origin:"https://foreign.example"},data:{}})).status(),403);
  pass("Cross-origin mutations rejected through Caddy and Next");
  await navigate("Administration");
  await page.getByRole("heading",{name:"Workspace members",exact:true}).waitFor();
  await scan("administration-desktop");
  const memberEmail="viewer-"+Date.now()+"@mv-validation.example.test";
  await page.getByLabel("Email address",{exact:true}).fill(memberEmail);
  await page.getByRole("button",{name:"Create invitation",exact:true}).click();
  const link=page.getByLabel("Private invitation link");await link.waitFor();
  const invitation=await link.inputValue();
  const viewer=await browser.newContext({ignoreHTTPSErrors:true});
  const viewerPage=await viewer.newPage();
  await viewerPage.goto(invitation);
  await viewerPage.getByLabel("Your name",{exact:true}).fill("Validation viewer");
  await viewerPage.getByLabel("Email address",{exact:true}).fill(memberEmail);
  await viewerPage.getByLabel("Password",{exact:true}).fill(password);
  await viewerPage.getByRole("button",{name:"Create account",exact:true}).click();
  await viewerPage.getByRole("heading",{name:"Market overview",exact:true}).waitFor();
  const reused=new URL(invitation).hash.split("#invite=")[1];
  assert.equal((await post("/api/auth/accept",{token:reused,email:memberEmail,name:"Reuse",password},viewer)).status(),400);
  assert.equal(await viewerPage.getByRole("button",{name:"Administration",exact:true}).count(),0);
  assert.ok(await viewerPage.getByRole("button",{name:"Manage markets",exact:true}).isDisabled());
  assert.equal((await viewer.request.get(origin+"/api/admin")).status(),403);
  assert.equal((await viewer.request.put(origin+"/api/watchlist",{headers:{Origin:origin},data:{symbols:["BTCUSDT"]}})).status(),403);
  pass("Real viewer invitation and backend/UI role enforcement");
  const accounts=await (await context.request.get(origin+"/api/admin")).json();
  const user=accounts.users.find(u=>u.email===memberEmail);
  assert.equal((await context.request.patch(origin+"/api/admin",{headers:{Origin:origin},data:{id:user.id,role:"viewer",enabled:false}})).status(),200);
  assert.equal((await viewer.request.get(origin+"/api/auth/me")).status(),401);
  await viewer.close();
  pass("Administrator disable revokes active session");
  await navigate("Notifications");await scan("notifications-desktop");
  await navigate("Signal journal");await scan("history-desktop");
  await navigate("My account");await scan("account-desktop");
  await navigate("System & delivery");await scan("operations-desktop");
  const health=await (await context.request.get(origin+"/api/system")).json();
  assert.equal(health.paper,"disabled");assert.equal(health.orders,"disabled");
  assert.equal(health.telegram,"not-configured");assert.equal(health.ai,"not-configured");
  assert.equal(health.web_delivery.state,"running");
  assert.equal(health.backup.state,"current");
  pass("Measured operations, backup, disabled paper/orders and deferred integrations");
  await page.getByRole("button",{name:"Switch to dark theme",exact:true}).click();
  await scan("operations-dark");
  await page.setViewportSize({width:390,height:844});
  await navigate("Notifications",true);await scan("notifications-mobile-dark");
  await navigate("Administration",true);await scan("administration-mobile-dark");
  await page.getByRole("button",{name:"Switch to light theme",exact:true}).click();
  await scan("administration-mobile-light");
  await page.getByRole("button",{name:"Sign out",exact:true}).click();
  await page.waitForURL(origin+"/login");
  assert.equal((await context.request.get(origin+"/api/auth/me")).status(),401);
  await scan("login-mobile");
  pass("Logout revocation, desktop/mobile and light/dark accessibility");
  assert.deepEqual(errors,[]);
  await writeFile(path.join(output,"checks.json"),JSON.stringify({checks,health,errors,host:"local isolated Docker production configuration; internal TLS only",timestamp:new Date().toISOString()},null,2));
  console.log(JSON.stringify({passed:checks.length,checks},null,2));
} finally { await browser.close(); }
