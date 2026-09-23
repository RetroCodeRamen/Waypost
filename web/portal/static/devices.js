(function () {
  var makeBtn = document.getElementById("make-code");
  var codeDisplay = document.getElementById("code-display");
  var codeValue = document.getElementById("code-value");
  var codeExpiry = document.getElementById("code-expiry");
  var listEl = document.getElementById("devices");
  var emptyEl = document.getElementById("devices-empty");
  var countdownTimer = null;
  var myUsername = "aj";

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatCountdown(expiresAt) {
    var secs = Math.max(0, Math.round(expiresAt - Date.now() / 1000));
    var m = Math.floor(secs / 60);
    var s = secs % 60;
    return "expires in " + m + ":" + (s < 10 ? "0" : "") + s;
  }

  function formatDest(d) {
    if (!d.transport_dest) return "no radio contact yet";
    return "Reticulum " + esc(d.transport_dest.slice(0, 12)) + "…";
  }

  async function refreshDevices() {
    var res = await fetch("/api/dispatch/devices", { credentials: "same-origin" });
    if (!res.ok) return;
    var data = await res.json();
    var devices = data.devices || [];
    listEl.innerHTML = "";
    emptyEl.hidden = devices.length > 0;
    devices.forEach(function (d) {
      var li = document.createElement("li");
      li.innerHTML =
        '<div><div class="node-id">' + esc(d.node_id) + '</div>' +
        '<div class="muted">' + formatDest(d) + '</div></div>' +
        '<button type="button" class="revoke" data-node-id="' + esc(d.node_id) + '">Revoke</button>';
      listEl.appendChild(li);
    });
    listEl.querySelectorAll("button.revoke").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        btn.disabled = true;
        await fetch("/api/dispatch/devices/unbind-one", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ node_id: btn.dataset.nodeId, username: myUsername }),
        });
        refreshDevices();
      });
    });
  }

  makeBtn.addEventListener("click", async function () {
    makeBtn.disabled = true;
    var res = await fetch("/api/auth/pairing/create", {
      method: "POST",
      credentials: "same-origin",
    });
    makeBtn.disabled = false;
    if (!res.ok) return;
    var body = await res.json();
    codeValue.textContent = body.code;
    codeDisplay.hidden = false;
    if (countdownTimer) clearInterval(countdownTimer);
    function tick() {
      var left = body.expires_at - Date.now() / 1000;
      if (left <= 0) {
        codeExpiry.textContent = "expired — generate a new one";
        clearInterval(countdownTimer);
        return;
      }
      codeExpiry.textContent = formatCountdown(body.expires_at);
    }
    tick();
    countdownTimer = setInterval(tick, 1000);
  });

  WaypostAuth.me().then(function (u) {
    if (u && u.username) myUsername = u.username;
  });

  refreshDevices();
})();
