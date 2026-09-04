import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { createHash } from "node:crypto";

const host = process.env.ATTRIBUTE_AI_HOST || "127.0.0.1";
const port = Number(process.env.ATTRIBUTE_AI_PORT || 4580);
const bridgeToken = process.env.ATTRIBUTE_CHATGPT_BRIDGE_TOKEN || "";
const codexHome = resolve(process.env.ATTRIBUTE_CODEX_HOME || "./storage/attribute-codex");
const proxyUrl = (process.env.ATTRIBUTE_CHATGPT_PROXY_URL || "").trim();
const requestTimeoutMs = 30000;
const configuredIdleTimeoutMs = Number(process.env.ATTRIBUTE_CHATGPT_IDLE_TIMEOUT_MS || process.env.ATTRIBUTE_CHATGPT_TIMEOUT_MS || 600000);
const analysisIdleTimeoutMs = Number.isFinite(configuredIdleTimeoutMs) && configuredIdleTimeoutMs > 0
  ? configuredIdleTimeoutMs : 600000;
const maxRequestBytes = Number(process.env.ATTRIBUTE_AI_MAX_REQUEST_BYTES || 8 * 1024 * 1024);
const analysisReasoningEffort = process.env.ATTRIBUTE_CHATGPT_REASONING_EFFORT?.trim() || "low";
const configuredConcurrency = Number(process.env.ATTRIBUTE_CHATGPT_CONCURRENCY || 3);
const analysisConcurrency = Number.isInteger(configuredConcurrency)
  ? Math.max(1, Math.min(8, configuredConcurrency)) : 3;

function codexCommand() {
  const configured = (process.env.CODEX_BIN || "").trim();
  if (configured) return configured;
  if (process.platform === "win32") {
    return resolve("./storage/codex-cli/node_modules/.bin/codex.cmd");
  }
  return "codex";
}

function codexEnvironment() {
  const environment = { ...process.env, CODEX_HOME: codexHome };
  for (const name of [
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "all_proxy", "no_proxy",
  ]) {
    delete environment[name];
  }
  if (proxyUrl) {
    environment.HTTP_PROXY = proxyUrl;
    environment.HTTPS_PROXY = proxyUrl;
    environment.ALL_PROXY = proxyUrl;
    environment.NO_PROXY = "127.0.0.1,localhost,::1";
    environment.http_proxy = proxyUrl;
    environment.https_proxy = proxyUrl;
    environment.all_proxy = proxyUrl;
    environment.no_proxy = environment.NO_PROXY;
  }
  const systemCaBundle = "/etc/ssl/certs/ca-certificates.crt";
  if (process.platform !== "win32" && !environment.CODEX_CA_CERTIFICATE
      && !environment.SSL_CERT_FILE && existsSync(systemCaBundle)) {
    environment.CODEX_CA_CERTIFICATE = systemCaBundle;
  }
  return environment;
}

export class CodexAppServer {
  constructor({
    idleTimeoutMs = analysisIdleTimeoutMs,
    sandboxDir = resolve(codexHome, "attribute-analysis-sandbox"),
    reasoningEffort = analysisReasoningEffort,
  } = {}) {
    this.child = null;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Set();
    this.starting = null;
    this.stderrTail = [];
    this.turnWaiters = new Set();
    this.idleTimeoutMs = idleTimeoutMs;
    this.sandboxDir = sandboxDir;
    this.reasoningEffort = reasoningEffort;
  }

  async ensureStarted() {
    if (this.starting) return this.starting;
    if (this.child && !this.child.killed) return;
    this.starting = this.start();
    try {
      await this.starting;
    } finally {
      this.starting = null;
    }
  }

  async start() {
    mkdirSync(codexHome, { recursive: true });
    const command = codexCommand();
    const shell = process.platform === "win32" && command.toLowerCase().endsWith(".cmd");
    const args = proxyUrl
      ? ["--enable", "respect_system_proxy", "app-server"]
      : ["app-server"];
    const child = spawn(command, args, {
      cwd: process.cwd(),
      env: codexEnvironment(),
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      shell,
    });
    this.child = child;
    this.stderrTail = [];
    child.stderr.setEncoding("utf8");
    child.stderr.on("data", (chunk) => {
      this.stderrTail.push(String(chunk).slice(-2000));
      this.stderrTail = this.stderrTail.slice(-10);
    });
    child.on("exit", (code) => {
      if (this.child === child) this.child = null;
      const error = new Error(`Codex App Server завершился (код ${code ?? "?"})`);
      this.failPending(error);
    });
    const lines = createInterface({ input: child.stdout });
    lines.on("line", (line) => this.onLine(line));
    await new Promise((resolveReady, rejectReady) => {
      const timer = setTimeout(() => rejectReady(new Error("Codex CLI не запустился")), 8000);
      child.once("spawn", () => {
        clearTimeout(timer);
        resolveReady();
      });
      child.once("error", (error) => {
        clearTimeout(timer);
        rejectReady(error);
      });
    });
    await this.request("initialize", {
      clientInfo: {
        name: "attribute-assistant",
        title: "Помощник по атрибутам",
        version: "1.0.0",
      },
      capabilities: {},
    }, 20000);
    this.notify("initialized", {});
  }

  onLine(line) {
    let message;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (message.id !== undefined && this.pending.has(message.id)) {
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(message.error.message || "Ошибка Codex App Server"));
      else pending.resolve(message.result);
      return;
    }
    if (message.method) {
      for (const listener of [...this.listeners]) listener(message);
    }
  }

  write(message) {
    if (!this.child?.stdin?.writable) throw new Error("Codex App Server недоступен");
    this.child.stdin.write(JSON.stringify(message) + "\n");
  }

  notify(method, params = {}) {
    this.write({ method, params });
  }

  failPending(error) {
    for (const { reject, timer } of this.pending.values()) {
      clearTimeout(timer);
      reject(error);
    }
    this.pending.clear();
    for (const waiter of [...this.turnWaiters]) waiter.reject(error);
  }

  async request(method, params = {}, timeoutMs = requestTimeoutMs) {
    if (method !== "initialize") await this.ensureStarted();
    const id = this.nextId++;
    return new Promise((resolveRequest, rejectRequest) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        rejectRequest(new Error(`Codex не ответил на ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolveRequest, reject: rejectRequest, timer });
      try {
        this.write({ id, method, params });
      } catch (error) {
        clearTimeout(timer);
        this.pending.delete(id);
        rejectRequest(error);
      }
    });
  }

  waitForTurn(threadId) {
    let timer;
    let settled = false;
    let resolveEvent;
    let rejectEvent;
    const promise = new Promise((resolve, reject) => {
      resolveEvent = resolve;
      rejectEvent = reject;
    });
    // The turn may fail while turn/start is still awaiting its acknowledgement.
    promise.catch(() => {});
    const finish = (error, event) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      this.listeners.delete(listener);
      this.turnWaiters.delete(waiter);
      if (error) rejectEvent(error);
      else resolveEvent(event);
    };
    const armIdleTimer = () => {
      clearTimeout(timer);
      timer = setTimeout(() => finish(new Error(
        `ChatGPT не присылал событий ${Math.round(this.idleTimeoutMs / 1000)} секунд; анализ остановлен`,
      )), this.idleTimeoutMs);
    };
    const listener = (event) => {
      const params = event.params || {};
      if ((params.threadId || params.thread_id) !== threadId) return;
      if (event.method === "turn/completed") finish(null, event);
      else armIdleTimer();
    };
    const waiter = { promise, reject: (error) => finish(error) };
    this.turnWaiters.add(waiter);
    this.listeners.add(listener);
    armIdleTimer();
    return waiter;
  }

  async status() {
    await this.ensureStarted();
    const result = await this.request("account/read", { refreshToken: false }, 30000);
    const account = result && Object.prototype.hasOwnProperty.call(result, "account")
      ? result.account
      : result || null;
    return {
      available: true,
      authenticated: Boolean(account),
      account: account ? {
        email: account.email || account.userEmail || "",
        plan: account.planType || account.plan || "",
      } : null,
      proxy_enabled: Boolean(proxyUrl),
    };
  }

  async deviceLogin() {
    await this.ensureStarted();
    const result = await this.request("account/login/start", { type: "chatgptDeviceCode" }, 60000);
    return {
      login_id: result?.loginId || "",
      verification_url: result?.verificationUrl || "https://auth.openai.com/codex/device",
      user_code: result?.userCode || "",
    };
  }

  async logout() {
    await this.ensureStarted();
    await this.request("account/logout", {}, 30000);
    return { ok: true };
  }

  async analyze(prompt) {
    await this.ensureStarted();
    const sandboxDir = this.sandboxDir;
    mkdirSync(sandboxDir, { recursive: true });
    const started = await this.request("thread/start", {
      cwd: sandboxDir,
      approvalPolicy: "never",
      sandbox: "read-only",
      ephemeral: true,
    }, 60000);
    const threadId = started?.thread?.id || started?.threadId || started?.id;
    if (!threadId) throw new Error("Codex App Server не вернул идентификатор задачи");
    const messages = [];
    const listener = (event) => {
      if (event.method !== "item/completed") return;
      const params = event.params || {};
      if ((params.threadId || params.thread_id) !== threadId) return;
      const item = params.item || {};
      if (item.type !== "agentMessage" && item.type !== "agent_message") return;
      const text = agentText(item);
      if (text) messages.push(text);
    };
    this.listeners.add(listener);
    const completion = this.waitForTurn(threadId);
    let turnId = "";
    let completed = false;
    try {
      const turn = await this.request("turn/start", {
        threadId,
        input: [{ type: "text", text: prompt }],
        effort: this.reasoningEffort,
      }, 60000);
      turnId = turn?.turn?.id || turn?.turnId || "";
      const event = await completion.promise;
      completed = true;
      const status = event.params?.turn?.status || event.params?.status || "completed";
      if (status !== "completed") {
        throw new Error(event.params?.turn?.error?.message
          || (status === "interrupted" ? "Анализ ChatGPT прерван" : "ChatGPT не смог выполнить анализ"));
      }
      if (!messages.length) {
        const fallback = agentText(event.params?.turn || event.params || {});
        if (fallback) messages.push(fallback);
      }
      return { thread_id: threadId, turn_id: turnId, text: messages.join("\n").trim() };
    } catch (error) {
      if (turnId && !completed && this.child?.stdin?.writable) {
        try {
          await this.request("turn/interrupt", { threadId, turnId }, 10000);
        } catch (interruptError) {
          throw new Error(`${error.message}. Не удалось подтвердить отмену: ${interruptError.message}`);
        }
      }
      throw error;
    } finally {
      completion.reject(new Error("Ожидание анализа завершено"));
      this.listeners.delete(listener);
    }
  }
}

function agentText(value) {
  if (!value) return "";
  if (typeof value === "string") return value;
  if (typeof value.text === "string") return value.text;
  if (Array.isArray(value.content)) {
    return value.content.map((item) => agentText(item)).filter(Boolean).join("\n");
  }
  if (value.message) return agentText(value.message);
  return "";
}

function httpError(message, statusCode) {
  return Object.assign(new Error(message), { statusCode });
}

export class AnalysisJobs {
  constructor(analyze, { retentionMs = 3600000, maxEntries = 100, concurrency = analysisConcurrency, log = console.info } = {}) {
    this.analyze = analyze;
    this.retentionMs = retentionMs;
    this.maxEntries = maxEntries;
    this.log = log;
    this.jobs = new Map();
    this.concurrency = concurrency;
    this.active = 0;
    this.queue = [];
  }

  prune() {
    const now = Date.now();
    for (const [id, job] of this.jobs) {
      if (job.finishedAt && now - job.finishedAt >= this.retentionMs) this.jobs.delete(id);
    }
  }

  publicState(job) {
    return {
      id: job.id,
      status: job.status,
      result: job.status === "completed" ? job.result : null,
      error: job.error,
    };
  }

  start(id, prompt) {
    if (!/^[a-f0-9]{32}$/.test(id)) throw httpError("Некорректный идентификатор анализа", 400);
    if (!prompt.trim()) throw httpError("Пустой запрос анализа", 400);
    this.prune();
    const digest = createHash("sha256").update(prompt).digest("hex");
    const existing = this.jobs.get(id);
    if (existing) {
      if (existing.digest !== digest) throw httpError("Идентификатор уже используется другим запросом", 409);
      return this.publicState(existing);
    }
    if (this.jobs.size >= this.maxEntries) {
      throw httpError("Хранилище анализов заполнено. Дождитесь освобождения завершённых задач", 503);
    }
    const job = {
      id, digest, status: "queued", result: null, error: "", finishedAt: null,
    };
    this.jobs.set(id, job);
    // A single queue limits all callers, including different batches and manual analysis.
    this.queue.push({ job, prompt });
    this.drain();
    return this.publicState(job);
  }

  drain() {
    while (this.active < this.concurrency && this.queue.length) {
      const { job, prompt } = this.queue.shift();
      this.active += 1;
      void this.run(job, prompt).finally(() => {
        this.active -= 1;
        this.drain();
      });
    }
  }

  release(id) {
    const job = this.jobs.get(id);
    if (job && !["completed", "failed"].includes(job.status)) {
      throw httpError("Нельзя удалить незавершённый анализ", 409);
    }
    // The caller has received the result; free capacity for the next products.
    this.jobs.delete(id);
    return { ok: true };
  }

  async run(job, prompt) {
    const startedAt = Date.now();
    job.status = "running";
    this.log(`Attribute ChatGPT ${job.id}: started, prompt_chars=${prompt.length}`);
    try {
      job.result = await this.analyze(prompt);
      job.status = "completed";
    } catch (error) {
      job.status = "failed";
      job.error = error instanceof Error ? error.message : String(error);
    } finally {
      job.finishedAt = Date.now();
      const responseChars = typeof job.result?.text === "string" ? job.result.text.length : 0;
      this.log(`Attribute ChatGPT ${job.id}: ${job.status}, duration_ms=${job.finishedAt - startedAt}, response_chars=${responseChars}`);
    }
  }

  get(id) {
    this.prune();
    const job = this.jobs.get(id);
    if (!job) throw httpError("Анализ не найден: bridge был перезапущен или срок хранения результата истёк", 404);
    return this.publicState(job);
  }
}

function sendJson(response, status, payload) {
  if (response.destroyed || response.writableEnded) return;
  response.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  response.end(JSON.stringify(payload));
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxRequestBytes) throw new Error("Слишком большой запрос");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export function createBridgeServer(codex, { token = bridgeToken, jobs = new AnalysisJobs((prompt) => codex.analyze(prompt)) } = {}) {
  return createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
    if (url.pathname === "/health") {
      sendJson(response, 200, { ok: true });
      return;
    }
    if (token && request.headers.authorization !== `Bearer ${token}`) {
      sendJson(response, 401, { error: "Недействительный токен моста" });
      return;
    }
    if (request.method === "GET" && url.pathname === "/status") {
      sendJson(response, 200, await codex.status());
      return;
    }
    if (request.method === "POST" && url.pathname === "/login/device") {
      sendJson(response, 200, await codex.deviceLogin());
      return;
    }
    if (request.method === "POST" && url.pathname === "/logout") {
      sendJson(response, 200, await codex.logout());
      return;
    }
    if (request.method === "POST" && url.pathname === "/analyses") {
      const body = await readJson(request);
      const state = jobs.start(String(body.request_id || ""), String(body.prompt || ""));
      sendJson(response, 202, state);
      return;
    }
    const analysisPath = /^\/analyses\/([a-f0-9]{32})$/.exec(url.pathname);
    if (request.method === "GET" && analysisPath) {
      sendJson(response, 200, jobs.get(analysisPath[1]));
      return;
    }
    if (request.method === "DELETE" && analysisPath) {
      sendJson(response, 200, jobs.release(analysisPath[1]));
      return;
    }
    sendJson(response, 404, { error: "Маршрут не найден" });
  } catch (error) {
    const tail = (codex.stderrTail || []).join("\n").trim();
    const message = error instanceof Error ? error.message : String(error);
    sendJson(response, error.statusCode || 503, {
      error: message,
      detail: tail ? tail.slice(-2000) : "",
    });
  }
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const server = createBridgeServer(new CodexAppServer());
  server.listen(port, host, () => {
    process.stdout.write(`Attribute AI bridge: http://${host}:${port}\n`);
  });
}

