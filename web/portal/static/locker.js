(function () {
  var meEl = document.getElementById("me");
  var filterEl = document.getElementById("filter");
  var scopeEl = document.getElementById("scope");
  var noteEl = document.getElementById("note");
  var fileEl = document.getElementById("file");
  var listEl = document.getElementById("file-list");
  var statusEl = document.getElementById("status-line");
  var hintEl = document.getElementById("limit-hint");
  var form = document.getElementById("upload-form");

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

  function me() {
    return meEl.value.trim() || "aj";
  }

  function listUrl() {
    var viewer = encodeURIComponent(me());
    var mode = filterEl.value;
    if (mode === "shared") {
      return "/api/locker/files?scope=shared&viewer=" + viewer;
    }
    if (mode === "mine") {
      return (
        "/api/locker/files?scope=personal&owner=" +
        viewer +
        "&viewer=" +
        viewer
      );
    }
    return "/api/locker/files?viewer=" + viewer;
  }

  function render(files) {
    if (!files.length) {
      listEl.innerHTML =
        '<li class="muted">No files yet. Upload something to share with the community.</li>';
      return;
    }
    listEl.innerHTML = files
      .map(function (f) {
        var dl =
          f.download_path +
          (f.scope === "personal" ? "?viewer=" + encodeURIComponent(me()) : "");
        return (
          '<li class="locker-item">' +
          '<div class="locker-item__main">' +
          '<div class="locker-item__name">' +
          esc(f.filename) +
          "</div>" +
          '<div class="locker-item__meta">' +
          esc(f.scope) +
          " · " +
          esc(f.size_label || f.size) +
          " · by " +
          esc(f.owner) +
          " · " +
          esc(relativeTime(f.created_at)) +
          (f.note ? " · " + esc(f.note) : "") +
          "</div></div>" +
          '<div class="locker-item__actions">' +
          '<a class="locker-dl" href="' +
          esc(dl) +
          '" download="' +
          esc(f.filename) +
          '">Download</a>' +
          (f.owner.toLowerCase() === me().toLowerCase()
            ? '<button type="button" class="locker-del secondary" data-id="' +
              esc(f.id) +
              '">Delete</button>'
            : "") +
          "</div></li>"
        );
      })
      .join("");

    listEl.querySelectorAll(".locker-del").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-id");
        fetch("/api/locker/files/" + encodeURIComponent(id) + "/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ actor: me() }),
        })
          .then(function (r) {
            if (!r.ok) throw new Error("delete failed");
            return refresh();
          })
          .catch(function () {
            alert("Could not delete file.");
          });
      });
    });
  }

  function refresh() {
    return fetch(listUrl())
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var files = data.files || [];
        statusEl.textContent =
          files.length +
          " file(s) · " +
          (data.shared_count || 0) +
          " shared on Station";
        if (data.max_upload_bytes) {
          var mb = Math.round(data.max_upload_bytes / (1024 * 1024));
          hintEl.textContent =
            "Shared files are downloadable by anyone on the Station. Personal files are only yours. Max upload " +
            mb +
            " MB. Large files stay on Wi‑Fi — not over Waylink.";
        }
        render(files);
      })
      .catch(function () {
        statusEl.textContent = "Could not load Locker.";
        listEl.innerHTML = "";
      });
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (!fileEl.files || !fileEl.files[0]) return;
    var fd = new FormData();
    fd.append("file", fileEl.files[0]);
    fd.append("owner", me());
    fd.append("scope", scopeEl.value);
    fd.append("note", noteEl.value.trim());
    fetch("/api/locker/files", { method: "POST", body: fd })
      .then(function (r) {
        if (!r.ok) {
          return r.json().then(function (j) {
            throw new Error(j.detail || "upload failed");
          });
        }
        fileEl.value = "";
        noteEl.value = "";
        return refresh();
      })
      .catch(function (err) {
        alert(err.message || "Upload failed.");
      });
  });

  document.getElementById("refresh").addEventListener("click", refresh);
  filterEl.addEventListener("change", refresh);
  refresh();
})();
