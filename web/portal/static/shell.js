/** Waypost application shell — sidebar, header, responsive drawer. */
(function (global) {
  var NAV_PRIMARY = [
    { id: "home", label: "Home", href: "/", icon: "home" },
    { id: "dispatch", label: "Dispatch", href: "/dispatch.html", icon: "dispatch" },
    { id: "postbox", label: "Postbox", href: "/postbox.html", icon: "postbox" },
    { id: "commons", label: "Commons", href: "/commons.html", icon: "commons" },
    { id: "fieldbook", label: "Fieldbook", href: "#", icon: "fieldbook", soon: true },
    { id: "noticeboard", label: "Noticeboard", href: "/noticeboard.html", icon: "notice" },
    { id: "beacon", label: "Beacon", href: "/beacon.html", icon: "beacon" },
    { id: "corkboard", label: "Corkboard", href: "/corkboard.html", icon: "corkboard" },
    { id: "locker", label: "Locker", href: "/locker.html", icon: "locker" },
    { id: "archive", label: "Archive", href: "#", icon: "archive", soon: true },
    { id: "atlas", label: "Atlas", href: "#", icon: "atlas", soon: true },
    { id: "rollcall", label: "Rollcall", href: "/rollcall.html", icon: "rollcall" },
    { id: "finder", label: "Finder", href: "#", icon: "finder", soon: true },
  ];

  var NAV_SYSTEM = [
    { id: "signal", label: "Signal", href: "/signal.html", icon: "signal" },
    { id: "devices", label: "Devices", href: "/devices.html", icon: "devices" },
    { id: "groups", label: "Groups", href: "/groups.html", icon: "groups" },
    { id: "control", label: "Control", href: "/control.html", icon: "control" },
  ];

  function iconSvg(name) {
    var paths = {
      home: '<path d="M4 12 L12 4 L20 12"/><path d="M7 11 V19 H17 V11"/>',
      dispatch: '<path d="M5 8 H15"/><path d="M5 12 H19"/><path d="M5 16 H12"/>',
      postbox: '<rect x="4" y="7" width="16" height="11" rx="1.5"/><path d="M4 9 L12 14 L20 9"/>',
      commons: '<circle cx="9" cy="10" r="2.5"/><circle cx="15" cy="10" r="2.5"/><path d="M5 18 C5 15 8 14 9 14 C11 14 12 15 12 15 C12 15 13 14 15 14 C16 14 19 15 19 18"/>',
      fieldbook: '<path d="M6 5 H16 A2 2 0 0 1 18 7 V19 H8 A2 2 0 0 0 6 21 Z"/><path d="M6 5 V19"/>',
      notice: '<rect x="6" y="4" width="12" height="16" rx="1"/><path d="M9 9 H15 M9 13 H15"/>',
      beacon: '<path d="M12 4 V10"/><path d="M8 14 L12 10 L16 14"/><circle cx="12" cy="18" r="2"/>',
      corkboard: '<rect x="4" y="5" width="16" height="14" rx="1.5"/><path d="M8 10 H13 M8 14 H11"/><circle cx="16" cy="9" r="1"/><circle cx="8" cy="17" r="1"/>',
      locker: '<rect x="5" y="7" width="14" height="12" rx="1.5"/><path d="M12 7 V4 M10 13 H14"/>',
      archive: '<path d="M5 8 H19 V19 H5 Z"/><path d="M5 8 L7 5 H17 L19 8"/><path d="M9 12 H15"/>',
      atlas: '<circle cx="12" cy="12" r="7"/><path d="M5 12 H19 M12 5 C14 8 14 16 12 19 C10 16 10 8 12 5"/>',
      rollcall: '<circle cx="12" cy="8" r="3"/><path d="M6 19 C6 15.5 9 14 12 14 C15 14 18 15.5 18 19"/>',
      finder: '<circle cx="11" cy="11" r="5.5"/><path d="M15.5 15.5 L19 19"/>',
      signal: '<path d="M5 16 V19"/><path d="M9 13 V19"/><path d="M13 9 V19"/><path d="M17 5 V19"/>',
      devices: '<circle cx="8" cy="12" r="3.5"/><path d="M11.2 12 H20 M15.5 12 V15.5 M18.5 12 V14.5"/>',
      groups: '<circle cx="9" cy="9" r="2.5"/><circle cx="16" cy="10" r="2"/><path d="M4.5 19 C4.5 15.5 7 14 9 14 C11 14 13.5 15.5 13.5 19"/><path d="M14.5 15 C16.5 15 19.5 16.2 19.5 19"/>',
      control: '<circle cx="12" cy="12" r="3"/><path d="M12 4 V7 M12 17 V20 M4 12 H7 M17 12 H20 M6.5 6.5 L8.5 8.5 M15.5 15.5 L17.5 17.5 M17.5 6.5 L15.5 8.5 M8.5 15.5 L6.5 17.5"/>',
    };
    var d = paths[name] || paths.home;
    return (
      '<svg class="wp-nav__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      d +
      "</svg>"
    );
  }

  function greeting(name) {
    var h = new Date().getHours();
    var part = "Hello";
    if (h < 12) part = "Good morning";
    else if (h < 18) part = "Good afternoon";
    else part = "Good evening";
    return part + ", " + name;
  }

  function initials(name) {
    var parts = String(name || "U").trim().split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }

  function navItem(item, active) {
    var cls = "wp-nav__link";
    if (item.id === active) cls += " is-active";
    if (item.soon) cls += " is-soon";
    var tag = item.soon ? "span" : "a";
    var href = item.soon ? "" : ' href="' + item.href + '"';
    return (
      "<" +
      tag +
      ' class="' +
      cls +
      '"' +
      href +
      ">" +
      iconSvg(item.icon) +
      "<span>" +
      item.label +
      "</span></" +
      tag +
      ">"
    );
  }

  function buildShell(opts) {
    var active = opts.active || "home";
    var user = opts.user || "AJ";
    var subtitle =
      opts.subtitle || "The network is alive. Here's what's new.";
    var pageTitle = opts.title || null;

    var primary = NAV_PRIMARY.map(function (i) {
      return navItem(i, active);
    }).join("");
    var system = NAV_SYSTEM.map(function (i) {
      return navItem(i, active);
    }).join("");

    return (
      '<div class="wp-backdrop" data-wp-close-nav></div>' +
      '<aside class="wp-sidebar" aria-label="Waypost navigation">' +
      '<a class="wp-brand" href="/" aria-label="Waypost Home">' +
      '<img class="wp-brand__mark" src="/static/brand/waypost-mark-64.png" width="34" height="34" alt=""/>' +
      '<span class="wp-brand__name">Waypost</span>' +
      "</a>" +
      '<nav class="wp-nav">' +
      '<div class="wp-nav__label">Apps</div>' +
      primary +
      '<div class="wp-nav__sep"></div>' +
      system +
      "</nav>" +
      '<div class="wp-sidebar__foot">Waypost Station</div>' +
      "</aside>" +
      '<div class="wp-main">' +
      '<header class="wp-topbar">' +
      '<div class="wp-greeting">' +
      '<button type="button" class="wp-menu-btn" data-wp-toggle-nav aria-label="Open menu">' +
      '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M4 12h16M4 17h16"/></svg>' +
      "</button>" +
      "<div>" +
      '<p class="wp-greeting__title">' +
      (pageTitle || greeting(user)) +
      "</p>" +
      '<p class="wp-greeting__sub">' +
      subtitle +
      "</p>" +
      "</div></div>" +
      '<div class="wp-topbar__right">' +
      '<label class="wp-search">' +
      '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="6"/><path d="M16 16l4 4"/></svg>' +
      '<input type="search" placeholder="Search Waypost…" disabled title="Finder coming soon"/>' +
      "</label>" +
      '<div class="wp-userchip">' +
      '<span class="wp-avatar">' +
      initials(user) +
      "</span>" +
      '<span class="wp-userchip__name">' +
      user +
      " ▾</span>" +
      "</div></div></header>" +
      '<div class="wp-content" data-wp-slot></div>' +
      "</div>"
    );
  }

  function ensureFavicon() {
    if (document.querySelector('link[rel="icon"]')) return;
    var link = document.createElement("link");
    link.rel = "icon";
    link.type = "image/png";
    link.href = "/static/brand/waypost-mark-32.png";
    document.head.appendChild(link);
    var apple = document.createElement("link");
    apple.rel = "apple-touch-icon";
    apple.href = "/static/brand/waypost-mark-256.png";
    document.head.appendChild(apple);
  }

  function mount(opts) {
    opts = opts || {};
    ensureFavicon();

    function paint(user) {
      if (user) {
        opts.user = user.display_name || user.username || opts.user;
      }
      document.body.classList.add("wp-body");

      var existing = document.getElementById("wp-page");
      if (!existing) {
        console.warn("WaypostShell: #wp-page not found");
        return;
      }

      var shell = document.createElement("div");
      shell.className = "wp-shell";
      shell.innerHTML = buildShell(opts);

      var slot = shell.querySelector("[data-wp-slot]");
      while (existing.firstChild) {
        slot.appendChild(existing.firstChild);
      }
      existing.remove();

      document.body.insertBefore(shell, document.body.firstChild);

      document.querySelectorAll("[data-wp-toggle-nav]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          document.body.classList.toggle("wp-nav-open");
        });
      });
      document.querySelectorAll("[data-wp-close-nav]").forEach(function (el) {
        el.addEventListener("click", function () {
          document.body.classList.remove("wp-nav-open");
        });
      });
      var chip = document.querySelector(".wp-userchip");
      if (chip && global.WaypostAuth) {
        chip.style.cursor = "pointer";
        chip.title = "Sign out";
        chip.addEventListener("click", function () {
          WaypostAuth.logout();
        });
      }
    }

    function withAuth() {
      if (!global.WaypostAuth) {
        paint(null);
        return;
      }
      WaypostAuth.requireAuth().then(function (user) {
        if (user) paint(user);
      });
    }

    if (global.WaypostAuth) {
      withAuth();
    } else {
      var s = document.createElement("script");
      s.src = "/static/auth.js";
      s.onload = withAuth;
      s.onerror = function () {
        paint(null);
      };
      document.head.appendChild(s);
    }
  }

  global.WaypostShell = { mount: mount, greeting: greeting };
})(window);
