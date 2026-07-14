// ==========================================================
// THAO TÁC JS TRÊN BẢNG BÁO CÁO (Lọc, Tìm kiếm, Xuất CSV, Modal Chi tiết)
// ==========================================================
function _t(text) {
  if (typeof window._t === 'function') {
    return window._t(text);
  }
  return text;
}

document.addEventListener('DOMContentLoaded', function() {
  const searchInput = document.getElementById('search-input');
  const statusFilter = document.getElementById('status-filter');
  const exportBtn = document.getElementById('export-csv-btn');
  const selectAllCheckbox = document.getElementById('select-all-reports');
  const rowCheckboxes = document.querySelectorAll('.report-checkbox');
  
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
        // Uncheck checkbox if row gets hidden by filters
        const cb = row.querySelector('.report-checkbox');
        if (cb && cb.checked) {
          cb.checked = false;
        }
      }
    });
    
    if (selectAllCheckbox) {
      selectAllCheckbox.checked = false;
    }
    updateExportButton();

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

  // Checkbox interactions
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener('change', function() {
      const isChecked = selectAllCheckbox.checked;
      const visibleRows = document.querySelectorAll('.report-row');
      visibleRows.forEach(row => {
        if (row.style.display !== 'none') {
          const cb = row.querySelector('.report-checkbox');
          if (cb) {
            cb.checked = isChecked;
          }
        }
      });
      updateExportButton();
    });
  }

  rowCheckboxes.forEach(cb => {
    cb.addEventListener('change', function() {
      if (!cb.checked && selectAllCheckbox) {
        selectAllCheckbox.checked = false;
      }
      updateExportButton();
    });
  });

  function updateExportButton() {
    if (!exportBtn) return;
    const checkedCount = document.querySelectorAll('.report-checkbox:checked').length;
    const svgIcon = `<svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24" style="margin-right: 6px;"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>`;
    
    if (checkedCount > 0) {
      exportBtn.innerHTML = svgIcon + `Xuất CSV (${checkedCount})`;
      exportBtn.style.background = '#059669'; // Green active status
    } else {
      exportBtn.innerHTML = svgIcon + 'Xuất CSV (Tất cả)';
      exportBtn.style.background = ''; // Default
    }
  }

  // Initial call
  updateExportButton();
  
  if (exportBtn) {
    exportBtn.addEventListener('click', function() {
      let selectedSessions = [];
      const checkedBoxes = document.querySelectorAll('.report-checkbox:checked');
      
      if (checkedBoxes.length > 0) {
        checkedBoxes.forEach(cb => {
          selectedSessions.push(cb.getAttribute('data-session'));
        });
      } else {
        const allRows = document.querySelectorAll('.report-row');
        allRows.forEach(row => {
          if (row.style.display !== 'none') {
            selectedSessions.push(row.getAttribute('data-session'));
          }
        });
      }

      if (selectedSessions.length === 0) {
        alert('Không có dữ liệu báo cáo nào để xuất!');
        return;
      }

      // Trực tiếp gọi API xuất báo cáo phương tiện chi tiết
      const sessionsParam = selectedSessions.join(',');
      window.location.href = `/api/export-reports?sessions=${sessionsParam}`;
    });
  }

  // ==========================================================
  // XỬ LÝ MODAL CHI TIẾT BÁO CÁO & BIỂU ĐỒ
  // ==========================================================
  const modal = document.getElementById('report-detail-modal');
  const closeModalBtn = document.getElementById('close-modal-btn');
  const tabButtons = document.querySelectorAll('.modal-tab-btn');
  const tabPanels = document.querySelectorAll('.modal-tab-panel');
  
  let doughnutChart = null;
  let lineChart = null;
  let currentLprEvents = []; // Cache LPR events for inline searching

  // Click on row to open modal
  const reportRows = document.querySelectorAll('.report-row');
  reportRows.forEach(row => {
    row.addEventListener('click', function(e) {
      // If user clicked directly on a video play hyperlink icon in table, open modal on video tab!
      let directVideo = false;
      if (e.target.tagName === 'A' || e.target.closest('a')) {
        e.preventDefault();
        directVideo = true;
      }

      const sessionId = row.getAttribute('data-session');
      if (sessionId) {
        openReportDetail(sessionId, directVideo);
      }
    });
  });

  if (closeModalBtn && modal) {
    closeModalBtn.addEventListener('click', closeReportDetail);
    // Click outside to close
    modal.addEventListener('click', function(e) {
      if (e.target === modal) {
        closeReportDetail();
      }
    });
  }

  // Tab switching
  tabButtons.forEach(btn => {
    btn.addEventListener('click', function() {
      tabButtons.forEach(b => b.classList.remove('active'));
      tabPanels.forEach(p => p.style.display = 'none');

      btn.classList.add('active');
      const targetTabId = btn.getAttribute('data-tab');
      const targetPanel = document.getElementById(targetTabId);
      if (targetPanel) {
        targetPanel.style.display = 'block';
      }
    });
  });

  // LPR search filter
  const lprSearchInput = document.getElementById('modal-lpr-search');
  if (lprSearchInput) {
    lprSearchInput.addEventListener('input', function() {
      filterModalLpr(lprSearchInput.value);
    });
  }

  function openReportDetail(sessionId, directVideo = false) {
    // Show modal container
    if (modal) modal.style.display = 'flex';
    document.body.style.overflow = 'hidden'; // Lock background scroll

    // Set loading placeholders
    document.getElementById('modal-session-title').textContent = `Chi tiết Phiên phân tích #${sessionId}`;
    document.getElementById('modal-session-source').textContent = 'Đang tải dữ liệu...';
    document.getElementById('modal-stat-total').innerHTML = '...';
    document.getElementById('modal-stat-peak').textContent = '...';
    document.getElementById('modal-stat-start').textContent = '...';
    document.getElementById('modal-stat-duration').textContent = '...';
    document.getElementById('modal-lpr-tbody').innerHTML = '<tr><td colspan="5" style="text-align:center;padding:20px;color:var(--color-muted);">Đang tải danh sách biển số...</td></tr>';
    document.getElementById('modal-lpr-count').textContent = 'Đang tải...';

    // Fetch report details
    fetch(`/api/reports/${sessionId}`, { credentials: 'same-origin' })
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          alert(`Không thể tải chi tiết báo cáo: ${data.error}`);
          closeReportDetail();
          return;
        }

        const meta = data.metadata || {};
        document.getElementById('modal-session-source').textContent = `Nguồn: ${meta.source_name || 'N/A'}`;
        document.getElementById('modal-stat-total').innerHTML = `${meta.total} <span style="font-size:11px;font-weight:500;color:var(--color-muted);">xe</span>`;
        document.getElementById('modal-stat-peak').textContent = meta.peak_hour_label || 'N/A';
        document.getElementById('modal-stat-start').textContent = meta.started_at || 'N/A';
        document.getElementById('modal-stat-duration').textContent = data.duration_formatted || 'N/A';

        // Render direction stats if counts exist
        const dir = data.direction_counts || {};
        const dirContainer = document.getElementById('direction-container');
        if (dirContainer) {
          if (dir.in > 0 || dir.out > 0) {
            dirContainer.style.display = 'flex';
            document.getElementById('direction-in-val').textContent = dir.in;
            document.getElementById('direction-out-val').textContent = dir.out;
          } else {
            dirContainer.style.display = 'none';
          }
        }

        // Render LPR Events list
        currentLprEvents = data.lpr_events || [];
        renderModalLprTable(currentLprEvents);
        if (lprSearchInput) lprSearchInput.value = ''; // Reset search field

        // Render Video Player
        const videoPlayer = document.getElementById('modal-video-player');
        const videoContainer = document.getElementById('modal-video-container');
        const videoEmpty = document.getElementById('modal-video-empty');
        if (videoPlayer) {
          if (meta.media_url) {
            videoPlayer.src = meta.media_url;
            videoPlayer.load();
            if (videoContainer) videoContainer.style.display = 'block';
            if (videoEmpty) videoEmpty.style.display = 'none';
          } else {
            videoPlayer.removeAttribute('src');
            if (videoContainer) videoContainer.style.display = 'none';
            if (videoEmpty) videoEmpty.style.display = 'block';
          }
        }

        // Render Charts
        renderCharts(meta.per_class || {}, data.chart_data || {});

        // Direct video tab if clicked from video icon
        if (directVideo) {
          const videoTabBtn = document.querySelector('.modal-tab-btn[data-tab="tab-video"]');
          if (videoTabBtn) videoTabBtn.click();
        } else {
          // Reset to default tab (Overview)
          const overviewTabBtn = document.querySelector('.modal-tab-btn[data-tab="tab-overview"]');
          if (overviewTabBtn) overviewTabBtn.click();
        }
      })
      .catch(err => {
        console.error(err);
        alert('Lỗi kết nối khi tải chi tiết báo cáo.');
        closeReportDetail();
      });
  }

  function closeReportDetail() {
    if (modal) modal.style.display = 'none';
    document.body.style.overflow = ''; // Restore background scroll

    // Stop video playing if modal closed
    const videoPlayer = document.getElementById('modal-video-player');
    if (videoPlayer) {
      videoPlayer.pause();
      videoPlayer.removeAttribute('src');
    }

    // Destroy charts
    if (doughnutChart) {
      doughnutChart.destroy();
      doughnutChart = null;
    }
    if (lineChart) {
      lineChart.destroy();
      lineChart = null;
    }
  }

  function renderCharts(perClass, timeSeries) {
    // 1. Doughnut Chart
    const ctxDoughnut = document.getElementById('modal-doughnut-chart');
    if (ctxDoughnut) {
      const labels = [_t('Ô tô'), _t('Xe máy'), _t('Xe buýt'), _t('Xe tải')];
      const counts = [
        perClass.car || perClass.automobile || 0,
        perClass.motorcycle || 0,
        perClass.bus || 0,
        perClass.truck || 0
      ];

      // Avoid rendering empty chart labels
      const hasData = counts.some(c => c > 0);
      
      if (doughnutChart) doughnutChart.destroy();
      
      doughnutChart = new Chart(ctxDoughnut, {
        type: 'doughnut',
        data: {
          labels: labels,
          datasets: [{
            data: hasData ? counts : [0, 0, 0, 0],
            backgroundColor: ['#6366f1', '#f59e0b', '#10b981', '#ef4444'],
            borderWidth: 2,
            borderColor: '#ffffff'
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'bottom',
              labels: {
                boxWidth: 12,
                font: { size: 11, weight: '600' }
              }
            }
          },
          cutout: '70%'
        }
      });
    }

    // 2. Line Flow Chart
    const ctxLine = document.getElementById('modal-line-chart');
    if (ctxLine) {
      if (lineChart) lineChart.destroy();

      lineChart = new Chart(ctxLine, {
        type: 'line',
        data: {
          labels: timeSeries.labels || [],
          datasets: [
            {
              label: _t('Tổng số xe'),
              data: timeSeries.total || [],
              borderColor: '#6366f1',
              backgroundColor: 'rgba(99, 102, 241, 0.1)',
              fill: true,
              tension: 0.3,
              borderWidth: 2.5
            },
            {
              label: _t('Ô tô'),
              data: timeSeries.car || [],
              borderColor: '#2563eb',
              borderWidth: 1.5,
              tension: 0.3,
              fill: false,
              hidden: true
            },
            {
              label: _t('Xe máy'),
              data: timeSeries.motorcycle || [],
              borderColor: '#f59e0b',
              borderWidth: 1.5,
              tension: 0.3,
              fill: false,
              hidden: true
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'top',
              labels: { boxWidth: 12, font: { size: 10, weight: '600' } }
            }
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: { font: { size: 10 } }
            },
            y: {
              beginAtZero: true,
              ticks: { precision: 0, font: { size: 10 } }
            }
          }
        }
      });
    }
  }

  function renderModalLprTable(events) {
    const tbody = document.getElementById('modal-lpr-tbody');
    const emptyMsg = document.getElementById('modal-lpr-empty');
    if (!tbody) return;

    tbody.innerHTML = '';
    
    if (events.length === 0) {
      if (emptyMsg) emptyMsg.style.display = 'block';
      document.querySelector('.modal-lpr-table').style.display = 'none';
      document.getElementById('modal-lpr-count').textContent = 'Tìm thấy: 0 biển số';
      return;
    }

    if (emptyMsg) emptyMsg.style.display = 'none';
    document.querySelector('.modal-lpr-table').style.display = 'table';
    document.getElementById('modal-lpr-count').textContent = `Tìm thấy: ${events.length} biển số`;

    events.forEach(ev => {
      const tr = document.createElement('tr');
      tr.style.borderBottom = '1px solid #f1f5f9';
      
      // Format time
      let timeParts = ev.created_at.split(' ');
      let timeStr = timeParts[1] || ev.created_at;

      // Class badge color
      let classLabel = _t('Xe');
      let classColor = '#475569';
      let classBg = '#f1f5f9';
      let c = ev.vehicle_class.toLowerCase();
      if (c === 'car' || c === 'automobile') {
        classLabel = _t('🚗 Ô tô');
        classColor = '#1e3a8a';
        classBg = '#dbeafe';
      } else if (c === 'motorcycle' || c === 'motorbike') {
        classLabel = _t('🏍️ Xe máy');
        classColor = '#78350f';
        classBg = '#fef3c7';
      } else if (c === 'bus') {
        classLabel = _t('🚌 Xe buýt');
        classColor = '#064e3b';
        classBg = '#d1fae5';
      } else if (c === 'truck') {
        classLabel = _t('🚛 Xe tải');
        classColor = '#7f1d1d';
        classBg = '#fee2e2';
      }

      // Plate Crop image cell
      let imgCell = '<span style="color:#cbd5e1">—</span>';
      if (ev.plate_image_path) {
        let imgUrl = ev.plate_image_path;
        if (!imgUrl.startsWith('/') && !imgUrl.startsWith('http')) {
          imgUrl = '/' + imgUrl;
        }
        imgCell = `<img src="${imgUrl}" alt="Plate crop" style="max-height: 28px; max-width: 100px; object-fit: contain; border-radius: 4px; border: 1px solid #cbd5e1; background: #fff; cursor: zoom-in;" onclick="window.open('${imgUrl}', '_blank')">`;
      }

      tr.innerHTML = `
        <td style="padding: 10px 16px; font-weight: 600; color: #64748b;">${timeStr}</td>
        <td style="padding: 10px 16px;">
          <span class="lpr-v-badge" style="color: ${classColor}; background: ${classBg};">${classLabel}</span>
        </td>
        <td style="padding: 10px 16px;">
          <span class="lpr-plate-badge">${ev.license_plate}</span>
        </td>
        <td style="padding: 10px 16px; font-weight: 600; color: #059669;">${Math.round(ev.confidence * 100)}%</td>
        <td style="padding: 10px 16px; text-align: center;">${imgCell}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  function filterModalLpr(query) {
    const q = query.toLowerCase().trim();
    if (!q) {
      renderModalLprTable(currentLprEvents);
      return;
    }
    const filtered = currentLprEvents.filter(ev => {
      return ev.license_plate.toLowerCase().includes(q) || ev.vehicle_class.toLowerCase().includes(q);
    });
    renderModalLprTable(filtered);
    document.getElementById('modal-lpr-count').textContent = `Tìm thấy: ${filtered.length} biển số (Bộ lọc: "${query}")`;
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
    fetch("/api/monitoring/live-state", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) { handleReportUpdate(data); })
      .catch(function () {})
      .finally(function () { connectReportsWS(); });
  }
})();
