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

  // ========== COLLAPSIBLE SIDEBAR ==========
  var collapseBtn = document.getElementById("sidebar-collapse-btn");
  if (collapseBtn && sidebar) {
    // Load collapse state
    var isCollapsed = localStorage.getItem("sidebar-collapsed") === "true";
    if (isCollapsed) {
      sidebar.classList.add("collapsed");
    }
    
    collapseBtn.addEventListener("click", function (e) {
      e.preventDefault();
      sidebar.classList.toggle("collapsed");
      var nowCollapsed = sidebar.classList.contains("collapsed");
      localStorage.setItem("sidebar-collapsed", nowCollapsed);
    });
  }

  // ========== PROFILE MODAL ==========
  var profileTrigger = document.getElementById("profile-trigger");
  var profileModal = document.getElementById("profile-modal");
  var profileClose = document.getElementById("profile-modal-close");
  var profileOverlay = document.getElementById("profile-modal-overlay");

  function openProfileModal(e) {
    if (e) e.preventDefault();
    if (profileModal) {
      profileModal.classList.add("is-open");
    }
  }

  function closeProfileModal(e) {
    if (e) e.preventDefault();
    if (profileModal) {
      profileModal.classList.remove("is-open");
    }
  }

  if (profileTrigger) {
    profileTrigger.addEventListener("click", openProfileModal);
  }
  if (profileClose) {
    profileClose.addEventListener("click", closeProfileModal);
  }
  if (profileOverlay) {
    profileOverlay.addEventListener("click", closeProfileModal);
  }
  
  // Close modal on escape key press
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && profileModal && profileModal.classList.contains("is-open")) {
      closeProfileModal();
    }
  });

  // ========== CLIENT-SIDE TRANSLATION SYSTEM (i18n) v2.7 ==========
  window.translations = {
    vi: {
      "lang-switch-tooltip": "Switch to English",
      "btn-collapse": "Thu gọn",
      "btn-expand": "Mở rộng"
    },
    en: {
      "lang-switch-tooltip": "Chuyển sang Tiếng Việt",
      "btn-collapse": "Collapse Menu",
      "btn-expand": "Expand Menu",

      // Sidebar / Navigation Shell
      "Giám sát Giao thông": "Traffic Monitor",
      "Đồ án tốt nghiệp": "Graduation Project",
      "MODULE CHÍNH": "MAIN MODULES",
      "QUẢN TRỊ": "ADMINISTRATION",
      "Tổng quan": "Dashboard Overview",
      "Giám sát đơn luồng": "Single Stream",
      "Giám sát đa luồng": "Multi Stream Grid",
      "Tối ưu & Cảnh báo": "AI Optimization",
      "Báo cáo kỹ thuật": "Technical Reports",
      "Đơn vị sử dụng": "Deployment Units",
      "Người dùng": "User Accounts",
      "Quản trị hệ thống": "System Settings",
      "Hồ sơ cá nhân": "User Profile",
      "Đăng xuất": "Sign Out",

      // Profile Modal
      "Tên đăng nhập:": "Username:",
      "Vai trò hệ thống:": "System Role:",
      "Đơn vị quản lý:": "Management Unit:",
      "Quản trị viên": "Administrator",
      "Người dùng": "Standard User",

      // Dashboard
      "Bảng điều khiển": "Dashboard Overview",
      "Hệ thống giám sát giao thông thông minh": "Intelligent Traffic Monitoring System",
      "Toàn cảnh phân tích giao thông": "Traffic Analysis Overview",
      "Theo dõi số lượng xe hôm nay, cơ cấu phương tiện theo loại và kết quả phiên phân tích gần nhất.": "Monitor today's vehicle counts, vehicle class structure, and latest analysis session results.",
      "Hệ thống đang sẵn sàng": "System is ready",
      "Mở giám sát": "Open Monitor",
      "Tổng số xe hôm nay": "Today's Total Vehicles",
      "Ô tô hôm nay": "Today's Cars",
      "Xe máy hôm nay": "Today's Motorcycles",
      "Phiên hoàn thành hôm nay": "Today's Completed Sessions",
      "Tổng xe đã đếm (Toàn bộ lịch sử)": "Total Counted Vehicles (Full History)",
      "Persist qua restart": "Persist across restart",
      "Tổng tất cả": "Grand Total",
      "Ô tô": "Cars",
      "Xe máy": "Motorcycles",
      "Xe tải + Bus": "Trucks + Buses",
      "Cơ cấu phương tiện": "Vehicle Structure",
      "Tổng xe": "Total Vehicles",
      "Xe buýt": "Buses",
      "Xe tải": "Trucks",
      "Chưa có dữ liệu phân tích.": "No analysis data yet.",
      "Chạy phân tích từ trang Giám sát": "Run analysis from the Monitor page",
      "Hoạt động theo giờ": "Hourly Activity",
      "Khung giờ cao điểm hôm nay:": "Today's peak hour:",
      "Khung giờ cao điểm hôm nay: 08:00": "Today's peak hour: 08:00",
      "Chưa có dữ liệu theo giờ.": "No hourly data yet.",
      "Chạy phân tích để có biểu đồ": "Run analysis to generate chart",
      "Phiên phân tích gần nhất": "Recent Analysis Sessions",
      "Xem tất cả báo cáo": "View all reports",
      "Lịch sử xe đếm được": "Counted Vehicle History Log",
      "Tất cả": "All",
      "Đang tải dữ liệu...": "Loading data...",
      "Đang tải...": "Loading...",
      "Loại xe": "Vehicle Type",
      "Chiều": "Direction",
      "Độ tin cậy": "Confidence",
      "Nguồn": "Source",
      "Thời gian": "Time",
      "Tải thêm": "Load More",
      "phiên": "sessions",
      "xe": "vehicles",

      // Monitoring & Multi-monitoring
      "Luồng Camera": "Camera Streams",
      "Chọn một luồng để đưa lên khung chính, chỉnh ROI hoặc xem trực tiếp.": "Select a stream to show on the main frame, edit ROI or view live.",
      "Chưa có video nào trong thư mục input.": "No videos found in the input folder.",
      "Khung xem chính": "Main Frame",
      "Video gốc": "Original Video",
      "Đang kết nối luồng phân tích...": "Connecting to analysis stream...",
      "↗ Đi": "↗ Outbound",
      "↘ Về": "↙ Inbound",
      "Lưu lượng": "Traffic Flow",
      "Tải video lên để hiển thị tại đây.": "Upload video to display here.",
      "Chưa có video để thao tác.": "No video to operate.",
      "Chỉnh ROI": "Edit ROI",
      "Xem trực tiếp": "View Live",
      "Dừng trực tiếp": "Stop Live",
      "Biển số nhận diện": "License Plates",
      "Sơ đồ lưới:": "Grid Layout:",
      "Chạy tất cả đã gán": "Run all assigned",
      "Dừng tất cả": "Stop all",
      "Tổng hệ thống đang chạy:": "Total system running:",
      "phương tiện": "vehicles",
      "Gán Camera cho ô giám sát": "Assign Camera to Slot",
      "Chọn Camera": "Select Camera",
      "Đang kết nối camera...": "Connecting camera...",
      "Kích hoạt": "Activate",
      "Phân tích nhanh": "Quick Analysis",
      "Thời gian giám sát": "Monitoring Time",
      "Mức phục vụ (LOS)": "Level of Service (LOS)",
      "Tốc độ bị hạn chế": "Speed restricted",
      "Chiều chủ đạo": "Main Direction",
      "Mật độ giao thông": "Traffic Density",
      "Thưa thớt": "Sparse",
      "Bình thường": "Normal",
      "Đông đúc": "Congested",
      "Nguồn dữ liệu": "Data Source",
      "Tải video lên": "Upload Video",
      "Kéo thả hoặc bấm — mp4, avi, mov, mkv": "Drag & drop or click — mp4, avi, mov, mkv",
      "Kết nối Camera IP": "Connect IP Camera",
      "Nhập URL RTSP hoặc HTTP stream": "Enter RTSP or HTTP stream URL",
      "Tên camera (VD: Cổng chính)": "Camera Name (e.g. Main Gate)",
      "Kết nối": "Connect",
      "Đang chờ phát hiện phương tiện...": "Waiting for vehicle detections...",
      "Phát hiện gần nhất": "Recent Detections",
      "Thời gian chạy": "Elapsed Time",
      "Phát hiện mới nhất": "Latest Detection",
      "ROI sẵn sàng": "ROI Ready",
      "Chưa có ROI": "No ROI Defined",
      "Chưa xem kết quả": "No results yet",
      "Đã phân tích gần đây": "Recently analyzed",
      "Kết quả các xe đã đếm được từ lần xem trước.": "Counted vehicles from previous session.",
      "Đã cấu hình": "Configured",
      "Chưa cấu hình": "Not configured",
      "👉 Bấm 'Xem trực tiếp' để bắt đầu AI.": "👉 Click 'View Live' to start AI.",
      "👉 Bấm 'Chỉnh ROI' để vẽ vùng đếm trước khi chạy AI.": "👉 Click 'Edit ROI' to draw counting zone before running AI.",
      "Đã Chọn Luồng Camera": "Camera Stream Selected",
      "Đang phân tích...": "Analyzing...",
      "🔴 Đông phương tiện": "🔴 Heavy Traffic",
      "🟡 Bình thường": "🟡 Normal Flow",
      "🟢 Thưa thớt": "🟢 Sparse Traffic",

      // AI Optimization / Config page
      "Tinh chỉnh lõi AI (YOLO) để loại bỏ hiện tượng đếm sót xe trong các video có góc quay khó, và theo dõi log cảnh báo hệ thống.": "Fine-tune YOLO AI core to eliminate vehicle skip counts under difficult viewing angles and monitor system logs.",
      "Biến số Nhận diện (AI Core)": "Detection Parameters (AI Core)",
      "Giảm \"Ngưỡng Tự tin\" nếu model bỏ sót nhiều xe ở xa (như file test1, test2). Tăng lên nếu nhận diện nhầm rác thành xe.": "Decrease 'Confidence' threshold if model misses distant vehicles. Increase if garbage is misidentified as vehicles.",
      "Ngưỡng Tự tin (Confidence)": "Confidence Threshold",
      "Mặc định: 0.5. Thử để 0.25 cho các video mờ.": "Default: 0.5. Try 0.25 for blurry videos.",
      "Kích thước vật thể tối thiểu (Min Box Area)": "Minimum Object Size (Min Box Area)",
      "Mặc định: 100. Giảm xuống 0-50 để bắt xe ở góc cực xa.": "Default: 100. Decrease to 0-50 to detect extremely distant vehicles.",
      "Thời gian chống trùng lặp biển số (LPR Debounce)": "License Plate Debounce Time (LPR Debounce)",
      "giây": "seconds",
      "Mặc định: 60 giây. Tránh lưu trùng lặp biển số của cùng một xe khi dừng đèn đỏ lâu.": "Default: 60s. Prevents duplicate plate records of the same vehicle at long red lights.",
      "Ngưỡng tự tin biển số (LPR Quality)": "Plate Confidence Threshold (LPR Quality)",
      "Mặc định: 0.20. Giảm xuống (ví dụ 0.15 - 0.25) để nhận diện các biển số nhỏ, xa, hoặc bị mờ do góc nghiêng.": "Default: 0.20. Decrease (e.g. 0.15 - 0.25) to read small, distant, or skewed license plates.",
      "Bộ lọc loại xe đếm": "Allowed Vehicle Classes Filter",
      "Nhấp chọn các loại phương tiện muốn đếm. Thay đổi sẽ cập nhật vào mô hình AI bên dưới.": "Select vehicle classes to count. Changes will apply to the AI model below.",
      "Cập nhật Mô hình AI": "Update AI Model Settings",
      "Lịch sử Cảnh báo & Tối ưu": "Alerts & Optimization Log History",
      "Loại Sự kiện": "Event Type",
      "Nội dung Chi tiết": "Detailed Content",
      "Cấu hình / Config": "Configuration / Config",
      "Cảnh báo / Warning": "Warning / Alert",
      "Thông báo / Info": "Notification / Info",

      // Technical Reports
      "Báo cáo phiên phân tích": "Analysis Session Reports",
      "Tất cả kết quả phân tích được lưu lại tại đây. Dữ liệu tự động cập nhật khi có phiên mới hoàn thành.": "All analysis session results are saved here. Data automatically updates on new session completion.",
      "Kết quả sẽ tự động xuất hiện trong bảng khi hoàn thành": "Results will appear in the table once the session completes",
      "Tổng xe (đang đếm)": "Total Vehicles (counting)",
      "Tổng số báo cáo": "Total Reports",
      "Tổng lượng phương tiện": "Total Vehicles Counted",
      "Tìm kiếm tên video, camera...": "Search video name, camera...",
      "Tất cả trạng thái": "All Statuses",
      "Xuất CSV": "Export CSV",
      "Phiên": "Session",
      "Tổng phân tích": "Total Counted",
      "Giờ cao điểm": "Peak Hour",
      "Trạng thái": "Status",
      "Thao tác": "Actions",
      "Không tìm thấy báo cáo": "No reports found",
      "Thử điều chỉnh bộ lọc hoặc từ khóa tìm kiếm của bạn.": "Try adjusting your filters or search keywords.",
      "Hệ thống chưa có báo cáo nào": "No reports in system yet",
      "Kết quả phân tích giao thông sẽ tự động được thu thập và lưu trữ vĩnh viễn tại đây ngay khi một phiên giám sát hoàn thành.": "Traffic analysis results will be automatically collected and permanently stored here on session completion.",
      "🚀 Bắt đầu ngay phiên phân tích đầu tiên": "🚀 Start your first analysis session now",
      "Chưa có phương tiện": "No vehicles counted yet",
      "Chi tiết Phiên phân tích #": "Analysis Session Details #",
      "Nguồn:": "Source:",
      "Tổng quan & Biểu đồ": "Overview & Charts",
      "Log Biển số nhận dạng": "License Plate Log",
      "Video góc nhìn AI": "AI View Video",
      "Khung giờ cao điểm": "Peak Hour Frame",
      "Thời gian bắt đầu": "Start Time",
      "Thời lượng phiên": "Session Duration",
      "Đi vào (Chiều đến):": "Inbound Direction:",
      "Đi ra (Chiều đi):": "Outbound Direction:",
      "Lưu lượng phương tiện theo thời gian": "Traffic Flow Rate Over Time",
      "Tìm kiếm biển số xe... (ví dụ: 98-T3)": "Search license plates... (e.g. 98-T3)",
      "Không phát hiện biển số xe nào trong phiên này": "No license plates detected in this session",
      "Không có bản ghi video kết quả cho phiên phân tích này": "No processed video recording for this session",
      "Hệ thống chạy trên luồng trực tiếp không bật chức năng ghi hoặc đã bị xóa file.": "System ran on a live stream without recording, or the video file has been deleted.",
      "Trình duyệt của bạn không hỗ trợ phát thẻ video.": "Your browser does not support HTML5 video.",
      "Xe": "Vehicle",
      "🚗 Ô tô": "🚗 Cars",
      "🏍️ Xe máy": "🏍️ Motorcycles",
      "🚌 Xe buýt": "🚌 Buses",
      "🚛 Xe tải": "🚛 Trucks",

      // Users
      "Đặt lại mật khẩu thành công!": "Password reset successful!",
      "Tạo người dùng": "Create User Account",
      "Họ tên": "Full Name",
      "Vai trò": "Role",
      "Hướng dẫn vai trò": "Role Guidelines",
      "Admin: quản lý người dùng, nguồn video, quản trị hệ thống và toàn bộ báo cáo.": "Admin: Manages user accounts, video sources, system settings, and all reports.",
      "User: xem bảng điều khiển, giám sát và báo cáo.": "User: View dashboard, monitor camera grids, and view reports.",
      "Lưu lý:": "Note:",
      "Lưu ý:": "Note:",
      "Tài khoản admin chính không thể bị vô hiệu hóa hoặc xóa. Tài khoản bị vô hiệu hóa sẽ không thể đăng nhập.": "The main admin account cannot be disabled or deleted. Disabled accounts cannot log in.",
      "Tài khoản người dùng": "User Accounts Registry",
      "Bị vô hiệu": "Disabled",
      "Vô hiệu hóa": "Disable",
      "🔑 Mật khẩu": "🔑 Password",
      "Mật khẩu mới cho ": "New password for ",
      "Nhập mật khẩu mới (≥8 ký tự)": "Enter new password (≥8 characters)",
      "Đặt lại": "Reset",
      "Hủy": "Cancel",

      // Brand settings
      "Thiết lập thông tin Đơn vị sử dụng": "Deployment Unit Profile Settings",
      "Địa chỉ": "Address",
      "Ảnh Logo": "Logo Image Preview",
      "Đóng": "Close",
      "Lưu cấu hình": "Save Settings",

      // System Settings (Admin)
      "Dung lượng CSDL": "Database Size",
      "Tổng lưu trữ": "Total Storage Used",
      "Thống kê chi tiết": "Detailed System Statistics",
      "Tổng phiên phân tích": "Total Analysis Sessions",
      "↳ Hoàn thành": "↳ Completed",
      "↳ Thất bại": "↳ Failed",
      "Video input": "Input Videos",
      "Video output": "Output Videos",
      "CSV / Logs": "CSVs / Output Logs",
      "Nhật ký hoạt động": "Activity Log Records",
      "Quản lý dữ liệu": "Data Storage Management",
      "Xóa dữ liệu cũ để giải phóng dung lượng hoặc reset hệ thống demo.": "Clear old data to free up storage space or reset the demo system.",
      "Xóa phiên phân tích & báo cáo": "Clear Analysis Sessions & Reports",
      "Xóa toàn bộ lịch sử phiên và báo cáo. Không xóa video hoặc nguồn.": "Delete all session history and reports. Does not delete videos or camera sources.",
      "Xóa phiên & báo cáo": "Clear Sessions & Reports",
      "Xóa video output đã xử lý": "Delete Processed Video Output",
      "Xóa toàn bộ video kết quả, CSV và log output.": "Delete all generated output videos, CSVs, and log outputs.",
      "Xóa video output": "Clear Video Outputs",
      "Xóa toàn bộ log hoạt động cũ.": "Clear all past system activity logs.",
      "Xóa nhật ký": "Clear Activity Logs",
      "Hành động": "Action",
      "Chi tiết": "Details",
      "IP": "IP Address",
      "Tạo user": "Create User",
      "Xóa user": "Delete User",
      "Đổi mật khẩu": "Change Password",
      "Bắt đầu phân tích": "Start Analysis",
      "Dừng phân tích": "Stop Analysis",
      "Xóa phiên": "Clear Sessions",
      "Xóa output": "Clear Output",
      "Chưa có nhật ký hoạt động nào.": "No activity logs recorded yet."
    }
  };

  var langToggle = document.getElementById("lang-toggle");
  var currentLang = localStorage.getItem("lang") || "vi";

  // Translate helper for other JS files
  window._t = function(text) {
    var lang = localStorage.getItem("lang") || "vi";
    var dict = window.translations[lang] || {};
    return dict[text] || text;
  };

  // Intercept window.confirm for localized confirmation messages
  var _originalConfirm = window.confirm;
  window.confirm = function (msg) {
    var isEn = (localStorage.getItem("lang") || "vi") === "en";
    if (isEn && msg) {
      if (msg.indexOf("Bạn chắc chắn muốn xóa tài khoản") !== -1) {
        var username = msg.match(/tài khoản\s+(.*?)\?/);
        msg = "Are you sure you want to delete the account " + (username ? username[1] : "") + "?";
      } else if (msg.indexOf("Bạn chắc chắn muốn xóa toàn bộ phiên phân tích") !== -1) {
        msg = "Are you sure you want to delete all analysis sessions and reports?";
      } else if (msg.indexOf("Bạn chắc chắn muốn xóa toàn bộ video output") !== -1) {
        msg = "Are you sure you want to delete all video outputs?";
      } else if (msg.indexOf("Xóa toàn bộ nhật ký hoạt động") !== -1) {
        msg = "Clear all activity logs?";
      }
    }
    return _originalConfirm(msg);
  };

  function translatePageText(lang) {
    var dict = window.translations[lang] || {};

    // 1. Translate title tooltips
    var elementsWithTitle = document.querySelectorAll("[title]");
    elementsWithTitle.forEach(function (el) {
      var title = el.getAttribute("title");
      var trimmed = title ? title.trim() : "";
      if (!trimmed) return;

      if (lang === "en") {
        if (dict[trimmed]) {
          if (!el.hasAttribute("data-orig-title")) {
            el.setAttribute("data-orig-title", title);
          }
          el.setAttribute("title", dict[trimmed]);
        }
      } else {
        if (el.hasAttribute("data-orig-title")) {
          el.setAttribute("title", el.getAttribute("data-orig-title"));
        }
      }
    });

    // 2. Translate text nodes
    var walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      null,
      false
    );
    
    var node;
    var dict = window.translations[lang] || {};

    while (node = walker.nextNode()) {
      var parent = node.parentElement;
      if (!parent) continue;

      var parentTagName = parent.tagName.toLowerCase();
      if (parentTagName === "script" || parentTagName === "style") {
        continue;
      }

      var text = node.nodeValue;
      var trimmed = text.trim();
      if (!trimmed) continue;

      if (lang === "en") {
        // If it's an exact match in the dictionary
        if (dict[trimmed]) {
          if (!parent.hasAttribute("data-orig-vi")) {
            parent.setAttribute("data-orig-vi", text);
          }
          var leadingWs = text.match(/^\s*/)[0];
          var trailingWs = text.match(/\s*$/)[0];
          node.nodeValue = leadingWs + dict[trimmed] + trailingWs;
        } else {
          // Check for sub-phrase replacements
          var replaced = text;
          var found = false;
          if (trimmed.indexOf("↗ Đi") !== -1) {
            replaced = replaced.replace("↗ Đi", "↗ Outbound");
            found = true;
          }
          if (trimmed.indexOf("↘ Về") !== -1) {
            replaced = replaced.replace("↘ Về", "↙ Inbound");
            found = true;
          }
          if (trimmed.indexOf("xe / phút") !== -1) {
            replaced = replaced.replace("xe / phút", "vehicles / min");
            found = true;
          }
          if (trimmed.indexOf("xe/giờ") !== -1) {
            replaced = replaced.replace("xe/giờ", "veh/hour");
            found = true;
          }
          if (trimmed.indexOf("Đang phân tích phiên") !== -1) {
            replaced = replaced.replace("Đang phân tích phiên", "Analyzing session");
            found = true;
          }
          if (trimmed.indexOf("Đang tải dữ liệu...") !== -1) {
            replaced = replaced.replace("Đang tải dữ liệu...", "Loading data...");
            found = true;
          }
          if (trimmed.indexOf("Hiện") !== -1 && trimmed.indexOf("bản ghi") !== -1) {
            replaced = replaced.replace("Hiện", "Showing").replace("bản ghi", "records");
            found = true;
          }
          if (trimmed.indexOf("bản ghi còn lại") !== -1) {
            replaced = replaced.replace("bản ghi còn lại", "records remaining").replace("Tải thêm", "Load more");
            found = true;
          }
          if (trimmed.indexOf("Chi tiết Phiên phân tích #") !== -1) {
            replaced = replaced.replace("Chi tiết Phiên phân tích #", "Analysis Session Details #");
            found = true;
          }
          if (trimmed.indexOf("Nguồn:") !== -1) {
            replaced = replaced.replace("Nguồn:", "Source:");
            found = true;
          }
          if (trimmed.indexOf("Đang tải danh sách biển số...") !== -1) {
            replaced = replaced.replace("Đang tải danh sách biển số...", "Loading license plate log...");
            found = true;
          }
          if (trimmed.indexOf("Đăng nhập thất bại cho") !== -1) {
            replaced = replaced.replace("Đăng nhập thất bại cho", "Login failed for");
            found = true;
          }
          if (trimmed.indexOf("Đăng nhập thành công") !== -1) {
            replaced = replaced.replace("Đăng nhập thành công", "Login successful");
            found = true;
          }
          if (trimmed.indexOf("Đã xóa") !== -1 && trimmed.indexOf("file output") !== -1) {
            replaced = replaced.replace("Đã xóa", "Deleted").replace("file output", "output files");
            found = true;
          }
          if (trimmed.indexOf("Đã xóa") !== -1 && trimmed.indexOf("nhật ký cũ") !== -1) {
            replaced = replaced.replace("Đã xóa", "Deleted").replace("nhật ký cũ", "old logs");
            found = true;
          }
          if (trimmed.indexOf("Tìm thấy:") !== -1 && trimmed.indexOf("biển số") !== -1) {
            replaced = replaced.replace("Tìm thấy:", "Found:").replace("biển số", "license plates");
            found = true;
          }
          if (trimmed.indexOf("Đang tải...") !== -1) {
            replaced = replaced.replace("Đang tải...", "Loading...");
            found = true;
          }

          if (found) {
            if (!parent.hasAttribute("data-orig-vi")) {
              parent.setAttribute("data-orig-vi", text);
            }
            node.nodeValue = replaced;
          }
        }
      } else {
        // Restore original VI value
        if (parent.hasAttribute("data-orig-vi")) {
          node.nodeValue = parent.getAttribute("data-orig-vi");
        }
      }
    }
  }

  var observer = null;
  function startObserver() {
    if (observer) return;
    observer = new MutationObserver(function (mutations) {
      observer.disconnect();
      translatePageText(currentLang);
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function stopObserver() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  }

  function applyTranslations(lang) {
    currentLang = lang;
    localStorage.setItem("lang", lang);

    stopObserver();

    // Update toggle button text and tooltip
    if (langToggle) {
      var langTextSpan = langToggle.querySelector(".lang-text");
      if (langTextSpan) {
        langTextSpan.textContent = lang === "vi" ? "EN" : "VI";
      }
      langToggle.setAttribute("title", window.translations[lang]["lang-switch-tooltip"]);
    }

    // Walk and translate DOM
    translatePageText(lang);

    // Handle collapse btn text manually since collapse/expand state has its own overrides
    var collapseBtnSpan = collapseBtn ? collapseBtn.querySelector("span") : null;
    if (collapseBtnSpan && sidebar) {
      if (sidebar.classList.contains("collapsed")) {
        collapseBtnSpan.textContent = lang === "vi" ? "Mở rộng" : "Expand Menu";
      } else {
        collapseBtnSpan.textContent = window.translations[lang]["btn-collapse"];
      }
    }

    // Dispatch event for other pages/charts to adjust
    window.dispatchEvent(new CustomEvent("langchanged", { detail: { lang: lang } }));

    // Restart observer for dynamic content
    startObserver();
  }

  if (langToggle) {
    langToggle.addEventListener("click", function (e) {
      e.preventDefault();
      var nextLang = currentLang === "vi" ? "en" : "vi";
      applyTranslations(nextLang);
    });
  }

  // Initial apply
  applyTranslations(currentLang);

  // Hook into collapsible sidebar events to handle button text in English/Vietnamese
  if (collapseBtn && sidebar) {
    collapseBtn.addEventListener("click", function () {
      setTimeout(function() {
        applyTranslations(currentLang);
      }, 50);
    });
  }
})();
