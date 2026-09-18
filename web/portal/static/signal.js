(function () {
  var stationEl = document.getElementById("station");
  var waylinkEl = document.getElementById("waylink");
  var syncEl = document.getElementById("sync");
  var networkEl = document.getElementById("network");
  var servicesEl = document.getElementById("services");
  var routeEl = document.getElementById("route");
  var destEl = document.getElementById("dest");

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function dl(obj, keys) {
    return keys
      .map(function (k) {
        var label = k[0];
        var key = k[1];
        var val = obj && obj[key];
        if (val === true) val = "yes";
        if (val === false) val = "no";
        if (val == null || val === "") val = "—";
        return "<dt>" + esc(label) + "</dt><dd>" + esc(val) + "</dd>";
      })
      .join("");
  }

  function refresh() {
    return fetch("/api/signal")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        stationEl.innerHTML = dl(data.station || {}, [
          ["Name", "name"],
          ["Env", "env"],
          ["SSID", "ssid"],
          ["Domain", "domain"],
          ["Registration", "registration_mode"],
        ]);
        waylinkEl.innerHTML = dl(data.waylink || {}, [
          ["Transport", "transport"],
          ["Device", "device"],
          ["Gateway", "gateway_running"],
          ["Handlers", "handlers"],
          ["Radios found", "radios_detected"],
          ["Note", "note"],
        ]);
        var radios = (data.waylink && data.waylink.radios) || [];
        var radioBox = document.getElementById("radios");
        if (radioBox) {
          if (!radios.length) {
            radioBox.innerHTML =
              '<li class="muted">No USB serial radios detected. Plug in Heltec boards.</li>';
          } else {
            radioBox.innerHTML = radios
              .map(function (r) {
                return (
                  "<li><strong>" +
                  esc(r.path) +
                  "</strong><small>" +
                  esc(r.kind) +
                  " · " +
                  esc(r.vid || "?") +
                  ":" +
                  esc(r.pid || "?") +
                  " · " +
                  (r.accessible ? "rw" : "no access") +
                  "</small></li>"
                );
              })
              .join("");
          }
        }
        var sync = data.sync || {};
        if (syncEl) {
          var pendingUsers = sync.pending_by_user || {};
          var pendingDetail = Object.keys(pendingUsers)
            .map(function (u) {
              return u + "=" + pendingUsers[u];
            })
            .join(", ");
          syncEl.innerHTML = dl(
            {
              pending: sync.pending_dispatch || 0,
              outbox: sync.outbox_depth || 0,
              waiting: (sync.waiting_nodes || []).join(", ") || "none",
              by_user: pendingDetail || "none",
            },
            [
              ["Dispatch waiting", "pending"],
              ["Outbox depth", "outbox"],
              ["Waiting nodes", "waiting"],
              ["By user", "by_user"],
            ]
          );
        }
        var net = data.network || {};
        networkEl.innerHTML = dl(
          {
            users:
              (net.users_online || 0) + " online / " + (net.users_total || 0) + " total",
            outposts:
              (net.outposts_online || 0) +
              " online / " +
              (net.outposts_total || 0) +
              " total",
            nodes: (net.bound_nodes || [])
              .map(function (n) {
                return n.node_id + " → " + n.username;
              })
              .join(", ") || "none",
            beacon: data.beacon_active ? "ACTIVE" : "clear",
          },
          [
            ["Users", "users"],
            ["Outposts", "outposts"],
            ["Bound nodes", "nodes"],
            ["Beacon", "beacon"],
          ]
        );
        var svc = data.services || {};
        servicesEl.innerHTML = Object.keys(svc)
          .map(function (k) {
            var ok = svc[k];
            return (
              "<li><span class=\"dot " +
              (ok ? "ok" : "bad") +
              "\"></span>" +
              esc(k) +
              "</li>"
            );
          })
          .join("");
      })
      .catch(function () {
        stationEl.innerHTML = "<dt>Error</dt><dd>Could not load Signal</dd>";
      });
  }

  document.getElementById("probe").addEventListener("click", function () {
    var dest = destEl.value.trim();
    if (!dest) return;
    fetch("/api/signal/route?destination=" + encodeURIComponent(dest))
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        routeEl.classList.remove("muted");
        routeEl.textContent = JSON.stringify(data, null, 2);
      })
      .catch(function () {
        routeEl.textContent = "Probe failed.";
      });
  });

  document.getElementById("airtest").addEventListener("click", function () {
    routeEl.classList.remove("muted");
    routeEl.textContent = "Running Heltec air test (/dev/ttyUSB0 → /dev/ttyUSB1)…";
    fetch("/api/signal/airtest", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        routeEl.textContent = JSON.stringify(data, null, 2);
      })
      .catch(function () {
        routeEl.textContent = "Air test failed.";
      });
  });

  document.getElementById("refresh").addEventListener("click", refresh);
  refresh();
})();
