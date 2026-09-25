(function () {
  var myUsername = "";
  var statusEl = document.getElementById("status");
  var listEl = document.getElementById("people");

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatReach(p) {
    if (p.reachability === "wifi+lora") return "Wi‑Fi + LoRa";
    if (p.reachability === "wifi") return "Wi‑Fi";
    if (p.reachability === "lora") return "LoRa";
    if (p.reachability === "recent") {
      if (!p.last_seen) return "Recently seen";
      var mins = Math.round((Date.now() / 1000 - p.last_seen) / 60);
      return "Last seen " + mins + "m";
    }
    return "Unavailable";
  }

  async function refresh() {
    if (myUsername) {
      await fetch("/api/rollcall/touch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: myUsername, via: "wifi" }),
      });
    }
    var data = await fetch("/api/rollcall").then(function (r) { return r.json(); });
    listEl.innerHTML = "";
    (data.people || []).forEach(function (p) {
      var li = document.createElement("li");
      li.innerHTML =
        '<div><div class="name">' +
        esc(p.display_name || p.username) +
        '</div><div class="status">' +
        esc(p.status || "—") +
        '</div></div>' +
        '<div class="reach">' +
        esc(formatReach(p)) +
        "</div>" +
        '<div class="actions">' +
        '<a href="/dispatch.html">Dispatch</a>' +
        '<a href="/postbox.html">Postbox</a>' +
        '<a href="/~' +
        encodeURIComponent(p.username) +
        '">Profile</a>' +
        "</div>";
      listEl.appendChild(li);
    });
  }

  document.getElementById("set-status").addEventListener("click", async function () {
    if (!myUsername) return;
    await fetch("/api/rollcall/status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: myUsername, status: statusEl.value }),
    });
    refresh();
  });

  WaypostAuth.requireAuth().then(function (user) {
    if (!user) return;
    myUsername = user.username;
    refresh();
    setInterval(refresh, 5000);
  });
})();
