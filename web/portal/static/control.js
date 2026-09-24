(function () {
  var notAdminPanel = document.getElementById("not-admin-panel");
  var adminPanel = document.getElementById("admin-panel");
  var pendingEl = document.getElementById("pending");
  var pendingEmptyEl = document.getElementById("pending-empty");

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function refreshPending() {
    WaypostAuth.api("/api/auth/pending")
      .then(function (r) {
        if (!r.ok) return { users: [] };
        return r.json();
      })
      .then(function (data) {
        var users = data.users || [];
        pendingEl.innerHTML = "";
        pendingEmptyEl.hidden = users.length > 0;
        users.forEach(function (u) {
          var li = document.createElement("li");
          li.innerHTML =
            '<div><div class="node-id">' + esc(u.display_name || u.username) +
            '</div><div class="muted">@' + esc(u.username) + "</div></div>" +
            '<button type="button" class="approve" data-username="' + esc(u.username) + '">Approve</button>';
          pendingEl.appendChild(li);
        });
        pendingEl.querySelectorAll("button.approve").forEach(function (btn) {
          btn.addEventListener("click", function () {
            btn.disabled = true;
            WaypostAuth.api("/api/auth/approve", {
              method: "POST",
              body: JSON.stringify({ username: btn.dataset.username }),
            }).finally(refreshPending);
          });
        });
      });
  }

  WaypostAuth.requireAuth().then(function (user) {
    if (!user) return;
    if (!user.is_admin) {
      notAdminPanel.hidden = false;
      return;
    }
    adminPanel.hidden = false;
    refreshPending();
    setInterval(refreshPending, 15000);
  });
})();
