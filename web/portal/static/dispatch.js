(function () {
  var meEl = document.getElementById("me");
  var refreshBtn = document.getElementById("refresh-list");
  var newDmBtn = document.getElementById("new-dm");
  var newRoomBtn = document.getElementById("new-room");
  var convListEl = document.getElementById("conv-list");
  var metaEl = document.getElementById("meta");
  var listEl = document.getElementById("messages");
  var form = document.getElementById("composer");
  var bodyEl = document.getElementById("body");
  var sendBtn = form.querySelector("button");

  var conversationId = null;
  var peerHint = null;
  var lastTs = 0;
  var pollTimer = null;

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function transportLabel(t) {
    if (!t) return "";
    if (t === "wifi") return "Wi‑Fi";
    if (t === "lora" || t === "mock") return "LoRa";
    return t;
  }

  function me() {
    return meEl.value.trim();
  }

  function setActive(active) {
    bodyEl.disabled = !active;
    sendBtn.disabled = !active;
  }

  function renderMessages(messages, replace) {
    if (replace) listEl.innerHTML = "";
    var mine = me().toLowerCase();
    messages.forEach(function (m) {
      if (m.created_at && m.created_at > lastTs) lastTs = m.created_at;
      var li = document.createElement("li");
      if (m.sender && m.sender.toLowerCase() === mine) li.className = "mine";
      var when = m.created_at ? new Date(m.created_at * 1000).toLocaleTimeString() : "";
      li.innerHTML =
        '<span class="who">' + esc(m.sender) + "</span>" +
        '<span class="body">' + esc(m.body) + "</span>" +
        '<span class="foot">' + esc(when) +
        (m.transport ? " · " + esc(transportLabel(m.transport)) : "") +
        (m.delivery_state ? " · " + esc(m.delivery_state) : "") +
        "</span>";
      listEl.appendChild(li);
    });
    listEl.scrollTop = listEl.scrollHeight;
  }

  function renderConvList(conversations) {
    convListEl.innerHTML = "";
    conversations.forEach(function (c) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      if (c.id === conversationId) btn.className = "active";
      var preview = c.last_message
        ? c.last_message.sender + ": " + c.last_message.body
        : c.kind === "room"
          ? "Room"
          : "Direct";
      btn.innerHTML =
        '<span class="title">' + esc(c.title || c.id) + "</span>" +
        '<span class="preview">' + esc(preview) + "</span>";
      btn.addEventListener("click", function () {
        openConversation(c.id);
      });
      li.appendChild(btn);
      convListEl.appendChild(li);
    });
  }

  async function refreshList() {
    var username = me();
    if (!username) return;
    var res = await fetch(
      "/api/dispatch/conversations?username=" + encodeURIComponent(username)
    );
    if (!res.ok) return;
    var data = await res.json();
    renderConvList(data.conversations || []);
  }

  async function openConversation(id) {
    conversationId = id;
    peerHint = null;
    lastTs = 0;
    setActive(false);
    metaEl.textContent = "Loading…";
    var res = await fetch("/api/dispatch/conversations/" + encodeURIComponent(id));
    if (!res.ok) {
      metaEl.textContent = "Conversation not found";
      return;
    }
    var data = await res.json();
    var c = data.conversation;
    if (c.kind === "direct") {
      var others = (c.members || []).filter(function (u) {
        return u.toLowerCase() !== me().toLowerCase();
      });
      peerHint = others[0] || null;
    }
    metaEl.textContent =
      (c.title || c.id) +
      " · " +
      c.kind +
      " · " +
      (c.members || []).join(", ");
    renderMessages(data.messages || [], true);
    setActive(true);
    bodyEl.focus();
    await refreshList();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(poll, 1500);
  }

  async function poll() {
    if (!conversationId) return;
    try {
      var url =
        "/api/dispatch/conversations/" +
        encodeURIComponent(conversationId) +
        "/messages?after_ts=" +
        encodeURIComponent(String(lastTs));
      var res = await fetch(url);
      if (!res.ok) return;
      var data = await res.json();
      if (data.messages && data.messages.length) {
        renderMessages(data.messages, false);
        refreshList();
      }
    } catch (e) {
      /* keep polling */
    }
  }

  refreshBtn.addEventListener("click", function () {
    refreshList();
  });

  meEl.addEventListener("change", function () {
    refreshList();
  });

  newDmBtn.addEventListener("click", async function () {
    var peer = window.prompt("Peer username?");
    if (!peer) return;
    var res = await fetch("/api/dispatch/conversations/direct", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_a: me(), user_b: peer.trim() }),
    });
    if (!res.ok) {
      metaEl.textContent = "Could not open DM";
      return;
    }
    var data = await res.json();
    await openConversation(data.conversation.id);
  });

  newRoomBtn.addEventListener("click", async function () {
    var title = window.prompt("Room name?", "crew");
    if (!title) return;
    var membersRaw = window.prompt(
      "Members (comma-separated, include yourself)",
      me() + ", bob"
    );
    if (!membersRaw) return;
    var members = membersRaw.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    if (members.indexOf(me()) === -1) members.unshift(me());
    var res = await fetch("/api/dispatch/conversations/rooms", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title.trim(), members: members, slug: title.trim() }),
    });
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      metaEl.textContent = err.detail || "Could not create room";
      return;
    }
    var data = await res.json();
    await openConversation(data.conversation.id);
  });

  form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var body = bodyEl.value.trim();
    if (!body || !conversationId) return;
    bodyEl.value = "";
    sendBtn.disabled = true;
    var payload = {
      sender: me(),
      body: body,
      transport: "wifi",
      conversation_id: conversationId,
    };
    try {
      var res = await fetch("/api/dispatch/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        var err = await res.json().catch(function () { return {}; });
        throw new Error(err.detail || "Send failed");
      }
      var data = await res.json();
      if (data.created && data.message) renderMessages([data.message], false);
      else await poll();
      refreshList();
    } catch (err) {
      metaEl.textContent = String(err.message || err);
      bodyEl.value = body;
    } finally {
      sendBtn.disabled = false;
      bodyEl.focus();
    }
  });

  refreshList();
})();
