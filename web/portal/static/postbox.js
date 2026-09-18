(function () {
  var mailboxEl = document.getElementById("mailbox");
  var statusLine = document.getElementById("status-line");
  var listEl = document.getElementById("mail-list");
  var emptyEl = document.getElementById("empty");
  var detailEl = document.getElementById("detail");
  var dSubj = document.getElementById("d-subj");
  var dMeta = document.getElementById("d-meta");
  var dBody = document.getElementById("d-body");
  var dAtt = document.getElementById("d-att");
  var replyForm = document.getElementById("reply-form");
  var replyBody = document.getElementById("reply-body");
  var composeDlg = document.getElementById("compose");
  var composeForm = document.getElementById("compose-form");
  var flushBtn = document.getElementById("flush-outbox");
  var selectedLocalId = null;
  var folder = "INBOX";

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function mailbox() {
    return mailboxEl.value.trim();
  }

  function setFolder(next) {
    folder = next;
    document.querySelectorAll("#folders button").forEach(function (btn) {
      btn.classList.toggle("active", btn.getAttribute("data-folder") === folder);
    });
    flushBtn.hidden = folder !== "OUTBOX";
    selectedLocalId = null;
    detailEl.hidden = true;
    emptyEl.hidden = false;
    emptyEl.textContent =
      folder === "OUTBOX"
        ? "Queued outbound mail. Flush to deliver."
        : folder === "SENT"
          ? "Sent messages."
          : "Select a message. Over LoRa, only headers cross until you open one.";
    refresh();
  }

  async function refresh() {
    var mb = mailbox();
    if (!mb) return;
    var st = await fetch(
      "/api/postbox/status?mailbox=" + encodeURIComponent(mb)
    ).then(function (r) { return r.json(); });
    statusLine.textContent =
      st.address +
      " · " +
      st.unread +
      " unread · outbox " +
      st.outbox +
      " · sent " +
      st.sent;

    var data = await fetch(
      "/api/postbox/messages?mailbox=" +
        encodeURIComponent(mb) +
        "&folder=" +
        encodeURIComponent(folder) +
        "&limit=50"
    ).then(function (r) { return r.json(); });
    listEl.innerHTML = "";
    (data.messages || []).forEach(function (m) {
      var li = document.createElement("li");
      var btn = document.createElement("button");
      btn.type = "button";
      if (!m.read && folder === "INBOX") btn.className = "unread";
      var who = folder === "INBOX" ? m.from : m.to;
      btn.innerHTML =
        '<span class="from">#' +
        esc(m.local_id) +
        " · " +
        esc(who) +
        "</span>" +
        '<span class="subj">' +
        esc(m.subject) +
        (m.has_attachment ? " 📎" : "") +
        "</span>";
      btn.addEventListener("click", function () {
        openMessage(m.local_id);
      });
      li.appendChild(btn);
      listEl.appendChild(li);
    });
  }

  async function openMessage(localId) {
    selectedLocalId = localId;
    var mb = mailbox();
    var msg = await fetch(
      "/api/postbox/messages/" +
        encodeURIComponent(localId) +
        "?mailbox=" +
        encodeURIComponent(mb) +
        "&folder=" +
        encodeURIComponent(folder)
    ).then(function (r) {
      if (!r.ok) throw new Error("not found");
      return r.json();
    });
    emptyEl.hidden = true;
    detailEl.hidden = false;
    dSubj.textContent = msg.subject;
    dMeta.textContent =
      "From " + msg.from + " · To " + msg.to + " · #" + msg.local_id + " · " + folder;
    dBody.textContent = msg.body || "";
    if (msg.has_attachment) {
      dAtt.hidden = false;
      dAtt.textContent =
        (msg.attachment_name || "attachment") +
        (msg.attachment_size ? " · " + msg.attachment_size + " bytes" : "") +
        " · Available over Wi‑Fi";
    } else {
      dAtt.hidden = true;
    }
    replyForm.hidden = folder !== "INBOX";
    refresh();
  }

  document.querySelectorAll("#folders button").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setFolder(btn.getAttribute("data-folder"));
    });
  });

  document.getElementById("refresh").addEventListener("click", refresh);
  mailboxEl.addEventListener("change", function () {
    setFolder(folder);
  });

  flushBtn.addEventListener("click", async function () {
    var res = await fetch("/api/postbox/outbox/flush", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mailbox: mailbox() }),
    });
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      alert(err.detail || "Flush failed");
      return;
    }
    var data = await res.json();
    statusLine.textContent = "Flushed " + data.count + " outbox message(s)";
    refresh();
  });

  document.getElementById("compose-btn").addEventListener("click", function () {
    composeDlg.showModal();
  });

  composeForm.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    var submitter = ev.submitter;
    if (submitter && submitter.value === "cancel") {
      composeDlg.close();
      return;
    }
    var to = document.getElementById("c-to").value.trim();
    var subject = document.getElementById("c-subj").value;
    var body = document.getElementById("c-body").value;
    var queueOnly = submitter && submitter.value === "queue";
    var res = await fetch("/api/postbox/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_user: mailbox(),
        to: to,
        subject: subject,
        body: body,
        queue_only: !!queueOnly,
      }),
    });
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      alert(err.detail || "Send failed");
      return;
    }
    composeDlg.close();
    document.getElementById("c-to").value = "";
    document.getElementById("c-subj").value = "";
    document.getElementById("c-body").value = "";
    setFolder(queueOnly ? "OUTBOX" : "SENT");
  });

  replyForm.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    if (selectedLocalId == null) return;
    var body = replyBody.value.trim();
    if (!body) return;
    var res = await fetch("/api/postbox/reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        from_user: mailbox(),
        local_id: selectedLocalId,
        body: body,
      }),
    });
    if (!res.ok) {
      var err = await res.json().catch(function () { return {}; });
      alert(err.detail || "Reply failed");
      return;
    }
    replyBody.value = "";
    refresh();
  });

  // Compose dialog includes Send / Queue / Cancel
  setFolder("INBOX");
})();
