(function () {
  var USER = "AJ";

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

  function initials(name) {
    var p = String(name || "?").trim().split(/[\s@]+/);
    if (p.length === 1) return p[0].slice(0, 2).toUpperCase();
    return (p[0][0] + p[1][0]).toUpperCase();
  }

  WaypostShell.mount({
    active: "home",
    user: USER,
    subtitle: "The network is alive. Here's what's new.",
  });

  var gate = document.getElementById("gate-note");
  if (gate) {
    gate.textContent =
      "Joined via Waygate? Bookmark " + window.location.origin + "/ for next time.";
  }

  function paintDashboard(data) {
    if (data.user && data.user.display_name) {
      var title = document.querySelector(".wp-greeting__title");
      if (title) {
        title.textContent = WaypostShell.greeting(data.user.display_name);
      }
      var chip = document.querySelector(".wp-userchip__name");
      if (chip) chip.textContent = data.user.display_name + " ▾";
      var av = document.querySelector(".wp-avatar");
      if (av) av.textContent = initials(data.user.display_name);
    }

    var cards = data.cards || {};
    Object.keys(cards).forEach(function (key) {
      var el = document.querySelector('[data-card="' + key + '"] .stat-card__value');
      if (el) el.textContent = String(cards[key].value);
    });

    var banner = document.getElementById("beacon-banner");
    if (banner) {
      if (data.active_beacon) {
        banner.hidden = false;
        document.getElementById("beacon-banner-title").textContent =
          "BEACON · " + (data.active_beacon.title || "Alert");
        document.getElementById("beacon-banner-meta").textContent =
          " " +
          (data.active_beacon.severity || "").toUpperCase() +
          " · " +
          (data.active_beacon.author || "");
      } else {
        banner.hidden = true;
      }
    }

    var list = document.getElementById("activity-list");
    var activity = data.activity || [];
    if (!activity.length) {
      list.innerHTML =
        '<li class="activity-empty muted">No recent activity yet. Try Dispatch, Postbox, or Commons.</li>';
    } else {
      list.innerHTML = activity
        .map(function (a) {
          return (
            "<li>" +
            '<div class="activity-avatar accent-' +
            esc(a.accent || "dispatch") +
            '">' +
            esc(initials(a.actor)) +
            "</div>" +
            "<div>" +
            '<div class="activity-actor">' +
            esc(a.actor) +
            "</div>" +
            '<div class="activity-text">' +
            esc(a.text) +
            "</div>" +
            '<div class="activity-service accent-' +
            esc(a.accent || "dispatch") +
            '">' +
            esc(a.service) +
            "</div>" +
            "</div>" +
            '<div class="activity-time">' +
            esc(relativeTime(a.ts)) +
            "</div>" +
            "</li>"
          );
        })
        .join("");
    }

    var net = data.network || {};
    var sync = data.sync || {};
    var pending = sync.pending_dispatch || 0;
    var netEl = document.getElementById("network-status");
    netEl.innerHTML =
      '<li><span class="dot ok"></span><div><strong>Waypost Station</strong><small>' +
      esc(net.station || "Online") +
      " · " +
      esc(net.ssid || "WAYPOST") +
      "</small></div></li>" +
      '<li><span class="dot ' +
      (pending ? "bad" : "ok") +
      '"></span><div><strong>Sync</strong><small>' +
      (pending
        ? pending + " Dispatch message(s) waiting"
        : "Nothing waiting") +
      "</small></div></li>" +
      '<li><span class="dot ok"></span><div><strong>Outposts</strong><small>' +
      esc(net.outposts_online) +
      " online / " +
      esc(net.outposts_total) +
      " total</small></div></li>" +
      '<li><span class="dot ok"></span><div><strong>Connected Users</strong><small>' +
      esc(net.users_online) +
      " online</small></div></li>" +
      '<li><span class="dot ok"></span><div><strong>Waylink</strong><small>' +
      esc(net.transport || "mock") +
      " transport</small></div></li>";

    var ql = document.getElementById("quick-links");
    ql.innerHTML = (data.quick_links || [])
      .map(function (l) {
        return (
          '<a class="quick-link" href="' +
          esc(l.href) +
          '">' +
          esc(l.label) +
          "</a>"
        );
      })
      .join("");
  }

  function loadDashboard() {
    return fetch("/api/dashboard", { credentials: "same-origin" }).then(function (r) {
      if (r.status === 401) {
        location.href = "/login.html?next=" + encodeURIComponent("/");
        return null;
      }
      return r.json();
    });
  }

  loadDashboard()
    .then(function (data) {
      if (data) paintDashboard(data);
    })
    .catch(function () {
      var list = document.getElementById("activity-list");
      if (list) {
        list.innerHTML =
          '<li class="activity-empty muted">Could not load dashboard data.</li>';
      }
    });
})();
