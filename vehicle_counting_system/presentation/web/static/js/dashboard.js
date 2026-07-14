(function () {
  // ====================================================================
  // Dashboard Real-time Sync Engine
  // Uses WebSocket /ws/dashboard for server-push updates instead of polling.
  // Merged from headless analysis AND live MJPEG stream stats.
  // ====================================================================

  var conf = window.DashboardData || {};

  // Baseline DB values
  var dbTodayTotal = conf.todayTotal || 0;
  var dbAutomobile = conf.automobile || 0;
  var dbMotorcycle = conf.motorcycle || 0;
  var dbBus = conf.bus || 0;
  var dbTruck = conf.truck || 0;
  var dbPerClass = conf.perClass || {};

  // Track previous state for "was running" detection
  var wasHeadlessRunning = conf.wasHeadlessRunning || false;
  var wasStreamActive = false;

  // ====================================================================
  // Helper: merge per_class dicts
  // ====================================================================
  function mergePerClass(base, live) {
    var result = {};
    var keys = Object.keys(base);
    Object.keys(live).forEach(function (k) {
      if (keys.indexOf(k) === -1) keys.push(k);
    });
    keys.forEach(function (k) {
      result[k] = (base[k] || 0) + (live[k] || 0);
    });
    return result;
  }

  function getVehicleMix(perClass) {
    return {
      automobile: (perClass.car || 0) + (perClass.truck || 0) + (perClass.bus || 0),
      motorcycle: perClass.motorcycle || 0,
      car: perClass.car || 0,
      truck: perClass.truck || 0,
      bus: perClass.bus || 0,
    };
  }

  // ====================================================================
  // DOM updaters
  // ====================================================================
  function updateStatCards(total, mix) {
    var el;
    el = document.getElementById("stat-today-total");
    if (el) el.textContent = total;
    el = document.getElementById("stat-automobile");
    if (el) el.textContent = mix.car;
    el = document.getElementById("stat-motorcycle");
    if (el) el.textContent = mix.motorcycle;
  }

  function setStatCardLive(isLive) {
    var ids = ["stat-today-total", "stat-automobile", "stat-motorcycle"];
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) {
        if (isLive) el.classList.add("is-live");
        else el.classList.remove("is-live");
      }
    });
  }

  // ====================================================================
  // Chart.js – Donut (vehicle mix) & Bar (hourly activity)
  // ====================================================================
  var CHART_COLORS = ['#6366f1', '#f59e0b', '#10b981', '#ef4444'];
  var donutChart = null;
  var hourlyChart = null;

  function initDonutChart() {
    var canvas = document.getElementById('donut-chart');
    if (!canvas) return;
    if (donutChart) return;
    var ctx = canvas.getContext('2d');
    var isEn = (localStorage.getItem("lang") || "vi") === "en";
    var donutLabels = isEn ? ['Cars', 'Motorcycles', 'Buses', 'Trucks'] : ['Ô tô', 'Xe máy', 'Xe buýt', 'Xe tải'];
    donutChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: donutLabels,
        datasets: [{
          data: [dbAutomobile, dbMotorcycle, dbBus, dbTruck],
          backgroundColor: CHART_COLORS,
          borderWidth: 0,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '68%',
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(30, 27, 75, 0.92)',
            titleFont: { size: 13, weight: '600' },
            bodyFont: { size: 12 },
            padding: 10,
            cornerRadius: 8,
            callbacks: {
              label: function (ctx) {
                var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                var pct = total > 0 ? Math.round(ctx.raw / total * 100) : 0;
                return ctx.label + ': ' + ctx.raw + ' (' + pct + '%)';
              }
            }
          }
        },
        animation: { animateRotate: true, duration: 800 }
      }
    });
  }

  // Shared chart config factory for the hourly bar chart
  function _hourlyChartConfig(ctx, labels, values) {
    // Gradient for bars
    var barGradient = ctx.createLinearGradient(0, 0, 0, 220);
    barGradient.addColorStop(0, 'rgba(99, 102, 241, 0.95)');
    barGradient.addColorStop(0.5, 'rgba(129, 140, 248, 0.75)');
    barGradient.addColorStop(1, 'rgba(165, 180, 252, 0.45)');

    // Hover gradient
    var hoverGradient = ctx.createLinearGradient(0, 0, 0, 220);
    hoverGradient.addColorStop(0, 'rgba(79, 70, 229, 1)');
    hoverGradient.addColorStop(0.5, 'rgba(99, 102, 241, 0.9)');
    hoverGradient.addColorStop(1, 'rgba(129, 140, 248, 0.6)');

    // Smart Y-axis step: avoid showing too many ticks
    var maxVal = Math.max.apply(null, values) || 1;
    var yStep;
    if (maxVal <= 10) yStep = 2;
    else if (maxVal <= 50) yStep = 10;
    else if (maxVal <= 200) yStep = 25;
    else if (maxVal <= 500) yStep = 50;
    else yStep = Math.ceil(maxVal / 8 / 10) * 10;

    var isEn = (localStorage.getItem("lang") || "vi") === "en";
    var barLabel = isEn ? 'Vehicles' : 'Phương tiện';

    return {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: barLabel,
          data: values,
          backgroundColor: barGradient,
          hoverBackgroundColor: hoverGradient,
          borderRadius: 6,
          borderSkipped: false,
          barPercentage: 0.65,
          categoryPercentage: 0.7,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { intersect: false, mode: 'index' },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(30, 27, 75, 0.94)',
            titleFont: { size: 13, weight: '600', family: 'Inter, system-ui, sans-serif' },
            bodyFont: { size: 12, family: 'Inter, system-ui, sans-serif' },
            padding: { top: 10, bottom: 10, left: 14, right: 14 },
            cornerRadius: 10,
            displayColors: false,
            filter: function (item) { return item.raw > 0; },
            callbacks: {
              title: function (items) { return '🕐 ' + items[0].label; },
              label: function (c) {
                return c.raw + (isEn ? ' vehicles passed' : ' phương tiện qua lại');
              }
            }
          }
        },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: {
              font: { size: 10, family: 'Inter, system-ui, sans-serif' },
              color: '#9ca3af',
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 9,
            }
          },
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(0,0,0,0.04)', drawBorder: false },
            border: { display: false },
            ticks: {
              font: { size: 11, family: 'Inter, system-ui, sans-serif' },
              color: '#9ca3af',
              stepSize: yStep,
              padding: 8,
              callback: function (val) { return Number.isInteger(val) ? val : ''; }
            }
          }
        },
        animation: { duration: 700, easing: 'easeOutQuart' }
      }
    };
  }

  function initHourlyChart() {
    var canvas = document.getElementById('hourly-chart');
    if (!canvas) return;
    if (hourlyChart) return;
    var ctx = canvas.getContext('2d');

    var serverData = conf.serverData || {};
    var allLabels = [];
    var allValues = [];
    for (var h = 6; h <= 23; h++) {
      var key = h.toString().padStart(2, '0');
      allLabels.push(key + ':00');
      allValues.push(serverData[key] || 0);
    }

    hourlyChart = new Chart(ctx, _hourlyChartConfig(ctx, allLabels, allValues));
  }

  // Initialize charts on page load if canvas exists
  if (document.getElementById('donut-chart')) initDonutChart();
  if (document.getElementById('hourly-chart')) initHourlyChart();

  function ensureDonutChartPanel(mix) {
    if (document.getElementById('donut-chart')) return;
    var content = document.getElementById('vehicle-mix-content');
    if (!content) return;

    var total = (mix.car || 0) + (mix.motorcycle || 0) + (mix.bus || 0) + (mix.truck || 0);

    content.innerHTML = '<div style="display: flex; align-items: center; gap: 24px; flex-wrap: wrap;">'
      + '<div style="position: relative; width: 200px; height: 200px; flex-shrink: 0;">'
      + '<canvas id="donut-chart"></canvas>'
      + '<div id="donut-center" style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); text-align: center; pointer-events: none;">'
      + '<div style="font-size: 28px; font-weight: 700; color: var(--color-text);">' + total + '</div>'
      + '<div style="font-size: 11px; color: var(--color-muted); text-transform: uppercase; letter-spacing: 0.5px;">Tổng xe</div>'
      + '</div></div>'
      + '<div style="flex: 1; min-width: 140px;">'
      + '<div class="chart-legend-list">'
      + '<div class="chart-legend-item"><span class="chart-legend-dot" style="background: #6366f1;"></span><span class="chart-legend-label">Ô tô</span><strong id="mix-automobile">' + (mix.car || 0) + '</strong></div>'
      + '<div class="chart-legend-item"><span class="chart-legend-dot" style="background: #f59e0b;"></span><span class="chart-legend-label">Xe máy</span><strong id="mix-motorcycle">' + (mix.motorcycle || 0) + '</strong></div>'
      + '<div class="chart-legend-item"><span class="chart-legend-dot" style="background: #10b981;"></span><span class="chart-legend-label">Xe buýt</span><strong id="mix-bus">' + (mix.bus || 0) + '</strong></div>'
      + '<div class="chart-legend-item"><span class="chart-legend-dot" style="background: #ef4444;"></span><span class="chart-legend-label">Xe tải</span><strong id="mix-truck">' + (mix.truck || 0) + '</strong></div>'
      + '</div></div></div>';

    initDonutChart();
    if (donutChart) {
      donutChart.data.datasets[0].data = [
        mix.car || 0,
        mix.motorcycle || 0,
        mix.bus || 0,
        mix.truck || 0,
      ];
      donutChart.update();
    }
  }

  function updateVehicleMixPanel(perClass, mix) {
    var total = (mix.car || 0) + (mix.motorcycle || 0) + (mix.bus || 0) + (mix.truck || 0);
    if (total > 0) {
      ensureDonutChartPanel(mix);
    }
    var el;
    el = document.getElementById('mix-automobile'); if (el) el.textContent = mix.car;
    el = document.getElementById('mix-motorcycle'); if (el) el.textContent = mix.motorcycle;
    el = document.getElementById('mix-bus'); if (el) el.textContent = mix.bus;
    el = document.getElementById('mix-truck'); if (el) el.textContent = mix.truck;

    if (donutChart) {
      donutChart.data.datasets[0].data = [
        mix.car || 0,
        mix.motorcycle || 0,
        mix.bus || 0,
        mix.truck || 0,
      ];
      donutChart.update('none');
    }
    var center = document.getElementById('donut-center');
    if (center) {
      var totalEl = center.querySelector('div');
      if (totalEl) {
        totalEl.textContent = total;
      }
    }
  }

  function ensureHourlyChartPanel() {
    if (document.getElementById('hourly-chart')) return;
    var content = document.getElementById('hourly-content');
    if (!content) return;

    content.innerHTML = '<div style="position: relative; width: 100%; height: 220px;"><canvas id="hourly-chart"></canvas></div>'
      + '<p class="muted" style="margin-top: 12px; font-size: 13px;" id="peak-hour-text"></p>';
  }

  function initHourlyChartWithData(labels, values) {
    var canvas = document.getElementById('hourly-chart');
    if (!canvas) return;
    var ctx = canvas.getContext('2d');
    hourlyChart = new Chart(ctx, _hourlyChartConfig(ctx, labels, values));
  }

  function updateHourlyActivity(hourlyData, maxCount) {
    if (!hourlyData || hourlyData.length === 0) return;

    var labels = hourlyData.map(function (item) { return item.hour + ':00'; });
    var values = hourlyData.map(function (item) { return item.count; });

    if (hourlyChart) {
      hourlyChart.data.labels = labels;
      hourlyChart.data.datasets[0].data = values;
      hourlyChart.update('none');
    } else {
      ensureHourlyChartPanel();
      initHourlyChartWithData(labels, values);
    }

    var peakHour = '';
    var peakCount = 0;
    hourlyData.forEach(function (item) {
      if (item.count > peakCount) { peakCount = item.count; peakHour = item.hour + ':00'; }
    });
    var peakEl = document.getElementById('peak-hour-text');
    if (peakEl && peakHour) {
      peakEl.textContent = 'Khung giờ cao điểm hôm nay: ' + peakHour;
    }
  }

  function updateLatestSession(session) {
    if (!session) return;
    var content = document.getElementById("latest-session-content");
    if (!content) return;

    var statusLabels = {
      completed: "Hoàn thành",
      running: "Đang chạy",
      queued: "Đang chờ",
      failed: "Thất bại",
      stopped: "Đã dừng",
    };
    var statusLabel = statusLabels[session.status] || session.status;
    var summary = session.summary || {};
    var perClass = summary.per_class || {};
    var mix = session.vehicle_mix || getVehicleMix(perClass);
    var total = (typeof summary.total === "number") ? summary.total : 0;

    var html = '<div class="session-summary">';
    html += '<div class="session-summary-row"><span class="muted">Phiên #' + session.id + '</span><span class="pill status-' + session.status + '">' + statusLabel + '</span></div>';
    html += '<div class="session-summary-row"><span class="muted">Video</span><span>' + (session.source_name || "—") + '</span></div>';
    html += '<div class="session-summary-row"><span class="muted">Tổng số xe</span><span><strong>' + total + '</strong></span></div>';
    html += '<div class="session-summary-row"><span class="muted">Ô tô</span><span>' + (mix.car || 0) + '</span></div>';
    html += '<div class="session-summary-row"><span class="muted">Xe máy</span><span>' + mix.motorcycle + '</span></div>';
    html += '<div class="session-summary-row"><span class="muted">Bắt đầu</span><span>' + (session.started_at || "—") + '</span></div>';
    if (session.finished_at) {
      html += '<div class="session-summary-row"><span class="muted">Kết thúc</span><span>' + session.finished_at + '</span></div>';
    }
    if (perClass && Object.keys(perClass).length > 0) {
      html += '<div class="session-summary-row"><span class="muted">Chi tiết</span><span>';
      Object.keys(perClass).forEach(function (k) {
        html += '<span class="pill">' + k + ': ' + perClass[k] + '</span>';
      });
      html += '</span></div>';
    }
    if (session.error_message) {
      html += '<div class="alert alert-error">' + session.error_message + '</div>';
    }
    html += '</div>';

    content.innerHTML = html;
  }

  // ====================================================================
  // Live Detection Feed + Detection Rate Engine
  // ====================================================================
  var VEHICLE_META = {
    car: { icon: '🚗', label: 'Ô tô', badge: 'car' },
    motorcycle: { icon: '🏍️', label: 'Xe máy', badge: 'motorcycle' },
    bus: { icon: '🚌', label: 'Xe buýt', badge: 'bus' },
    truck: { icon: '🚛', label: 'Xe tải', badge: 'truck' },
  };
  var FEED_MAX_ITEMS = 50;
  var feedItems = [];           // Array of { type, icon, label, badge, time, ts }
  var prevLivePerClass = {};    // Previous poll per_class (to diff)
  var detectionTimestamps = []; // All detection timestamps for rate calc
  var liveStartTime = null;     // When live mode started
  var prevRatePerMin = null;    // For trend comparison
  var isLiveFeedActive = false;

  function showLiveFeedPanel() {
    var feedPanel = document.getElementById('live-feed-panel');
    var sessionPanel = document.getElementById('latest-session-content');
    var title = document.getElementById('bottom-panel-title');
    if (feedPanel) feedPanel.style.display = '';
    if (sessionPanel) sessionPanel.style.display = 'none';
    if (title) title.innerHTML = '<span class="live-dot-inline" style="margin-right: 6px;"></span>Phát hiện phương tiện trực tiếp';
    if (!isLiveFeedActive) {
      isLiveFeedActive = true;
      liveStartTime = Date.now();
      feedItems = [];
      detectionTimestamps = [];
      prevLivePerClass = {};
      prevRatePerMin = null;
    }
  }

  function hideLiveFeedPanel() {
    var feedPanel = document.getElementById('live-feed-panel');
    var sessionPanel = document.getElementById('latest-session-content');
    var title = document.getElementById('bottom-panel-title');
    if (feedPanel) feedPanel.style.display = 'none';
    if (sessionPanel) sessionPanel.style.display = '';
    if (title) title.textContent = 'Phiên phân tích gần nhất';
    isLiveFeedActive = false;
  }

  function diffAndAddFeedItems(currentPerClass) {
    var now = Date.now();
    var timeStr = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    var newDetections = 0;

    Object.keys(currentPerClass).forEach(function (cls) {
      var curr = currentPerClass[cls] || 0;
      var prev = prevLivePerClass[cls] || 0;
      var diff = curr - prev;
      if (diff > 0) {
        var meta = VEHICLE_META[cls] || { icon: '🚙', label: cls, badge: 'car' };
        for (var i = 0; i < diff; i++) {
          feedItems.unshift({
            type: cls,
            icon: meta.icon,
            label: meta.label,
            badge: meta.badge,
            time: timeStr,
            ts: now,
          });
          detectionTimestamps.push(now);
          newDetections++;
        }
      }
    });

    if (feedItems.length > FEED_MAX_ITEMS) {
      feedItems = feedItems.slice(0, FEED_MAX_ITEMS);
    }

    prevLivePerClass = JSON.parse(JSON.stringify(currentPerClass));
    return newDetections;
  }

  function renderFeedList() {
    var list = document.getElementById('live-feed-list');
    if (!list) return;

    if (feedItems.length === 0) {
      list.innerHTML = '<div class="feed-empty">Đang chờ phát hiện phương tiện...</div>';
      return;
    }

    var html = '';
    feedItems.forEach(function (item) {
      html += '<div class="feed-item">'
        + '<span class="feed-item-icon">' + item.icon + '</span>'
        + '<span class="feed-item-label">' + item.label + '</span>'
        + '<span class="feed-item-badge ' + item.badge + '">' + item.label + '</span>'
        + '<span class="feed-item-time">' + item.time + '</span>'
        + '</div>';
    });
    list.innerHTML = html;
  }

  function updateDetectionRate(liveTotal) {
    var now = Date.now();
    detectionTimestamps = detectionTimestamps.filter(function (ts) {
      return (now - ts) < 120000;
    });

    var recentCount = detectionTimestamps.filter(function (ts) {
      return (now - ts) < 60000;
    }).length;

    var rateEl = document.getElementById('rate-per-min');
    if (rateEl) rateEl.textContent = recentCount;

    var arrowEl = document.getElementById('rate-trend-arrow');
    var trendTextEl = document.getElementById('rate-trend-text');
    if (prevRatePerMin !== null && arrowEl && trendTextEl) {
      var diff = recentCount - prevRatePerMin;
      if (diff > 0) {
        arrowEl.textContent = '↑';
        arrowEl.className = 'rate-trend-arrow up';
        trendTextEl.textContent = '+' + diff + ' so với phút trước';
      } else if (diff < 0) {
        arrowEl.textContent = '↓';
        arrowEl.className = 'rate-trend-arrow down';
        trendTextEl.textContent = diff + ' so với phút trước';
      } else {
        arrowEl.textContent = '→';
        arrowEl.className = 'rate-trend-arrow stable';
        trendTextEl.textContent = 'Ổn định';
      }
    } else if (recentCount > 0 && trendTextEl) {
      trendTextEl.textContent = 'Đang phát hiện xe...';
    }
    prevRatePerMin = recentCount;

    var elapsedEl = document.getElementById('rate-elapsed');
    if (elapsedEl && liveStartTime) {
      var elapsed = Math.floor((now - liveStartTime) / 1000);
      var mm = Math.floor(elapsed / 60).toString().padStart(2, '0');
      var ss = (elapsed % 60).toString().padStart(2, '0');
      elapsedEl.textContent = mm + ':' + ss;
    }

    var lastDetectEl = document.getElementById('rate-last-detect');
    if (lastDetectEl) {
      if (feedItems.length > 0) {
        lastDetectEl.textContent = feedItems[0].time;
      } else {
        lastDetectEl.textContent = '—';
      }
    }

    var countEl = document.getElementById('feed-total-count');
    if (countEl) {
      countEl.textContent = liveTotal + ' xe';
    }
  }

  function processLiveFeed(livePerClass, liveTotal, isActive) {
    if (isActive) {
      showLiveFeedPanel();
      var newCount = diffAndAddFeedItems(livePerClass);
      if (newCount > 0) {
        renderFeedList();
      }
      updateDetectionRate(liveTotal);
    } else {
      if (isLiveFeedActive) {
        hideLiveFeedPanel();
      }
    }
  }


  function showLiveBanner(title, detail, total, car, moto) {
    var banner = document.getElementById("live-analysis-banner");
    if (banner) banner.style.display = "";
    var el;
    el = document.getElementById("live-banner-title"); if (el) el.textContent = title;
    el = document.getElementById("live-banner-detail"); if (el) el.textContent = detail;
    el = document.getElementById("live-total"); if (el) el.textContent = total;
    el = document.getElementById("live-car"); if (el) el.textContent = car;
    el = document.getElementById("live-moto"); if (el) el.textContent = moto;
  }

  function hideLiveBanner() {
    var banner = document.getElementById("live-analysis-banner");
    if (banner) banner.style.display = "none";
    var pill = document.getElementById("dashboard-status-pill");
    if (pill) pill.textContent = "Hệ thống đang sẵn sàng";
  }

  function refreshDashboardFromDB() {
    fetch("/api/dashboard", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        dbTodayTotal = data.today_total || 0;
        var mix = data.vehicle_mix || {};
        dbAutomobile = mix.car || 0;
        dbMotorcycle = mix.motorcycle || 0;
        dbBus = mix.bus || 0;
        dbTruck = mix.truck || 0;
        dbPerClass = data.per_class || {};

        updateStatCards(dbTodayTotal, {car: dbAutomobile, motorcycle: dbMotorcycle });
        setStatCardLive(false);

        updateVehicleMixPanel(dbPerClass, mix);

        if (data.hourly_activity && data.hourly_activity.length > 0) {
          updateHourlyActivity(data.hourly_activity, data.max_hourly_count || 1);
        }

        if (data.latest_session) {
          updateLatestSession(data.latest_session);
        }

        var sessEl = document.getElementById("stat-sessions-today");
        if (sessEl) sessEl.textContent = data.completed_sessions_today || 0;
      })
      .catch(function () {});
  }

  function _processPollResults(headless, stream, dbData) {
      var headlessActive = false;
      var streamActive = false;
      var livePerClass = {};
      var liveTotal = 0;
      var bannerTitle = "";
      var bannerDetail = "";

      if (headless && headless.active_session_id && headless.live_state) {
        var ls = headless.live_state;
        if (ls.status === "running" || ls.status === "queued") {
          headlessActive = true;
          var summary = ls.summary || {};
          livePerClass = summary.per_class || {};
          liveTotal = (typeof summary.total === "number") ? summary.total : 0;
          bannerTitle = "Đang phân tích: " + (ls.source_name || "video");
          bannerDetail = "Phiên phân tích headless — dữ liệu cập nhật real-time";

          var pill = document.getElementById("dashboard-status-pill");
          if (pill) pill.innerHTML = '<span class="live-dot-inline"></span> Đang phân tích phiên #' + headless.active_session_id;
        }
      }

      if (stream && stream.has_active_stream) {
        streamActive = true;
        if (headlessActive) {
          bannerDetail = "Đang chạy phân tích + stream trực tiếp";
        } else {
          bannerTitle = "🎥 Stream trực tiếp đang chạy";
          bannerDetail = stream.stream_count + " luồng camera — dữ liệu cập nhật real-time";

          var pill2 = document.getElementById("dashboard-status-pill");
          if (pill2) pill2.innerHTML = '<span class="live-dot-inline"></span> Stream trực tiếp đang hoạt động';
        }
      }

      var isAnyActive = headlessActive || streamActive;

      // ============================================================
      // Always use DB data for stat cards (single source of truth)
      // ============================================================
      if (dbData) {
        var todayTotal = dbData.db_today_total || 0;
        var todayPerClass = dbData.db_today_per_class || {};
        var todayMix = getVehicleMix(todayPerClass);

        // Update today stat cards
        updateStatCards(todayTotal, todayMix);
        setStatCardLive(isAnyActive);

        // Update donut chart + legend
        updateVehicleMixPanel(todayPerClass, todayMix);

        // Update hourly chart
        var hourlyData = dbData.db_hourly_activity || [];
        if (hourlyData.length > 0) {
          // Build full labels 06-23
          var fullLabels = [];
          var fullValues = [];
          var hourMap = {};
          hourlyData.forEach(function (item) { hourMap[item.hour] = item.count; });
          for (var h = 6; h <= 23; h++) {
            var hkey = h.toString().padStart(2, '0');
            fullLabels.push(hkey + ':00');
            fullValues.push(hourMap[hkey] || 0);
          }

          if (hourlyChart) {
            hourlyChart.data.labels = fullLabels;
            hourlyChart.data.datasets[0].data = fullValues;
            hourlyChart.update('none');
          } else {
            ensureHourlyChartPanel();
            initHourlyChartWithData(fullLabels, fullValues);
          }

          // Update peak hour text
          var peakHour = '';
          var peakCount = 0;
          hourlyData.forEach(function (item) {
            if (item.count > peakCount) { peakCount = item.count; peakHour = item.hour + ':00'; }
          });
          var peakEl = document.getElementById('peak-hour-text');
          if (peakEl && peakHour) {
            peakEl.textContent = 'Khung giờ cao điểm hôm nay: ' + peakHour;
          }
        }

        // Update all-time stat cards
        var alltimeTotal = dbData.db_alltime_total || 0;
        var alltimePerClass = dbData.db_alltime_per_class || {};
        var alltimeMix = getVehicleMix(alltimePerClass);
        var el;
        el = document.getElementById("stat-alltime-total"); if (el) el.textContent = alltimeTotal;
        // Update all-time class cards (the gradient cards)
        var alltimeCards = document.querySelectorAll('.card-grid .stat-card');
        // We have 4 alltime cards — try to update by index if they exist in the alltime section
        var alltimeSection = document.getElementById('stat-alltime-total');
        if (alltimeSection) {
          var parent = alltimeSection.closest('.card-grid');
          if (parent) {
            var cards = parent.querySelectorAll('.stat-value');
            if (cards.length >= 4) {
              cards[0].textContent = alltimeTotal;
              cards[1].textContent = alltimeMix.car || 0;
              cards[2].textContent = alltimeMix.motorcycle || 0;
              cards[3].textContent = (alltimeMix.truck || 0) + (alltimeMix.bus || 0);
            }
          }
        }

        // Update sessions count
        var sessEl = document.getElementById("stat-sessions-today");
        // Keep it as-is (no DB data for this in WS, it's less critical)
      }

      if (isAnyActive) {
        // Merge live per_class for feed detection (live stream + headless)
        var mergedLive = {};
        if (headlessActive) mergedLive = mergePerClass(mergedLive, livePerClass);
        if (streamActive && stream) mergedLive = mergePerClass(mergedLive, stream.per_class || {});

        var liveT = (headlessActive ? liveTotal : 0) + (streamActive && stream ? (stream.total || 0) : 0);

        showLiveBanner(bannerTitle, bannerDetail,
          dbData ? (dbData.db_today_total || 0) : liveT,
          dbData ? getVehicleMix(dbData.db_today_per_class || {}).automobile : 0,
          dbData ? getVehicleMix(dbData.db_today_per_class || {}).motorcycle : 0
        );
        processLiveFeed(mergedLive, liveT, true);

      } else {
        hideLiveBanner();
        setStatCardLive(false);
        processLiveFeed({}, 0, false);

        if (wasHeadlessRunning || wasStreamActive) {
          // After stopping, do a full DB refresh to get latest session etc.
          setTimeout(refreshDashboardFromDB, 2000);
        }
      }

      wasHeadlessRunning = headlessActive;
      wasStreamActive = streamActive;
  }


  function pollAll() {
    var pHeadless = fetch("/api/monitoring/live-state", { credentials: "same-origin" }).then(function (r) { return r.json(); }).catch(function () { return null; });
    var pStream = fetch("/api/stream/active-stats", { credentials: "same-origin" }).then(function (r) { return r.json(); }).catch(function () { return null; });
    var pDashboard = fetch("/api/dashboard", { credentials: "same-origin" }).then(function (r) { return r.json(); }).catch(function () { return null; });

    Promise.all([pHeadless, pStream, pDashboard]).then(function (results) {
      var dashData = results[2];
      var dbData = null;
      if (dashData) {
        dbData = {
          db_today_total: dashData.today_total || 0,
          db_today_per_class: dashData.per_class || {},
          db_alltime_total: dashData.alltime_total || 0,
          db_alltime_per_class: dashData.alltime_per_class || {},
          db_hourly_activity: dashData.hourly_activity || [],
        };
      }
      _processPollResults(results[0], results[1], dbData);
    });
  }

  // ====================================================================
  // WebSocket connection — replaces setInterval(pollAll, POLL_MS)
  // ====================================================================

  var _dashboardWS = null;
  var _wsReconnectTimer = null;

  function _handleDashboardMessage(data) {
    // Rebuild the two-source structure pollAll() expected
    var headlessPayload = null;
    var streamPayload = null;

    if (data.live_state || data.active_session_id) {
      headlessPayload = { active_session_id: data.active_session_id, live_state: data.live_state };
    }
    if (data.stream_stats) {
      streamPayload = data.stream_stats;
    }

    // Pass DB data from WS payload
    var dbData = {
      db_today_total: data.db_today_total || 0,
      db_today_per_class: data.db_today_per_class || {},
      db_alltime_total: data.db_alltime_total || 0,
      db_alltime_per_class: data.db_alltime_per_class || {},
      db_hourly_activity: data.db_hourly_activity || [],
    };

    _processPollResults(headlessPayload, streamPayload, dbData);
  }

  function connectDashboardWS() {
    if (_dashboardWS && (_dashboardWS.readyState === WebSocket.OPEN || _dashboardWS.readyState === WebSocket.CONNECTING)) {
      return;
    }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/ws/dashboard");
    _dashboardWS = ws;

    ws.onmessage = function (event) {
      try { _handleDashboardMessage(JSON.parse(event.data)); } catch (e) {}
    };

    ws.onclose = function () {
      _wsReconnectTimer = setTimeout(connectDashboardWS, 2000);
    };

    ws.onerror = function () { ws.close(); };
  }

  // Start polling (initial data on page load + WebSocket + periodic fallback)
  if (document.getElementById('dashboard-stats')) {
    pollAll();   // one-time initial load
    connectDashboardWS();
    // Periodic fallback: poll every 2s to ensure sync even if WS drops
    setInterval(pollAll, 2000);
  }

  // Listen for language changes to recreate charts with new labels
  window.addEventListener("langchanged", function () {
    if (donutChart) {
      donutChart.destroy();
      donutChart = null;
    }
    if (hourlyChart) {
      hourlyChart.destroy();
      hourlyChart = null;
    }
    if (document.getElementById('donut-chart')) initDonutChart();
    if (document.getElementById('hourly-chart')) initHourlyChart();
  });
})();
