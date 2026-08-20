import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const host = process.env.ATTRIBUTE_AI_HOST || "127.0.0.1";
const port = Number(process.env.ATTRIBUTE_AI_PORT || 4580);
const bridgeToken = process.env.ATTRIBUTE_CHATGPT_BRIDGE_TOKEN || "";
const codexHome = resolve(process.env.ATTRIBUTE_CODEX_HOME || "./storage/attribute-codex");
const proxyUrl = (process.env.ATTRIBUTE_CHATGPT_PROXY_URL || process.env.ATTRIBUTE_CODEX_PROXY_URL || "").trim();
const requestTimeoutMs = Number(process.env.ATTRIBUTE_CHATGPT_TIMEOUT_MS || 600000);
mkdirSync(codexHome, { recursive: true });

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

class CodexAppServer {
  constructor() {
    this.child = null;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = new Set();
    this.starting = null;
    this.stderrTail = [];
  }

  async ensureStarted() {
    if (this.child && !this.child.killed) return;
    if (this.starting) return this.starting;
    this.starting = this.start();
    try {
      await this.starting;
    } finally {
      this.starting = null;
    }
  }

  async start() {
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
      for (const { reject } of this.pending.values()) reject(error);
      this.pending.clear();
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

  async request(method, params = {}, timeoutMs = requestTimeoutMs) {
    if (method !== "initialize") await this.ensureStarted();
    const id = this.nextId++;
    return new Promise((resolveRequest, rejectRequest) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        rejectRequest(new Error(`Codex не ответил на ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve: resolveRequest, reject: rejectRequest, timer });
      this.write({ id, method, params });
    });
  }

  waitFor(predicate, timeoutMs = requestTimeoutMs) {
    return new Promise((resolveEvent, rejectEvent) => {
      let timer;
      const listener = (message) => {
        if (!predicate(message)) return;
        clearTimeout(timer);
        this.listeners.delete(listener);
        resolveEvent(message);
      };
      timer = setTimeout(() => {
        this.listeners.delete(listener);
        rejectEvent(new Error("Истекло время ожидания ответа ChatGPT"));
      }, timeoutMs);
      this.listeners.add(listener);
    });
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
    const sandboxDir = resolve(codexHome, "attribute-analysis-sandbox");
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
    try {
      const completion = this.waitFor((event) => {
        if (event.method !== "turn/completed") return false;
        const params = event.params || {};
        return (params.threadId || params.thread_id) === threadId;
      });
      const turn = await this.request("turn/start", {
        threadId,
        input: [{ type: "text", text: prompt }],
      }, 60000);
      const turnId = turn?.turn?.id || turn?.turnId || "";
      const event = await completion;
      const status = event.params?.turn?.status || event.params?.status || "completed";
      if (status === "failed") {
        throw new Error(event.params?.turn?.error?.message || "ChatGPT не смог выполнить анализ");
      }
      if (!messages.length) {
        const fallback = agentText(event.params?.turn || event.params || {});
        if (fallback) messages.push(fallback);
      }
      return { thread_id: threadId, turn_id: turnId, text: messages.join("\n").trim() };
    } finally {
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

const codex = new CodexAppServer();

function sendJson(response, status, payload) {
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
    if (size > 1024 * 1024) throw new Error("Слишком большой запрос");
    chunks.push(chunk);
  }
  if (!chunks.length) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", `http://${request.headers.host || "localhost"}`);
    if (url.pathname === "/health") {
      sendJson(response, 200, { ok: true });
      return;
    }
    if (bridgeToken && request.headers.authorization !== `Bearer ${bridgeToken}`) {
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
    if (request.method === "POST" && url.pathname === "/analyze") {
      const body = await readJson(request);
      if (!String(body.prompt || "").trim()) throw new Error("Пустой запрос анализа");
      sendJson(response, 200, await codex.analyze(String(body.prompt)));
      return;
    }
    sendJson(response, 404, { error: "Маршрут не найден" });
  } catch (error) {
    const tail = codex.stderrTail.join("\n").trim();
    const message = error instanceof Error ? error.message : String(error);
    sendJson(response, 503, {
      error: message,
      detail: tail ? tail.slice(-2000) : "",
    });
  }
});

server.listen(port, host, () => {
  process.stdout.write(`Attribute AI bridge: http://${host}:${port}\n`);
});

