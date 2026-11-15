const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function clientWith(fetch) {
  const data = new Map([["client.access", "expired"], ["client.refresh", "valid-refresh"]]);
  const localStorage = { getItem: k => data.get(k) || null, setItem: (k,v) => data.set(k,v), removeItem: k => data.delete(k) };
  const sandbox = { window: {}, fetch, localStorage, setTimeout, clearTimeout, AbortController };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../apps/web/static/web/js/core.js"), "utf8"), sandbox);
  return { api: sandbox.window.App.createClient("client"), data };
}
const response = (status, data = {}) => ({ status, ok: status < 400, statusText: "error", json: async () => data });

test("temporary refresh failure preserves both tokens", async () => {
  for (const fail of [() => { throw new TypeError("offline"); }, () => response(502)]) {
    let n = 0;
    const { api, data } = clientWith(async () => ++n === 1 ? response(401) : fail());
    await assert.rejects(api.get("/auth/me/"));
    assert.equal(data.get("client.refresh"), "valid-refresh");
    assert.equal(data.get("client.access"), "expired");
  }
});

test("invalid refresh clears tokens", async () => {
  const { api, data } = clientWith(async () => response(401));
  await assert.rejects(api.get("/auth/me/"));
  assert.equal(data.size, 0);
});

test("logout submits refresh for server revocation and clears local state", async () => {
  const calls = [];
  const { api, data } = clientWith(async (url, options) => { calls.push([url, options]); return response(204); });
  await api.signOut();
  assert.equal(data.size, 0);
  assert.equal(calls[0][0], "/api/v1/auth/logout/");
  assert.equal(JSON.parse(calls[0][1].body).refresh, "valid-refresh");
});
