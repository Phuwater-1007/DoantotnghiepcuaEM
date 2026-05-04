// ==========================================================
// THAO TÁC JS TRÊN BẢNG BÁO CÁO (Lọc, Tìm kiếm, Xuất CSV...)
// ==========================================================
document.addEventListener('DOMContentLoaded', function() {
  const searchInput = document.getElementById('search-input');
  const statusFilter = document.getElementById('status-filter');
  const exportBtn = document.getElementById('export-csv-btn');
  
  if (searchInput && statusFilter) {
    searchInput.addEventListener('input', applyFilters);
    statusFilter.addEventListener('change', applyFilters);
  }

  function applyFilters() {
    const searchTerm = searchInput.value.toLowerCase();
    const statusTerm = statusFilter.value;
    const rows = document.querySelectorAll('.report-row');
    let visibleCount = 0;
    
    rows.forEach(row => {
      const textData = row.textContent.toLowerCase();
      const rowStatus = row.dataset.status;
      
      const matchSearch = textData.includes(searchTerm);
      const matchStatus = statusTerm === 'all' || rowStatus === statusTerm;
      
      if (matchSearch && matchStatus) {
        row.style.display = '';
        visibleCount++;
      } else {
        row.style.display = 'none';
      }
    });
    
    const noResults = document.getElementById('no-results');
    const thead = document.querySelector('.premium-table thead');
    if (noResults && thead) {
      if (visibleCount === 0 && rows.length > 0) {
        noResults.style.display = 'block';
        thead.style.display = 'none';
      } else {
        noResults.style.display = 'none';
        thead.style.display = '';
      }
    }
  }
  
  if (exportBtn) {
    exportBtn.addEventListener('click', function() {
      // Get current timestamp for the report header
      const now = new Date();
      const timeString = now.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
      const dateString = now.toLocaleDateString('vi-VN');
      
      // Build Professional CSV Header
      let csv = "\ufeffTHỐNG KÊ LƯU LƯỢNG PHƯƠNG TIỆN GIAO THÔNG\n";
      csv += "Ứng dụng Hệ thống Giám sát Cơ sở hạ tầng AI\n";
      csv += `Thời gian xuất báo cáo: ${timeString} - ${dateString}\n\n`;
      
      // Feature Columns
      csv += "Phiên,Ngày,Giờ,Nguồn phân tích,Tổng lượng xe,Ô tô,Xe máy,Xe buýt,Xe tải,Khung giờ cao điểm,Trạng thái\n";
      
      const rows = document.querySelectorAll('.report-row');
      
      rows.forEach(row => {
        if (row.style.display !== 'none') {
          // Read clean data strictly from data attributes
          const session = row.getAttribute('data-session') || '';
          const dateFull = row.getAttribute('data-date') || '';
          const source = row.getAttribute('data-source') || '';
          const total = row.getAttribute('data-total') || '0';
          const car = row.getAttribute('data-car') || '0';
          const moto = row.getAttribute('data-moto') || '0';
          const bus = row.getAttribute('data-bus') || '0';
          const truck = row.getAttribute('data-truck') || '0';
          const peak = row.getAttribute('data-peak') && row.getAttribute('data-peak') !== 'N/A' ? row.getAttribute('data-peak') : 'Không xác định';
          const status = row.getAttribute('data-status-label') || '';
          
          // Split Date/Time if possible
          let dateParts = dateFull.split(' ');
          let dateOnly = dateParts[0] || dateFull;
          let timeOnly = dateParts[1] || '';
          
          const cols = [
            `#${session}`,
            dateOnly,
            timeOnly,
            source,
            total,
            car,
            moto,
            bus,
            truck,
            peak,
            status
          ];
          
          // Escape and stringify row
          const data = cols.map(c => `"${c.replace(/"/g, '""')}"`);
          csv += data.join(',') + "\n";
        }
      });
      
      // Tạo file tải về
      const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `BaoCao_GiaoThong_${dateString.replace(/\//g, '')}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    });
  }
});

// ==========================================================
// WEBSOCKET CHO CẬP NHẬT BANNER KHI CÓ PHIÊN ĐANG CHẠY
// ==========================================================
(function () {
  var wasRunning = false;
  var _reportsWS = null;
  var _reportsReconnectTimer = null;

  function handleReportUpdate(data) {
    var activeId = data.active_session_id;
    var live = data.live_state;
    var banner = document.getElementById("report-live-banner");
    var liveTitle = document.getElementById("report-live-title");
    var liveTotalEl = document.getElementById("report-live-total");

    if (activeId && live && (live.status === "running" || live.status === "queued")) {
      wasRunning = true;
      if (banner) banner.style.display = "";
      if (liveTitle) liveTitle.textContent = "Đang phân tích: " + (live.source_name || "video");
      var summary = live.summary || {};
      var total = (typeof summary.total === "number") ? summary.total : 0;
      if (liveTotalEl) liveTotalEl.textContent = total;
    } else {
      if (banner) banner.style.display = "none";
      // Auto-reload khi phiên vừa hoàn thành → hiện kết quả mới
      if (wasRunning) {
        wasRunning = false;
        setTimeout(function () { window.location.reload(); }, 1500);
      }
    }
  }

  function connectReportsWS() {
    if (_reportsWS && (_reportsWS.readyState === WebSocket.OPEN || _reportsWS.readyState === WebSocket.CONNECTING)) {
      return;
    }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/ws/monitoring");
    _reportsWS = ws;

    ws.onmessage = function (event) {
      try { handleReportUpdate(JSON.parse(event.data)); } catch (e) {}
    };

    ws.onclose = function () {
      _reportsReconnectTimer = setTimeout(connectReportsWS, 2000);
    };

    ws.onerror = function () { ws.close(); };
  }

  if (document.getElementById('report-live-banner')) {
    // Initial state check then switch to WebSocket
    fetch("/api/monitoring/live-state", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) { handleReportUpdate(data); })
      .catch(function () {})
      .finally(function () { connectReportsWS(); });
  }
})();

