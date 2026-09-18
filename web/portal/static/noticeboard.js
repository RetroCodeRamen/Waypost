(function () {
  var meEl = document.getElementById("me");
  var priorityEl = document.getElementById("priority");
  var listEl = document.getElementById("notice-list");
  var emptyEl = document.getElementById("empty");
  var detailEl = document.getElementById("detail");
  var dPriority = document.getElementById("d-priority");
  var dTitle = document.getElementById("d-title");
  var dMeta = document.getElementById("d-meta");
  var dBody = document.getElementById("d-body");
  var expireBtn = document.getElementById("expire-btn");
  var statusLine = document.getElementById("status-line");
  var dialog = document.getElementById("compose");
  var composeBtn = document.getElementById("compose-btn");
  var composeForm = document.getElementById("compose-form");
  var cTitle = document.getElementById("c-title");
  var cBody = document.getElementById("c-body");
  var refreshBtn = document.getElementById("refresh");

  var selectedId = null;
  var notices = [];

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function relativeTime(ts) {
    if (!ts) return "";
    var sec = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
    if (sec < 60) return sec + "s ago";
    var min = Math.floor(sec / 60);
    if (min < 60) return min + "m ago";
    var hr = Math.floor(min / 60);
    if (hr < 48) return hr + "h ago";
    return Math.floor(hr / 24) + "d ago";
  }

  function renderList() {
    if (!notices.length) {
      listEl.innerHTML =
        '<li class="muted" style="padding:0.5rem">No active notices.</li>';
      return;
    }
    listEl.innerHTML = notices
      .map(function (n) {
        var cls = selectedId === n.id ? "active" : "";
        if (n.priority === "high") cls += (cls ? " " : "") + "priority-high";
        return (
          '<li><button type="button" class="' +
          cls +
          '" data-id="' +
          esc(n.id) +
          '">' +
          '<span class="from">' +
          esc(n.priority.toUpperCase()) +
          " · " +
          esc(n.author) +
          "</span>" +
          '<span class="subj">' +
          esc(n.title) +
          "</span></button></li>"
        );
      })
      .join("");
    listEl.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openNotice(btn.getAttribute("data-id"));
      });
    });
  }

  function openNotice(id) {
    selectedId = id;
    var n = notices.find(function (x) {
      return x.id === id;
    });
    if (!n) {
      emptyEl.hidden = false;
      detailEl.hidden = true;
      return;
    }
    emptyEl.hidden = true;
    detailEl.hidden = false;
    dPriority.textContent = n.priority.toUpperCase();
    dPriority.className = "notice-badge priority-" + n.priority;
    dTitle.textContent = n.title;
    dMeta.textContent =
      "By " + n.author + " · " + relativeTime(n.created_at) + (n.active ? "" : " · expired");
    dBody.textContent = n.body;
    expireBtn.hidden = !n.active;
    renderList();
  }

  function refresh() {
    return fetch("/api/noticeboard/notices?active_only=true&limit=50")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        notices = data.notices || [];
        statusLine.textContent =
          (data.active_count || 0) +
          " active · structured bulletins (not Commons posts)";
        renderList();
        if (selectedId) openNotice(selectedId);
        else if (notices.length) openNotice(notices[0].id);
        else {
          emptyEl.hidden = false;
          detailEl.hidden = true;
        }
      })
      .catch(function () {
        statusLine.textContent = "Could not load Noticeboard.";
      });
  }

  composeBtn.addEventListener("click", function () {
    cTitle.value = "";
    cBody.value = "";
    dialog.showModal();
  });

  composeForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var submitter = ev.submitter;
    var value = submitter ? submitter.value : "cancel";
    if (value === "cancel") {
      dialog.close();
      return;
    }
    var author = meEl.value.trim();
    var title = cTitle.value.trim();
    var body = cBody.value.trim();
    if (!author || !title || !body) return;
    fetch("/api/noticeboard/notices", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        author: author,
        title: title,
        body: body,
        priority: priorityEl.value,
      }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        return r.json();
      })
      .then(function (n) {
        dialog.close();
        selectedId = n.id;
        return refresh();
      })
      .catch(function () {
        alert("Could not post notice.");
      });
  });

  expireBtn.addEventListener("click", function () {
    if (!selectedId) return;
    fetch("/api/noticeboard/notices/" + encodeURIComponent(selectedId) + "/expire", {
      method: "POST",
    })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        selectedId = null;
        return refresh();
      })
      .catch(function () {
        alert("Could not expire notice.");
      });
  });

  refreshBtn.addEventListener("click", refresh);
  refresh();
})();
