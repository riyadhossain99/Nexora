const fs = require("fs");
const path = require("path");
const express = require("express");
const QRCode = require("qrcode");
const baileys = require("@whiskeysockets/baileys");
const { useMultiFileAuthState, DisconnectReason, downloadMediaMessage } = baileys;
const makeWASocket = baileys.default || baileys.makeWASocket;

const PORT = process.env.PORT || 3001;
const DJANGO = process.env.DJANGO_URL || "http://127.0.0.1:8000";
const SESSIONS = path.join(__dirname, "sessions");
const MEDIA = path.resolve(__dirname, "..", "..", "frontend", "media");
const PHOTO_TIMEOUT = 30000;
const MAX_PHOTO_BYTES = 4 * 1024 * 1024;
const MAX_CHAT_PENDING = 16;
const MAX_SESSION_PENDING = 32;
const sessions = {};
const controls = {};
const seen = new Set();

async function resolveImageMedia(item) {
  if (!item) return null;
  const rawUrl = typeof item === "string" ? item : (item.url || item.image || "");
  const caption = (typeof item === "object" && item.caption) ? String(item.caption) : "";
  if (!rawUrl) return null;

  if (rawUrl.startsWith("/media/")) {
    const localPath = path.resolve(MEDIA, rawUrl.slice("/media/".length));
    if (!localPath.startsWith(MEDIA + path.sep)) return null;
    if (fs.existsSync(localPath)) {
      return { image: fs.readFileSync(localPath), caption };
    }
    return null;
  }

  if (rawUrl.startsWith("http://") || rawUrl.startsWith("https://")) {
    try {
      const resp = await fetch(rawUrl);
      if (resp.ok) {
        const buf = Buffer.from(await resp.arrayBuffer());
        return { image: buf, caption };
      }
    } catch (e) {}
    return { image: { url: rawUrl }, caption };
  }

  return null;
}

async function sendMediaMessage(sock, jid, item) {
  const mediaObj = await resolveImageMedia(item);
  if (!mediaObj) return false;
  await sock.sendMessage(jid, mediaObj);
  return true;
}

async function downloadIncomingImage(message, session) {
  const controller = new AbortController();
  session.downloads.add(controller);
  let stream;
  const interrupt = () => stream?.destroy(new Error("Photo download interrupted"));
  controller.signal.addEventListener("abort", interrupt, { once: true });
  const timer = setTimeout(() => controller.abort(), PHOTO_TIMEOUT);
  timer.unref?.();
  try {
    // Baileys nests Axios options; cancelling the HTTP request alone doesn't end its output pipe.
    stream = await downloadMediaMessage(message, "stream", {
      options: { timeout: PHOTO_TIMEOUT, signal: controller.signal },
    });
    if (controller.signal.aborted) throw new Error("Photo download interrupted");
    const chunks = [];
    let size = 0;
    for await (const chunk of stream) {
      size += chunk.length;
      if (size > MAX_PHOTO_BYTES) throw new Error("Photo is too large");
      chunks.push(chunk);
    }
    if (!size) throw new Error("Photo is empty");
    return Buffer.concat(chunks);
  } finally {
    clearTimeout(timer);
    controller.signal.removeEventListener("abort", interrupt);
    stream?.destroy();
    controller.abort();
    session.downloads.delete(controller);
  }
}

async function _start(tid, s) {
  const dir = path.join(SESSIONS, tid);
  fs.mkdirSync(dir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(dir);
  if (s.stopped) return;
  const sock = makeWASocket({ auth: state, printQRInTerminal: false });
  s.sock = sock;

  sock.ev.on("creds.update", () => {
    if (s.stopped || sessions[tid] !== s) return s.saving;
    s.saving = s.saving.then(() => {
      if (!s.stopped && sessions[tid] === s) return saveCreds();
    }).catch(error => console.error(`[wa:${tid}] saving credentials: ${error.message}`));
    return s.saving;
  });

  sock.ev.on("connection.update", ({ connection, qr, lastDisconnect }) => {
    if (s.stopped || sessions[tid] !== s) return;
    if (qr) {
      s.qr = qr;
      s.status = "QR_READY";
    }
    if (connection === "open") {
      s.qr = null;
      s.status = "CONNECTED";
    }
    if (connection === "close") {
      s.status = "DISCONNECTED";
      s.qr = null;
      const loggedOut =
        lastDisconnect?.error?.output?.statusCode === DisconnectReason.loggedOut;
      if (loggedOut) {
        stopSession(tid).catch(error => console.error(`[wa:${tid}] logout: ${error.message}`));
      } else {
        clearTimeout(s.retryTimer);
        s.retryTimer = setTimeout(() => {
          if (s.stopped || sessions[tid] !== s) return;
          delete sessions[tid];
          return startSession(tid).catch(error => console.error(`[wa:${tid}] reconnect: ${error.message}`));
        }, 2000);
      }
    }
  });

  sock.ev.on("messages.upsert", async ({ messages }) => {
    const work = [];
    for (const m of messages) {
      if (s.stopped || sessions[tid] !== s) return;
      if (!m.message || m.key.fromMe || !m.key.remoteJid) continue;
      if (m.key.remoteJid.endsWith("@g.us") || seen.has(m.key.id)) continue;
      seen.add(m.key.id);
      if (seen.size > 2000) seen.clear();

      // Normalize JID (removes companion device suffixes like :1 or :2 that cause sending failures)
      const rawJid = m.key.remoteJid;
      const cleanJid = baileys.jidNormalizedUser ? baileys.jidNormalizedUser(rawJid) : rawJid;
      const phone = cleanJid.split("@")[0].replace(/\D/g, "");

      if ((s.pending[cleanJid] || 0) >= MAX_CHAT_PENDING || s.pendingTotal >= MAX_SESSION_PENDING) {
        if (!s.notices[cleanJid]) {
          s.notices[cleanJid] = true;
          const noticeTimer = setTimeout(() => { delete s.notices[cleanJid]; }, 60000);
          noticeTimer.unref?.();
          work.push(Promise.resolve().then(async () => {
            if (s.stopped || sessions[tid] !== s) return;
            await sock.sendMessage(cleanJid, { text: "Please wait for my earlier replies, then resend any unanswered messages." });
          }));
        }
        continue;
      }
      s.pending[cleanJid] = (s.pending[cleanJid] || 0) + 1;
      s.pendingTotal++;

      // Keep a follow-up behind its photo download and completed agent reply.
      work.push(controlSession(cleanJid, async () => {
        if (s.stopped || sessions[tid] !== s) return;

        // Unwrap messages that might be wrapped inside ephemeral or view-once containers
        const unwrap = (msg) => {
          if (!msg) return {};
          if (msg.ephemeralMessage?.message) return unwrap(msg.ephemeralMessage.message);
          if (msg.viewOnceMessage?.message) return unwrap(msg.viewOnceMessage.message);
          if (msg.viewOnceMessageV2?.message) return unwrap(msg.viewOnceMessageV2.message);
          if (msg.documentWithCaptionMessage?.message) return unwrap(msg.documentWithCaptionMessage.message);
          return msg;
        };
        const inner = unwrap(m.message);

        const img = inner.imageMessage;
        const text =
          inner.conversation ||
          inner.extendedTextMessage?.text ||
          img?.caption ||
          inner.videoMessage?.caption ||
          "";

        console.log(`[wa:${tid}] 📩 Received from ${phone} (${cleanJid}): "${text.slice(0, 70)}"`);

        let image = null;
        if (img) {
          try {
            const buf = await downloadIncomingImage(m, s);
            image = { mime: img.mimetype || "image/jpeg", b64: buf.toString("base64") };
          } catch (e) {
            console.error(`[wa:${tid}] media error: ${e.message}`);
            if (s.stopped || sessions[tid] !== s) return;
            try {
              await sock.sendMessage(cleanJid, { text: "I could not download that photo. Please resend it, preferably as a smaller photo." });
            } catch (sendError) {
              console.error(`[wa:${tid}] photo retry notice: ${sendError.message}`);
            }
            return;
          }
        }
        if (s.stopped || sessions[tid] !== s) return;

        try {
          console.log(`[wa:${tid}] 🤖 Calling Django webhook (${DJANGO}/api/webhook/wa/)...`);
          const r = await fetch(`${DJANGO}/api/webhook/wa/`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ tenant_id: tid, phone, text, image }),
          });
          if (!r.ok) {
            const errText = await r.text();
            console.error(`[wa:${tid}] ❌ Django webhook returned HTTP ${r.status}: ${errText.slice(0, 160)}`);
            return;
          }
          const data = await r.json();
          if (s.stopped || sessions[tid] !== s) return;
          console.log(`[wa:${tid}] 💬 AI reply ready: "${(data.reply || "").slice(0, 70)}" (media: ${data.media?.length || 0})`);

          if (data.media && Array.isArray(data.media) && data.media.length > 0) {
            for (const item of data.media) {
              try {
                await sendMediaMessage(sock, cleanJid, item);
                console.log(`[wa:${tid}] 📸 Sent media to ${cleanJid}`);
              } catch (err) {
                console.error(`[wa:${tid}] ❌ Failed to send media: ${err.message}`);
              }
            }
          }
          if (data.reply) {
            try {
              await sock.sendMessage(cleanJid, { text: data.reply });
              console.log(`[wa:${tid}] ✅ Sent reply to ${cleanJid}`);
            } catch (sendErr) {
              console.error(`[wa:${tid}] ❌ Failed to send WhatsApp message: ${sendErr.message}`);
            }
          } else {
            console.warn(`[wa:${tid}] ⚠️ Django returned no reply text.`);
          }
        } catch (e) {
          console.error(`[wa:${tid}] ❌ Webhook error: ${e.message}`);
        }
      }, s.inbound).finally(() => {
        s.pendingTotal--;
        if (--s.pending[cleanJid] === 0) delete s.pending[cleanJid];
      }));
    }
    // Register the whole batch first, otherwise a later event can overtake its later entries.
    const results = await Promise.allSettled(work);
    for (const result of results) {
      if (result.status === "rejected") console.error(`[wa:${tid}] message error: ${result.reason?.message || result.reason}`);
    }
  });

  return s;
}

function startSession(tid) {
  const current = sessions[tid];
  if (current?.stopped) return Promise.reject(new Error("Session is stopping. Try again shortly."));
  if (current) return current.ready;
  const s = {
    status: "CONNECTING", qr: null, sock: null, stopped: false, retryTimer: null,
    saving: Promise.resolve(), inbound: Object.create(null), pending: Object.create(null),
    pendingTotal: 0, notices: Object.create(null), downloads: new Set(),
  };
  sessions[tid] = s;
  s.ready = _start(tid, s).then(() => s).catch(error => {
    if (sessions[tid] === s) delete sessions[tid];
    // A failed first connection need not leave an empty folder behind.
    try { fs.rmdirSync(path.join(SESSIONS, tid)); } catch {}
    throw error;
  });
  return s.ready;
}

async function stopSession(tid) {
  const s = sessions[tid];
  if (!s) {
    fs.rmSync(path.join(SESSIONS, tid), { recursive: true, force: true });
    return;
  }
  if (s.stopping) return s.stopping;
  s.stopped = true;
  for (const controller of s.downloads) controller.abort();
  clearTimeout(s.retryTimer);
  s.stopping = (async () => {
    if (s.sock) s.sock.end(undefined);
    await s.ready.catch(() => {});
    await s.saving;
    if (sessions[tid] !== s) return;
    fs.rmSync(path.join(SESSIONS, tid), { recursive: true, force: true });
    delete sessions[tid];
  })().catch(error => {
    s.stopping = null;
    throw error;
  });
  return s.stopping;
}

function controlSession(tid, operation, queue = controls) {
  // Session controls and each session's customer inbox use independent queues.
  const previous = queue[tid];
  const next = previous ? previous.catch(() => {}).then(operation) : Promise.resolve(operation());
  queue[tid] = next;
  return next.finally(() => {
    if (queue[tid] === next) delete queue[tid];
  });
}

const app = express();
app.use(express.json({ limit: "30mb" }));

app.param("tid", (req, res, next, tid) => {
  if (!/^\d+$/.test(tid)) return res.status(400).json({ error: "invalid tenant id" });
  next();
});

app.get("/wa/:tid/status", async (req, res) => {
  try {
    const s = sessions[req.params.tid];
    res.json({
      status: s && !s.stopped ? s.status : "DISCONNECTED",
      qr: s?.qr && !s.stopped ? await QRCode.toDataURL(s.qr, { width: 320 }) : null,
    });
  } catch (e) {
    res.status(500).json({ status: "ERROR", error: e.message });
  }
});

app.post("/wa/:tid/connect", async (req, res) => {
  try {
    const tid = req.params.tid;
    const s = await controlSession(tid, () => startSession(tid));
    res.json({ ok: true, status: s.status });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.post("/wa/:tid/send", async (req, res) => {
  try {
    const { phone, text, image, caption } = req.body || {};
    const s = sessions[req.params.tid];
    if (!s || s.stopped || s.status !== "CONNECTED") {
      return res.status(409).json({ ok: false, error: "WhatsApp is disconnected. Open Settings and click Connect." });
    }
    const jid = `${String(phone).replace(/\D/g, "")}@s.whatsapp.net`;
    if (image) {
      const sent = await sendMediaMessage(s.sock, jid, { url: image, caption: caption || text || "" });
      if (!sent) return res.status(400).json({ ok: false, error: "Product image is unavailable." });
    } else {
      await s.sock.sendMessage(jid, { text: String(text || "") });
    }
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post("/wa/:tid/remove", async (req, res) => {
  try {
    const tid = req.params.tid;
    await controlSession(tid, () => stopSession(tid));
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post("/wa/:tid/reset", async (req, res) => {
  try {
    const tid = req.params.tid;
    await controlSession(tid, async () => {
      await stopSession(tid);
      await startSession(tid);
    });
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.listen(PORT, "127.0.0.1", () => {
  console.log(`wa_bridge listening on :${PORT}`);
  // Automatically resume previously authenticated WhatsApp sessions
  if (fs.existsSync(SESSIONS)) {
    try {
      const dirs = fs.readdirSync(SESSIONS);
      for (const d of dirs) {
        if (/^\d+$/.test(d) && fs.existsSync(path.join(SESSIONS, d, "creds.json"))) {
          console.log(`[wa_bridge] Auto-resuming saved WhatsApp session for tenant ${d}...`);
          startSession(d).catch((e) => console.error(`[wa_bridge] Failed to auto-resume session ${d}: ${e.message}`));
        }
      }
    } catch (e) {
      console.error(`[wa_bridge] Error reading sessions directory: ${e.message}`);
    }
  }
});
