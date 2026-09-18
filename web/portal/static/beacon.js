(function () {
  var meEl = document.getElementById("me");
  var severityEl = document.getElementById("severity");
  var panel = document.getElementById("active-panel");
  var aTitle = document.getElementById("a-title");
  var aMeta = document.getElementById("a-meta");
  var aBody = document.getElementById("a-body");
  var historyEl = document.getElementById("history");
  var dialog = document.getElementById("compose");
  var composeForm = document.getElementById("compose-form");
  var cTitle = document.getElementById("c-title");
  var cBody = document.getElementById("c-body");

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

  function renderActive(b) {
    if (!b) {
      panel.className = "wp-card app-panel beacon-active is-clear";
      aTitle.textContent = "No active Beacon";
      aMeta.textContent = "Network is clear.";
      aBody.hidden = true;
      aBody.textContent = "";
      return;
    }
    panel.className =
      "wp-card app-panel beacon-active severity-" + (b.severity || "emergency");
    aTitle.textContent = b.title;
    aMeta.textContent =
      (b.severity || "").toUpperCase() +
      " · by " +
      b.author +
      " · " +
      relativeTime(b.created_at);
    aBody.hidden = false;
    aBody.textContent = b.body;
  }

  function renderHistory(list) {
    if (!list.length) {
      historyEl.innerHTML = '<li class="muted">No Beacon history yet.</li>';
      return;
    }
    historyEl.innerHTML = list
      .map(function (b) {
        return (
          "<li>" +
          '<span class="badge">' +
          esc((b.severity || "").toUpperCase()) +
          (b.active ? " · ACTIVE" : "") +
          "</span>" +
          "<strong>" +
          esc(b.title) +
          "</strong>" +
          '<span class="meta">' +
          esc(b.author) +
          " · " +
          esc(relativeTime(b.created_at)) +
          "</span></li>"
        );
      })
      .join("");
  }

  function refresh() {
    return Promise.all([
      fetch("/api/beacon").then(function (r) {
        return r.json();
      }),
      fetch("/api/beacon/history?limit=20").then(function (r) {
        return r.json();
      }),
    ])
      .then(function (pair) {
        renderActive(pair[0].beacon);
        renderHistory(pair[1].beacons || []);
      })
      .catch(function () {
        aTitle.textContent = "Could not load Beacon";
      });
  }

  document.getElementById("push-btn").addEventListener("click", function () {
    cTitle.value = "";
    cBody.value = "";
    dialog.showModal();
  });

  composeForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var value = ev.submitter ? ev.submitter.value : "cancel";
    if (value === "cancel") {
      dialog.close();
      return;
    }
    fetch("/api/beacon", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        author: meEl.value.trim(),
        title: cTitle.value.trim(),
        body: cBody.value.trim(),
        severity: severityEl.value,
      }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) {
          throw new Error(j.detail || "failed");
        });
        dialog.close();
        return refresh();
      })
      .catch(function (err) {
        alert(err.message || "Could not push Beacon.");
      });
  });

  document.getElementById("clear-btn").addEventListener("click", function () {
    fetch("/api/beacon/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
      .then(function (r) {
        if (!r.ok) throw new Error("failed");
        return refresh();
      })
      .catch(function () {
        alert("Could not clear Beacon.");
      });
  });

  document.getElementById("refresh").addEventListener("click", refresh);
  refresh();
})();
