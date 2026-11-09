const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const vm = require("node:vm");
const { EventEmitter } = require("node:events");
const { Readable } = require("node:stream");

// Exercise the real bridge handlers with disposable files and a fake WhatsApp socket.
function bridge(t, authGate = Promise.resolve(), saveGate = Promise.resolve(), messageOptions = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "nexora-wa-test-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const routes = {};
  const sockets = [];
  const timers = [];
  const webhooks = [];
  const sent = [];
  const downloads = [];
  const downloadCalls = [];
  let authCalls = 0;
  let onListening;
  const app = {
    use() {}, param() {},
    listen(port, host, callback) { onListening = callback; },
    get(route, handler) { routes[`GET ${route}`] = handler; },
    post(route, handler) { routes[`POST ${route}`] = handler; },
  };
  const express = Object.assign(() => app, { json: () => null });
  const baileys = {
    DisconnectReason: { loggedOut: 401 },
    async downloadMediaMessage(message, type, options) {
      downloads.push(message.key.id);
      downloadCalls.push({ id: message.key.id, type, options });
      const wait = Promise.resolve(messageOptions.download?.(message, options));
      const signal = options?.options?.signal;
      if (signal) {
        let abort;
        try {
          await new Promise((resolve, reject) => {
            abort = () => reject(new Error("Fixture transport aborted"));
            if (signal.aborted) return abort();
            signal.addEventListener("abort", abort, { once: true });
            wait.then(resolve, reject);
          });
        } finally {
          signal.removeEventListener("abort", abort);
        }
      } else {
        await wait;
      }
      return type === "stream" ? (messageOptions.stream?.(message) || Readable.from([Buffer.from("fixture-photo")])) : Buffer.from("fixture-photo");
    },
    async useMultiFileAuthState(folder) {
      authCalls++;
      await authGate;
      return { state: {}, saveCreds: async () => {
        await saveGate;
        await fs.promises.writeFile(path.join(folder, "creds.json"), "{}");
      } };
    },
    default() {
      let onClose;
      const closed = new Promise(resolve => { onClose = resolve; });
      const socket = {
        closed,
        ev: new EventEmitter(),
        async sendMessage(jid, body) { sent.push({ jid, body }); return {}; },
        end() {
          this.ended = true;
          onClose();
          this.ev.emit("connection.update", { connection: "close" });
        },
      };
      sockets.push(socket);
      return socket;
    },
  };
  const context = vm.createContext({
    __dirname: directory,
    process: { env: {} },
    Buffer,
    AbortController,
    console: { log() {}, warn() {}, error() {} },
    setTimeout(fn, delay) { const timer = { fn, delay, cleared: false }; timers.push(timer); return timer; },
    clearTimeout(timer) { if (timer) timer.cleared = true; },
    fetch: async (url, options) => {
      if (!url.endsWith("/api/webhook/wa/")) throw new Error("Network disabled in tests");
      const body = JSON.parse(options.body);
      webhooks.push(body);
      await messageOptions.webhook?.(body);
      return { ok: true, json: async () => ({ reply: body.image ? "Photo received." : `Reply: ${body.text}`, media: [] }) };
    },
    require(name) {
      if (name === "express") return express;
      if (name === "@whiskeysockets/baileys") return baileys;
      if (name === "qrcode") return { toDataURL: async () => "data:image/png;base64,test" };
      return require(name);
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "index.js"), "utf8"), context);
  return {
    sockets, timers, routes, webhooks, sent, downloads, downloadCalls,
    folder: (id) => path.join(directory, "sessions", id),
    authCalls: () => authCalls,
    resumeSaved: () => onListening(),
    start: (id) => context.startSession(id),
    async receive(id, messageId, message, jid = "100@s.whatsapp.net") {
      return this.receiveBatch(id, [{ key: { id: messageId, remoteJid: jid }, message }]);
    },
    async receiveBatch(id, messages) {
      const s = await context.startSession(id);
      const handler = s.sock.ev.listeners("messages.upsert")[0];
      return handler({ messages });
    },
    async api(method, route, id, body = {}) {
      const handler = routes[`${method} ${route}`];
      assert.ok(handler, `${method} ${route} must exist`);
      const result = { code: 200 };
      const response = {
        status(code) { result.code = code; return this; },
        json(body) { result.body = body; return this; },
      };
      await handler({ params: { tid: id }, body }, response);
      return result;
    },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

function incoming(id, message, jid = "100@s.whatsapp.net") {
  return { key: { id, remoteJid: jid }, message };
}

test("a photo deadline aborts a stalled transport and releases the next question", { timeout: 3000 }, async (t) => {
  const gate = deferred();
  const started = deferred();
  t.after(gate.resolve);
  const h = bridge(t, undefined, undefined, { download: async () => { started.resolve(); await gate.promise; } });
  const photo = h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  await started.promise;
  const question = h.receive("12", "question", { conversation: "Aita ache?" });
  try {
    await h.receive("12", "barrier", { conversation: "Hello" }, "200@s.whatsapp.net");
    const deadline = h.timers.find(timer => timer.delay === 30000);
    assert.ok(deadline, "A photo download must have a cancellable deadline");
    const options = h.downloadCalls[0].options.options;
    assert.equal(options.timeout, 30000);
    deadline.fn();
    await Promise.all([photo, question]);
    assert.equal(options.signal.aborted, true);
    assert.deepEqual(h.webhooks.filter(body => body.phone === "100").map(body => body.text), ["Aita ache?"]);
    assert.match(h.sent.find(item => item.jid === "100@s.whatsapp.net").body.text, /photo.*resend|resend.*photo/i);
  } finally {
    gate.resolve();
    await Promise.allSettled([photo, question]);
  }
});

test("a photo deadline destroys a stalled decrypted body stream", { timeout: 3000 }, async (t) => {
  const reading = deferred();
  const body = new Readable({ read() { reading.resolve(); } });
  t.after(() => body.destroy());
  const started = deferred();
  const h = bridge(t, undefined, undefined, { download: () => started.resolve(), stream: () => body });
  const photo = h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  let question;
  try {
    await started.promise;
    assert.equal(h.downloadCalls[0].type, "stream");
    await reading.promise;
    question = h.receive("12", "question", { conversation: "Question" });
    h.timers.find(timer => timer.delay === 30000).fn();
    await Promise.all([photo, question]);
    assert.equal(body.destroyed, true);
    assert.equal(h.downloadCalls[0].options.options.signal.aborted, true);
    assert.deepEqual(h.webhooks.map(message => message.text), ["Question"]);
  } finally {
    body.destroy();
    await Promise.allSettled([photo, question]);
  }
});

test("an oversized incoming photo is bounded and asks for a retry", async (t) => {
  const body = Readable.from([Buffer.alloc(4 * 1024 * 1024 + 1)]);
  t.after(() => body.destroy());
  const h = bridge(t, undefined, undefined, { stream: () => body });
  await h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  assert.equal(h.webhooks.length, 0);
  assert.equal(body.destroyed, true);
  assert.match(h.sent[0].body.text, /photo.*resend|resend.*photo/i);
});

test("pending messages are bounded per customer with one wait-and-resend notice", { timeout: 3000 }, async (t) => {
  const gate = deferred();
  const started = deferred();
  t.after(gate.resolve);
  const h = bridge(t, undefined, undefined, { webhook: async message => {
    if (message.image) { started.resolve(); await gate.promise; }
  } });
  const photo = h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  await started.promise;
  const pending = Array.from({ length: 40 }, (_, i) => h.receive("12", `q-${i}`, { conversation: `Question ${i}` }));
  await h.receive("12", "barrier", { conversation: "Hello" }, "200@s.whatsapp.net");
  const notices = h.sent.filter(item => item.jid === "100@s.whatsapp.net" && /wait.*resend/i.test(item.body.text));
  gate.resolve();
  await Promise.all([photo, ...pending]);
  assert.equal(h.webhooks.filter(message => message.phone === "100").length, 16);
  assert.equal(notices.length, 1);
  await h.receive("12", "after-drain", { conversation: "After drain" });
  assert.equal(h.webhooks.filter(message => message.phone === "100").length, 17);
});

test("pending work across customers is bounded for a connected session", { timeout: 3000 }, async (t) => {
  const gate = deferred();
  t.after(gate.resolve);
  const h = bridge(t, undefined, undefined, { download: () => gate.promise });
  const pending = Array.from({ length: 50 }, (_, i) => h.receive("12", `photo-${i}`, { imageMessage: { mimetype: "image/png" } }, `${100 + i}@s.whatsapp.net`));
  await Promise.resolve();
  await Promise.resolve();
  gate.resolve();
  await Promise.all(pending);
  assert.equal(h.downloads.length, 32);
  assert.equal(h.webhooks.length, 32);
});

test("a batch enqueues its photo and first question before a later event", { timeout: 3000 }, async (t) => {
  const gate = deferred();
  const started = deferred();
  t.after(gate.resolve);
  const h = bridge(t, undefined, undefined, { download: async () => { started.resolve(); await gate.promise; } });
  const batch = h.receiveBatch("12", [
    incoming("photo", { imageMessage: { mimetype: "image/png" } }),
    incoming("question-1", { conversation: "First question" }),
  ]);
  await started.promise;
  const later = h.receive("12", "question-2", { conversation: "Later question" });
  await h.receive("12", "barrier", { conversation: "Hello" }, "200@s.whatsapp.net");
  gate.resolve();
  await Promise.all([batch, later]);
  assert.deepEqual(h.webhooks.filter(body => body.phone === "100").map(body => body.image ? "photo" : body.text), ["photo", "First question", "Later question"]);
});

test("a batch containing a blocked customer does not block another customer", { timeout: 3000 }, async (t) => {
  const gate = deferred();
  const started = deferred();
  t.after(gate.resolve);
  const h = bridge(t, undefined, undefined, { download: async () => { started.resolve(); await gate.promise; } });
  const photo = h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  await started.promise;
  const batch = h.receiveBatch("12", [
    incoming("question", { conversation: "Question" }),
    incoming("other", { conversation: "Other customer" }, "200@s.whatsapp.net"),
  ]);
  await h.receive("12", "barrier", { conversation: "Hello" }, "300@s.whatsapp.net");
  const otherProceeded = h.webhooks.some(body => body.phone === "200");
  gate.resolve();
  await Promise.all([photo, batch]);
  assert.equal(otherProceeded, true);
});

test("a delayed photo precedes its question while other customers stay independent", { timeout: 3000 }, async (t) => {
  const download = deferred();
  const started = deferred();
  t.after(download.resolve);
  const h = bridge(t, undefined, undefined, { download: async () => {
    started.resolve();
    await download.promise;
  } });
  const photo = h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  await started.promise;
  const question = h.receive("12", "question", { conversation: "Aita ache?" });
  await h.receive("12", "other-customer", { conversation: "Hello" }, "200@s.whatsapp.net");
  download.resolve();
  await Promise.all([photo, question]);
  const sameChat = h.webhooks.filter(body => body.phone === "100");
  assert.deepEqual(sameChat.map(body => Boolean(body.image)), [true, false]);
  assert.equal(sameChat[1].text, "Aita ache?");
  assert.equal(h.webhooks[0].phone, "200");
  assert.deepEqual(h.sent.filter(item => item.jid === "100@s.whatsapp.net").map(item => item.body.text), ["Photo received.", "Reply: Aita ache?"]);
});

test("a follow-up waits for the earlier webhook reply so chat saves cannot overlap", { timeout: 3000 }, async (t) => {
  const response = deferred();
  const started = deferred();
  let photoFinished = false;
  let prematureQuestion = false;
  t.after(response.resolve);
  const h = bridge(t, undefined, undefined, { webhook: async body => {
    if (body.image) {
      started.resolve();
      await response.promise;
      photoFinished = true;
    } else if (body.phone === "100" && !photoFinished) {
      prematureQuestion = true;
    }
  } });
  const photo = h.receive("12", "photo", { imageMessage: { mimetype: "image/png" } });
  await started.promise;
  const question = h.receive("12", "question", { conversation: "Is it available?" });
  await h.receive("12", "other", { conversation: "Hello" }, "200@s.whatsapp.net");
  response.resolve();
  await Promise.all([photo, question]);
  assert.equal(prematureQuestion, false);
});

test("a failed webhook does not block the next message in the same chat", async (t) => {
  const h = bridge(t, undefined, undefined, { webhook: async body => {
    if (body.text === "first") throw new Error("Fixture request failed");
  } });
  await Promise.all([
    h.receive("12", "first", { conversation: "first" }),
    h.receive("12", "second", { conversation: "second" }),
  ]);
  assert.deepEqual(h.webhooks.map(body => body.text), ["first", "second"]);
  assert.deepEqual(h.sent.map(item => item.body.text), ["Reply: second"]);
});

test("removed sessions cancel pending messages without blocking their replacement", { timeout: 3000 }, async (t) => {
  const download = deferred();
  const started = deferred();
  t.after(download.resolve);
  const h = bridge(t, undefined, undefined, { download: async () => {
    started.resolve();
    await download.promise;
  } });
  const photo = h.receive("12", "old-photo", { imageMessage: { mimetype: "image/png" } });
  await started.promise;
  const pending = h.receive("12", "old-question", { conversation: "Old question" });
  await h.receive("12", "other", { conversation: "Hello" }, "200@s.whatsapp.net");
  await h.api("POST", "/wa/:tid/remove", "12");
  await h.receive("12", "new-session", { conversation: "New question" });
  download.resolve();
  await Promise.all([photo, pending]);
  assert.deepEqual(h.webhooks.filter(body => body.phone === "100").map(body => body.text), ["New question"]);
  assert.deepEqual(h.sent.filter(item => item.jid === "100@s.whatsapp.net").map(item => item.body.text), ["Reply: New question"]);
});

test("checking status never creates a session or folder", async (t) => {
  const h = bridge(t);
  const result = await h.api("GET", "/wa/:tid/status", "12");
  assert.equal(result.body.status, "DISCONNECTED");
  assert.equal(h.authCalls(), 0);
  assert.equal(fs.existsSync(h.folder("12")), false);
});

test("sending while disconnected reports the problem without starting WhatsApp", async (t) => {
  const h = bridge(t);
  const result = await h.api("POST", "/wa/:tid/send", "12", { phone: "8801700000000", text: "Hello" });
  assert.equal(result.code, 409);
  assert.equal(result.body.ok, false);
  assert.equal(h.authCalls(), 0);
  assert.equal(fs.existsSync(h.folder("12")), false);
});

test("startup restores saved credentials and ignores empty session folders", async (t) => {
  const h = bridge(t);
  fs.mkdirSync(h.folder("12"), { recursive: true });
  fs.writeFileSync(path.join(h.folder("12"), "creds.json"), "{}");
  fs.mkdirSync(h.folder("13"), { recursive: true });
  h.resumeSaved();
  assert.equal(h.authCalls(), 1);
  await h.start("12");
  const empty = await h.api("GET", "/wa/:tid/status", "13");
  assert.equal(empty.body.status, "DISCONNECTED");
});

test("explicit connect starts once and exposes a QR code", async (t) => {
  const h = bridge(t);
  await h.api("POST", "/wa/:tid/connect", "12");
  await h.api("POST", "/wa/:tid/connect", "12");
  assert.equal(h.authCalls(), 1);
  h.sockets[0].ev.emit("connection.update", { qr: "test-qr" });
  const status = await h.api("GET", "/wa/:tid/status", "12");
  assert.equal(status.body.status, "QR_READY");
  assert.match(status.body.qr, /^data:image\/png/);
});

test("removal forgets credentials and cancels even an already queued reconnect", async (t) => {
  const h = bridge(t);
  await h.start("12");
  await h.sockets[0].ev.listeners("creds.update")[0]();
  h.sockets[0].ev.emit("connection.update", { connection: "close" });
  const pending = h.timers[0];
  assert.ok(pending);
  const result = await h.api("POST", "/wa/:tid/remove", "12");
  assert.equal(result.body.ok, true);
  await pending.fn();
  assert.equal(pending.cleared, true);
  assert.equal(h.authCalls(), 1);
  assert.equal(fs.existsSync(h.folder("12")), false);
});

test("removal waits for an in-flight start and prevents a late socket", async (t) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const h = bridge(t, gate);
  assert.ok(h.routes["POST /wa/:tid/remove"]);
  const starting = h.start("12");
  const stopping = h.api("POST", "/wa/:tid/remove", "12");
  release();
  await Promise.all([starting, stopping]);
  assert.equal(h.sockets.length, 0);
  assert.equal(fs.existsSync(h.folder("12")), false);
});

test("late events from an old socket cannot revive or close its replacement", async (t) => {
  const h = bridge(t);
  await h.start("12");
  const old = h.sockets[0];
  await h.api("POST", "/wa/:tid/remove", "12");
  await h.api("POST", "/wa/:tid/connect", "12");
  h.sockets[1].ev.emit("connection.update", { connection: "open" });
  old.ev.emit("connection.update", { connection: "close" });
  await old.ev.listeners("creds.update")[0]();
  const status = await h.api("GET", "/wa/:tid/status", "12");
  assert.equal(status.body.status, "CONNECTED");
  assert.equal(fs.existsSync(path.join(h.folder("12"), "creds.json")), false);
});

test("removal during reset leaves no replacement socket or session files", async (t) => {
  let releaseSave;
  const saveGate = new Promise(resolve => { releaseSave = resolve; });
  const h = bridge(t, Promise.resolve(), saveGate);
  await h.start("12");
  const old = h.sockets[0];
  const saving = old.ev.listeners("creds.update")[0]();
  await Promise.resolve(); // Let the credential write enter its deferred save.
  const resetting = h.api("POST", "/wa/:tid/reset", "12");
  await old.closed;
  old.ev.emit("creds.update");
  const removing = h.api("POST", "/wa/:tid/remove", "12");
  releaseSave();
  const [, reset, remove] = await Promise.all([saving, resetting, removing]);
  assert.equal(reset.body.ok, true);
  assert.equal(remove.body.ok, true);
  const status = await h.api("GET", "/wa/:tid/status", "12");
  assert.equal(status.body.status, "DISCONNECTED");
  assert.ok(h.sockets.every(socket => socket.ended));
  assert.equal(fs.existsSync(h.folder("12")), false);
});
