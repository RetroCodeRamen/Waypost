(function () {
  var makeOutpostCodeBtn = document.getElementById("make-outpost-code");
  var outpostCodeDisplay = document.getElementById("outpost-code-display");
  var outpostCodeValue = document.getElementById("outpost-code-value");
  var outpostCodeExpiry = document.getElementById("outpost-code-expiry");
  var outpostCodeTimer = null;

  function formatCountdown(expiresAt) {
    var secs = Math.max(0, Math.round(expiresAt - Date.now() / 1000));
    var m = Math.floor(secs / 60);
    var s = secs % 60;
    return "expires in " + m + ":" + (s < 10 ? "0" : "") + s;
  }

  makeOutpostCodeBtn.addEventListener("click", async function () {
    makeOutpostCodeBtn.disabled = true;
    var res = await fetch("/api/auth/pairing/create", {
      method: "POST",
      credentials: "same-origin",
    });
    makeOutpostCodeBtn.disabled = false;
    if (!res.ok) return;
    var body = await res.json();
    outpostCodeValue.textContent = body.code;
    outpostCodeDisplay.hidden = false;
    if (outpostCodeTimer) clearInterval(outpostCodeTimer);
    function tick() {
      var left = body.expires_at - Date.now() / 1000;
      if (left <= 0) {
        outpostCodeExpiry.textContent = "expired — generate a new one";
        clearInterval(outpostCodeTimer);
        return;
      }
      outpostCodeExpiry.textContent = formatCountdown(body.expires_at);
    }
    tick();
    outpostCodeTimer = setInterval(tick, 1000);
  });

  var outpostsEl = document.getElementById("outposts");
  var outpostsEmptyEl = document.getElementById("outposts-empty");
  var boardPanel = document.getElementById("board-panel");
  var boardNameEl = document.getElementById("board-outpost-name");
  var notesEl = document.getElementById("notes");
  var notesEmptyEl = document.getElementById("notes-empty");
  var postForm = document.getElementById("post-form");
  var postBody = document.getElementById("post-body");
  var postSignature = document.getElementById("post-signature");
  var selectedOutpostId = null;

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatAgo(ts) {
    if (!ts) return "never";
    var mins = Math.round((Date.now() / 1000 - ts) / 60);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    return Math.round(mins / 60) + "h ago";
  }

  async function selectOutpost(id, displayName) {
    selectedOutpostId = id;
    boardNameEl.textContent = displayName || id;
    boardPanel.hidden = false;
    document.querySelectorAll("#outposts li").forEach(function (li) {
      li.classList.toggle("selected", li.dataset.outpostId === id);
    });
    await refreshNotes();
  }

  async function refreshOutposts() {
    var res = await fetch("/api/corkboard/outposts", { credentials: "same-origin" });
    if (!res.ok) return;
    var data = await res.json();
    var outposts = data.outposts || [];
    outpostsEl.innerHTML = "";
    outpostsEmptyEl.hidden = outposts.length > 0;
    outposts.forEach(function (o) {
      var li = document.createElement("li");
      li.dataset.outpostId = o.node_id;
      if (o.node_id === selectedOutpostId) li.classList.add("selected");
      li.innerHTML =
        '<div class="outpost-name">' + esc(o.display_name || o.node_id) + '</div>' +
        '<div class="muted">last heard ' + esc(formatAgo(o.last_seen_at)) + '</div>';
      li.addEventListener("click", function () {
        selectOutpost(o.node_id, o.display_name);
      });
      outpostsEl.appendChild(li);
    });
  }

  async function refreshNotes() {
    if (!selectedOutpostId) return;
    var res = await fetch(
      "/api/corkboard/outposts/" + encodeURIComponent(selectedOutpostId) + "/notes",
      { credentials: "same-origin" }
    );
    if (!res.ok) return;
    var data = await res.json();
    var notes = data.notes || [];
    notesEl.innerHTML = "";
    notesEmptyEl.hidden = notes.length > 0;
    notes.forEach(function (n) {
      var li = document.createElement("li");
      li.innerHTML =
        '<div class="note-body">' + esc(n.body) + '</div>' +
        '<div class="muted note-sig">' + esc(n.signature || "anonymous") + '</div>';
      notesEl.appendChild(li);
    });
  }

  postForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (!selectedOutpostId) return;
    var body = postBody.value.trim();
    if (!body) return;
    var res = await fetch(
      "/api/corkboard/outposts/" + encodeURIComponent(selectedOutpostId) + "/notes",
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body: body, signature: postSignature.value.trim() || null }),
      }
    );
    if (res.ok) {
      postBody.value = "";
      postSignature.value = "";
      await refreshNotes();
    }
  });

  refreshOutposts();
  setInterval(refreshOutposts, 10000);
})();
