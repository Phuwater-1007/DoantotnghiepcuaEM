(function () {
  // ========== HAMBURGER MENU ==========
  var hamburger = document.getElementById("hamburger-btn");
  var sidebar = document.getElementById("sidebar");
  var overlay = document.getElementById("sidebar-overlay");

  function toggleSidebar() {
    sidebar.classList.toggle("is-open");
    overlay.classList.toggle("is-visible");
    hamburger.classList.toggle("is-active");
  }

  if (hamburger) {
    hamburger.addEventListener("click", toggleSidebar);
  }
  if (overlay) {
    overlay.addEventListener("click", toggleSidebar);
  }

  // Close sidebar when clicking a nav link on mobile
  var navLinks = document.querySelectorAll(".nav-links a");
  navLinks.forEach(function (link) {
    link.addEventListener("click", function () {
      if (window.innerWidth <= 1100 && sidebar.classList.contains("is-open")) {
        toggleSidebar();
      }
    });
  });

  // ========== DARK MODE TOGGLE ==========
  var themeToggle = document.getElementById("theme-toggle");
  var html = document.documentElement;

  function setTheme(theme) {
    html.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }

  // Load saved theme
  var savedTheme = localStorage.getItem("theme") || "light";
  setTheme(savedTheme);

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var current = html.getAttribute("data-theme");
      setTheme(current === "dark" ? "light" : "dark");
    });
  }

  // ========== TOAST NOTIFICATION SYSTEM ==========
  window.showToast = function (message, type, duration) {
    type = type || "info"; // info, success, error, warning
    duration = duration || 3500;
    var container = document.getElementById("toast-container");
    if (!container) return;

    var toast = document.createElement("div");
    toast.className = "toast toast-" + type;

    var icons = {
      success: "✓",
      error: "✕",
      warning: "⚠",
      info: "ℹ"
    };

    toast.innerHTML =
      '<span class="toast-icon">' + (icons[type] || "ℹ") + "</span>" +
      '<span class="toast-message">' + message + "</span>" +
      '<button class="toast-close" onclick="this.parentElement.remove()">×</button>';

    container.appendChild(toast);

    // Trigger animation
    requestAnimationFrame(function () {
      toast.classList.add("toast-show");
    });

    setTimeout(function () {
      toast.classList.remove("toast-show");
      toast.classList.add("toast-hide");
      setTimeout(function () { toast.remove(); }, 300);
    }, duration);
  };

  // Override native alert with toast
  var _originalAlert = window.alert;
  window.alert = function (msg) {
    if (typeof window.showToast === "function") {
      // Detect type from message content
      var type = "info";
      if (msg && (msg.indexOf("lỗi") !== -1 || msg.indexOf("Lỗi") !== -1 || msg.indexOf("thất bại") !== -1 || msg.indexOf("Không") !== -1)) {
        type = "error";
      } else if (msg && (msg.indexOf("thành công") !== -1 || msg.indexOf("Tải xong") !== -1)) {
        type = "success";
      } else if (msg && (msg.indexOf("chắc chắn") !== -1 || msg.indexOf("chưa") !== -1 || msg.indexOf("Chưa") !== -1)) {
        type = "warning";
      }
      window.showToast(msg, type);
    } else {
      _originalAlert(msg);
    }
  };

  // ========== HEARTBEAT & LIVE DOT ==========
  function post(url) {
    return fetch(url, { method: "POST", credentials: "same-origin" }).catch(function () {});
  }

  function heartbeat() {
    post("/api/client/heartbeat");
  }

  heartbeat();
  setInterval(heartbeat, 1000);

  window.addEventListener("pagehide", function () {
    var url = "/api/client/disconnect";
    try {
      if (navigator.sendBeacon) {
        navigator.sendBeacon(url);
      }
    } catch (e) {}
    post(url);
  });

  // Live dot indicator trong sidebar — dùng WebSocket thay vì poll
  var _appStatusWS = null;
  var _appStatusReconnectTimer = null;

  function connectAppStatusWS() {
    if (_appStatusWS && (_appStatusWS.readyState === WebSocket.OPEN || _appStatusWS.readyState === WebSocket.CONNECTING)) {
      return;
    }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/ws/app-status");
    _appStatusWS = ws;

    ws.onmessage = function (event) {
      try {
        var data = JSON.parse(event.data);
        var dot = document.getElementById("nav-live-dot");
        if (dot) {
          var isActive = data.active_session_id || data.has_active_stream;
          dot.style.display = isActive ? "inline-block" : "none";
        }
      } catch (e) {}
    };

    ws.onclose = function () {
      _appStatusReconnectTimer = setTimeout(connectAppStatusWS, 3000);
    };

    ws.onerror = function () { ws.close(); };
  }

  // Initial check then keep alive via WebSocket
  fetch("/api/monitoring/status", { credentials: "same-origin" })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var dot = document.getElementById("nav-live-dot");
      if (dot) dot.style.display = data.active_session_id ? "inline-block" : "none";
    })
    .catch(function () {})
    .finally(function () { connectAppStatusWS(); });
})();
