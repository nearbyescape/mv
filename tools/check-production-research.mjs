import {chromium} from "@playwright/test";
import assert from "node:assert/strict";
import {readFile,writeFile} from "node:fs/promises";
import {createHash} from "node:crypto";
import path from "node:path";
const origin="https://localhost:3443";
const browser=await chromium.launch();
const context=await browser.newContext({ignoreHTTPSErrors:true});
const sha=bytes=>createHash("sha256").update(bytes).digest("hex");
const results=[];
try {
  const login=await context.request.post(origin+"/api/auth/login",{headers:{Origin:origin},data:{email:"owner@mv-validation.example.test",password:"MV private validation password 2026!"}});
  assert.equal(login.status(),200);
  for(const [endpoint,directory] of [["research","backtests"],["research/study","exit-studies"],["research/filters","filter-studies"]]){
    const pointer=JSON.parse(await readFile(path.join("artifacts",directory,"latest.json"),"utf8"));
    const response=await context.request.get(origin+"/api/"+endpoint);
    assert.equal(response.status(),200);
    const payload=await response.json();assert.equal(payload.available,true);assert.equal(payload.report.id,pointer.id);
    for(const name of Object.keys(payload.report.files).concat("report.json")){
      const response=await context.request.get(origin+"/api/"+endpoint+"?file="+encodeURIComponent(name));
      assert.equal(response.status(),200,name);
      const actual=await response.body();
      const expected=await readFile(path.join("artifacts",directory,pointer.id,name));
      assert.equal(sha(actual),sha(expected),name);
      results.push({endpoint,file:name,sha256:sha(actual),bytes:actual.length});
    }
  }
  await writeFile("artifacts/production-validation/research-exports.json",JSON.stringify({host:"isolated private HTTPS Docker stack",results,timestamp:new Date().toISOString()},null,2));
  console.log(JSON.stringify({reports:3,exports:results.length,result:"all private downloads match original files byte-for-byte"},null,2));
} finally {await browser.close();}
