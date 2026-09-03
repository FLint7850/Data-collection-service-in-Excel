import assert from "node:assert/strict";
import test from "node:test";
import { mkdtempSync, rmdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AnalysisJobs, CodexAppServer, createBridgeServer } from "../deploy/attribute-ai-bridge.mjs";

const requestId = "a".repeat(32);
const settle = () => new Promise((resolve) => setImmediate(resolve));
const quiet = () => {};
const event = (codex, method, params) => codex.onLine(JSON.stringify({ method, params }));

function fakeCodex(t, options = {}) {
  const sandboxDir = mkdtempSync(join(tmpdir(), "attribute-ai-bridge-test-"));
  t.after(() => rmdirSync(sandboxDir));
  const codex = new CodexAppServer({ idleTimeoutMs: 1000, sandboxDir, ...options });
  const requests = [];
  codex.child = { stdin: { writable: true } };
  codex.ensureStarted = async () => {};
  codex.request = async (method, params) => {
    requests.push({ method, params });
    if (method === "thread/start") return { thread: { id: "thread-1" } };
    if (method === "turn/start") return { turn: { id: "turn-1" } };
    if (method === "turn/interrupt") return {};
    throw new Error(`Unexpected method ${method}`);
  };
  return { codex, requests };
}

test("duplicate job submission and polling never repeat the model call", async () => {
  let calls = 0;
  let finish;
  const jobs = new AnalysisJobs(() => {
    calls += 1;
    return new Promise((resolve) => { finish = resolve; });
  }, { log: quiet });
  assert.equal(jobs.start(requestId, "all products").status, "running");
  jobs.start(requestId, "all products");
  for (let i = 0; i < 10; i++) assert.equal(jobs.get(requestId).status, "running");
  assert.equal(calls, 1);
  finish({ text: "one answer" });
  await settle();
  assert.deepEqual(jobs.get(requestId).result, { text: "one answer" });
  assert.equal(jobs.start(requestId, "all products").status, "completed");
  assert.equal(calls, 1);
});

test("reusing an id for different products is rejected", () => {
  const jobs = new AnalysisJobs(async () => ({ text: "answer" }), { log: quiet });
  jobs.start(requestId, "first prompt");
  assert.throws(() => jobs.start(requestId, "other prompt"), { statusCode: 409 });
});

test("global queue limits concurrent calls and starts the next product without waiting for the slowest", async () => {
  const started = [];
  const finish = new Map();
  const jobs = new AnalysisJobs((prompt) => {
    started.push(prompt);
    return new Promise((resolve) => finish.set(prompt, resolve));
  }, { concurrency: 2, log: quiet });
  const ids = Array.from({ length: 5 }, (_, i) => i.toString(16).padStart(32, "0"));
  ids.forEach((id, i) => jobs.start(id, `product-${i}`));
  jobs.start(ids[2], "product-2");
  assert.deepEqual(started, ["product-0", "product-1"]);
  assert.equal(jobs.get(ids[2]).status, "queued");
  assert.equal(jobs.queue.length, 3);
  assert.throws(() => jobs.release(ids[0]), { statusCode: 409 });
  assert.throws(() => jobs.release(ids[2]), { statusCode: 409 });
  for (let i = 1; i < 5; i++) {
    finish.get(`product-${i}`)({ text: `answer-${i}` });
    await settle();
    assert.equal(jobs.get(ids[0]).status, "running");
    assert.equal(jobs.get(ids[i]).result.text, `answer-${i}`);
    jobs.release(ids[i]);
    assert.ok(jobs.active <= 2);
  }
  finish.get("product-0")({ text: "answer-0" });
  await settle();
  assert.deepEqual(started, ids.map((_, i) => `product-${i}`));
  assert.equal(jobs.active, 0);
  assert.equal(jobs.queue.length, 0);
});

test("a failed request releases its slot and does not cancel queued products", async () => {
  let fail;
  const jobs = new AnalysisJobs((prompt) => prompt === "bad"
    ? new Promise((_, reject) => { fail = reject; })
    : Promise.resolve({ text: "good" }), { concurrency: 1, log: quiet });
  jobs.start(requestId, "bad");
  const nextId = "b".repeat(32);
  jobs.start(nextId, "good");
  assert.equal(jobs.get(nextId).status, "queued");
  fail(new Error("model failed"));
  await settle();
  assert.equal(jobs.get(requestId).status, "failed");
  assert.equal(jobs.get(nextId).result.text, "good");
  assert.equal(jobs.active, 0);
});

test("acknowledged results free storage for batches larger than the retention capacity", async () => {
  const jobs = new AnalysisJobs(async (prompt) => ({ text: prompt }), { maxEntries: 3, concurrency: 2, log: quiet });
  for (let i = 0; i < 105; i++) {
    const id = i.toString(16).padStart(32, "0");
    jobs.start(id, `product-${i}`);
    await settle();
    assert.equal(jobs.get(id).result.text, `product-${i}`);
    assert.deepEqual(jobs.release(id), { ok: true });
    assert.deepEqual(jobs.release(id), { ok: true });
  }
  assert.equal(jobs.jobs.size, 0);
});

test("model errors are retained and not retried", async () => {
  let calls = 0;
  const jobs = new AnalysisJobs(async () => {
    calls += 1;
    throw new Error("model failed");
  }, { log: quiet });
  jobs.start(requestId, "all products");
  await settle();
  assert.equal(jobs.get(requestId).status, "failed");
  assert.equal(jobs.get(requestId).error, "model failed");
  assert.equal(jobs.start(requestId, "all products").status, "failed");
  assert.equal(calls, 1);
});

test("active jobs are not expired or evicted by a capacity limit", () => {
  const jobs = new AnalysisJobs(() => new Promise(() => {}), { retentionMs: 0, maxEntries: 1, log: quiet });
  jobs.start(requestId, "all products");
  assert.equal(jobs.get(requestId).status, "running");
  assert.throws(() => jobs.start("b".repeat(32), "other products"), { statusCode: 503 });
  assert.equal(jobs.get(requestId).status, "running");
});

test("expired completed results report absence instead of starting another analysis", async () => {
  const jobs = new AnalysisJobs(async () => ({ text: "done" }), { retentionMs: 0, log: quiet });
  jobs.start(requestId, "all products");
  await settle();
  assert.throws(() => jobs.get(requestId), { statusCode: 404 });
});

test("activity allows one analysis to run longer than the idle timeout", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { codex, requests } = fakeCodex(t);
  const analysis = codex.analyze("all products");
  await settle();
  for (let i = 0; i < 4; i++) {
    t.mock.timers.tick(900);
    event(codex, "item/reasoning/textDelta", { threadId: "thread-1", delta: "working" });
  }
  event(codex, "item/completed", { threadId: "thread-1", item: { type: "agentMessage", text: "one answer" } });
  event(codex, "turn/completed", { threadId: "thread-1", turn: { id: "turn-1", status: "completed" } });
  assert.deepEqual(await analysis, { thread_id: "thread-1", turn_id: "turn-1", text: "one answer" });
  assert.equal(requests.filter(({ method }) => method === "turn/start").length, 1);
  assert.equal(requests.some(({ method }) => method === "turn/interrupt"), false);
  assert.equal(codex.listeners.size, 0);
  assert.equal(codex.turnWaiters.size, 0);
});

test("attribute analysis explicitly uses low effort without changing the model", async (t) => {
  const { codex, requests } = fakeCodex(t);
  const analysis = codex.analyze("all products");
  await settle();
  event(codex, "item/completed", { threadId: "thread-1", item: { type: "agentMessage", text: "one answer" } });
  event(codex, "turn/completed", { threadId: "thread-1", turn: { id: "turn-1", status: "completed" } });
  await analysis;
  assert.deepEqual(requests.find(({ method }) => method === "turn/start").params, {
    threadId: "thread-1", input: [{ type: "text", text: "all products" }], effort: "low",
  });
  assert.equal(requests.some(({ params }) => "model" in params), false);
});

test("effort can be adjusted for a quality comparison without changing the prompt", async (t) => {
  const { codex, requests } = fakeCodex(t, { reasoningEffort: "medium" });
  const analysis = codex.analyze("all products");
  await settle();
  event(codex, "turn/completed", { threadId: "thread-1", turn: { id: "turn-1", status: "completed", text: "answer" } });
  await analysis;
  assert.equal(requests.find(({ method }) => method === "turn/start").params.effort, "medium");
});

test("completion logs response size and duration without logging product data", async () => {
  const logs = [];
  const jobs = new AnalysisJobs(async () => ({ text: "private answer" }), { log: (line) => logs.push(line) });
  jobs.start(requestId, "private prompt");
  await settle();
  assert.match(logs[0], /prompt_chars=14/);
  assert.match(logs[1], /completed, duration_ms=\d+, response_chars=14/);
  assert.equal(logs.some((line) => line.includes("private")), false);
});

test("a stalled analysis is interrupted and all waiters are removed", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { codex, requests } = fakeCodex(t);
  const analysis = codex.analyze("all products");
  const rejected = assert.rejects(analysis, /не присылал событий/);
  await settle();
  t.mock.timers.tick(1001);
  await rejected;
  assert.deepEqual(requests.find(({ method }) => method === "turn/interrupt"), {
    method: "turn/interrupt", params: { threadId: "thread-1", turnId: "turn-1" },
  });
  assert.equal(codex.listeners.size, 0);
  assert.equal(codex.turnWaiters.size, 0);
});

test("interleaved App Server events stay isolated by product thread", async (t) => {
  const { codex } = fakeCodex(t);
  let nextThread = 0;
  codex.request = async (method, params) => {
    if (method === "thread/start") return { thread: { id: `thread-${++nextThread}` } };
    if (method === "turn/start") return { turn: { id: `turn-${params.threadId}` } };
    throw new Error(`Unexpected method ${method}`);
  };
  const first = codex.analyze("product A");
  const second = codex.analyze("product B");
  await settle();
  assert.equal(codex.turnWaiters.size, 2);
  event(codex, "item/completed", { threadId: "thread-2", item: { type: "agentMessage", text: "answer B" } });
  event(codex, "item/completed", { threadId: "foreign-thread", item: { type: "agentMessage", text: "wrong answer" } });
  event(codex, "turn/completed", { threadId: "thread-2", turn: { status: "completed" } });
  assert.equal((await second).text, "answer B");
  assert.equal(codex.turnWaiters.size, 1);
  event(codex, "item/completed", { threadId: "thread-1", item: { type: "agentMessage", text: "answer A" } });
  event(codex, "turn/completed", { threadId: "thread-1", turn: { status: "completed" } });
  assert.equal((await first).text, "answer A");
  assert.equal(codex.turnWaiters.size, 0);
  assert.equal(codex.listeners.size, 0);
});

test("unrelated thread events cannot keep a stalled analysis alive", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const codex = new CodexAppServer({ idleTimeoutMs: 1000 });
  const waiting = codex.waitForTurn("thread-1");
  const rejected = assert.rejects(waiting.promise, /не присылал событий/);
  t.mock.timers.tick(900);
  event(codex, "item/agentMessage/delta", { threadId: "thread-2", delta: "working" });
  t.mock.timers.tick(101);
  await rejected;
});

test("App Server exit fails active analysis immediately", async (t) => {
  const { codex, requests } = fakeCodex(t);
  const analysis = codex.analyze("all products");
  const rejected = assert.rejects(analysis, /server exited/);
  await settle();
  codex.child = null;
  codex.failPending(new Error("server exited"));
  await rejected;
  assert.equal(requests.some(({ method }) => method === "turn/interrupt"), false);
  assert.equal(codex.listeners.size, 0);
});

test("turn/start failure removes event waiters without an unhandled rejection", async (t) => {
  const { codex } = fakeCodex(t);
  const request = codex.request;
  codex.request = async (method, params) => {
    if (method === "turn/start") throw new Error("start failed");
    return request(method, params);
  };
  await assert.rejects(codex.analyze("all products"), /start failed/);
  assert.equal(codex.listeners.size, 0);
  assert.equal(codex.turnWaiters.size, 0);
});

test("interrupted turns are never returned as a successful empty answer", async (t) => {
  const { codex } = fakeCodex(t);
  const analysis = codex.analyze("all products");
  const rejected = assert.rejects(analysis, /прерван/);
  await settle();
  event(codex, "turn/completed", { threadId: "thread-1", turn: { id: "turn-1", status: "interrupted" } });
  await rejected;
});

test("HTTP submission returns immediately and the same result is retrievable later", async (t) => {
  let finish;
  let calls = 0;
  const jobs = new AnalysisJobs(() => {
    calls += 1;
    return new Promise((resolve) => { finish = resolve; });
  }, { log: quiet });
  const server = createBridgeServer({}, { token: "test-token", jobs });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => {
    server.close(resolve);
    server.closeAllConnections();
  }));
  const base = `http://127.0.0.1:${server.address().port}`;
  const headers = { authorization: "Bearer test-token", "content-type": "application/json" };
  const response = await fetch(`${base}/analyses`, {
    method: "POST", headers, body: JSON.stringify({ request_id: requestId, prompt: "all products" }),
  });
  assert.equal(response.status, 202);
  assert.equal((await response.json()).id, requestId);
  const pending = await fetch(`${base}/analyses/${requestId}`, { headers });
  assert.equal((await pending.json()).status, "running");
  const prematureRelease = await fetch(`${base}/analyses/${requestId}`, { method: "DELETE", headers });
  assert.equal(prematureRelease.status, 409);
  await prematureRelease.json();
  const unauthorized = await fetch(`${base}/analyses/${requestId}`);
  assert.equal(unauthorized.status, 401);
  await unauthorized.json();
  finish({ text: "one answer" });
  await settle();
  const completed = await fetch(`${base}/analyses/${requestId}`, { headers });
  assert.deepEqual((await completed.json()).result, { text: "one answer" });
  assert.equal(calls, 1);
  const release = await fetch(`${base}/analyses/${requestId}`, { method: "DELETE", headers });
  assert.equal(release.status, 200);
  await release.json();
  const missing = await fetch(`${base}/analyses/${requestId}`, { headers });
  assert.equal(missing.status, 404);
  await missing.json();
});
