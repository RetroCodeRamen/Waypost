(function () {
  var createForm = document.getElementById("create-form");
  var nameEl = document.getElementById("group-name");
  var listEl = document.getElementById("group-list");
  var listEmptyEl = document.getElementById("group-list-empty");
  var detailPanel = document.getElementById("detail-panel");
  var detailNameEl = document.getElementById("detail-name");
  var memberListEl = document.getElementById("member-list");
  var addForm = document.getElementById("add-member-form");
  var addUsernameEl = document.getElementById("add-username");
  var addRoleEl = document.getElementById("add-role");
  var notAdminHintEl = document.getElementById("not-admin-hint");

  var myUsername = "";
  var selectedGroupId = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function refreshGroups() {
    return WaypostAuth.api("/api/groups")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var groups = data.groups || [];
        listEmptyEl.hidden = groups.length > 0;
        listEl.innerHTML = groups
          .map(function (g) {
            var cls = g.id === selectedGroupId ? " class=\"is-selected\"" : "";
            return (
              "<li" + cls + '><button type="button" data-id="' + esc(g.id) + '">' +
              esc(g.name) + '<span class="muted"> · ' + g.members.length + " member(s)</span>" +
              "</button></li>"
            );
          })
          .join("");
        listEl.querySelectorAll("button[data-id]").forEach(function (btn) {
          btn.addEventListener("click", function () {
            selectGroup(btn.getAttribute("data-id"));
          });
        });
      });
  }

  function selectGroup(groupId) {
    selectedGroupId = groupId;
    WaypostAuth.api("/api/groups/" + encodeURIComponent(groupId))
      .then(function (r) {
        return r.json();
      })
      .then(function (group) {
        detailPanel.hidden = false;
        detailNameEl.textContent = group.name;
        var isAdmin = group.members.some(function (m) {
          return m.username.toLowerCase() === myUsername.toLowerCase() && m.role === "admin";
        });
        addForm.hidden = !isAdmin;
        notAdminHintEl.hidden = isAdmin;
        memberListEl.innerHTML = group.members
          .map(function (m) {
            var removeBtn = isAdmin
              ? '<button type="button" class="secondary remove-member" data-username="' +
                esc(m.username) + '">Remove</button>'
              : "";
            return (
              "<li><div><strong>" + esc(m.username) + '</strong><span class="muted"> · ' +
              esc(m.role) + "</span></div>" + removeBtn + "</li>"
            );
          })
          .join("");
        memberListEl.querySelectorAll(".remove-member").forEach(function (btn) {
          btn.addEventListener("click", function () {
            btn.disabled = true;
            WaypostAuth.api("/api/groups/" + encodeURIComponent(groupId) + "/members/remove", {
              method: "POST",
              body: JSON.stringify({ username: btn.dataset.username }),
            })
              .then(function (r) {
                if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail); });
                return selectGroup(groupId);
              })
              .then(refreshGroups)
              .catch(function (err) {
                alert(err.message || "Could not remove member.");
                btn.disabled = false;
              });
          });
        });
      });
    refreshGroups();
  }

  createForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var name = nameEl.value.trim();
    if (!name) return;
    WaypostAuth.api("/api/groups", {
      method: "POST",
      body: JSON.stringify({ name: name }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail); });
        nameEl.value = "";
        return refreshGroups();
      })
      .catch(function (err) {
        alert(err.message || "Could not create group.");
      });
  });

  addForm.addEventListener("submit", function (ev) {
    ev.preventDefault();
    if (!selectedGroupId) return;
    var username = addUsernameEl.value.trim();
    if (!username) return;
    WaypostAuth.api("/api/groups/" + encodeURIComponent(selectedGroupId) + "/members", {
      method: "POST",
      body: JSON.stringify({ username: username, role: addRoleEl.value }),
    })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail); });
        addUsernameEl.value = "";
        return selectGroup(selectedGroupId);
      })
      .catch(function (err) {
        alert(err.message || "Could not add member.");
      });
  });

  WaypostAuth.requireAuth().then(function (user) {
    if (!user) return;
    myUsername = user.username;
    refreshGroups();
  });
})();
