(function () {
  // ========== LIVE STREAM VARIABLES ==========
  var liveStreamImg = document.getElementById("live-stream-img");
  var liveBadge = document.getElementById("live-badge");
  var startLiveBtn = document.getElementById("start-live-btn");
  var stopLiveBtn = document.getElementById("stop-live-btn");
  var isLiveStreaming = false;
  var liveStreamSourceId = null;
  var liveStatsPollTimer = null;
  var streamRetryCount = 0;
  var streamRetryMax = 8;
  var streamRetryTimer = null;
  var focusPlayer = document.getElementById("focus-player");
  var selectedVideoName = document.getElementById("selected-video-name");
  var selectedRoiStatus = document.getElementById("selected-roi-status");
  var editRoiLink = document.getElementById("edit-roi-link");
  var latestSessionStatus = document.getElementById("latest-session-status");
  var latestSessionSource = document.getElementById("latest-session-source");
  var latestResultNote = document.getElementById("latest-result-note");
  var latestTotalCount = document.getElementById("latest-total-count");
  var latestCarCount = document.getElementById("latest-car-count");
  var latestMotorcycleCount = document.getElementById("latest-motorcycle-count");
  var focusTotalCount = document.getElementById("focus-total-count");
  var focusCarCount = document.getElementById("focus-car-count");
  var focusMotorcycleCount = document.getElementById("focus-motorcycle-count");
  var tiles = Array.prototype.slice.call(document.querySelectorAll(".monitor-video-tile"));
  var libraryItems = Array.prototype.slice.call(document.querySelectorAll(".monitor-library-item"));
  var isProcessedView = false;
  var currentInputVideoUrl = "";
  var currentVideoName = "";
  var currentSourceId = null;
  var liveStatePollTimer = null;
  var lastCompleted = null;

  // ========== TRAFFIC DENSITY TRACKER ==========
  var densityHistory = [];        // array of {timestamp, total}
  var DENSITY_WINDOW_MS = 5000;   // 5-second sliding window
  var DENSITY_THRESH_LOW = 2;     // < 2 vehicles/5s = Thưa thớt
  var DENSITY_THRESH_HIGH = 5;    // > 5 vehicles/5s = Đông phương tiện

  function updateTrafficDensity(currentTotal) {
    var now = Date.now();
    densityHistory.push({ timestamp: now, total: currentTotal });
    // Purge old entries outside the sliding window
    while (densityHistory.length > 0 && densityHistory[0].timestamp < now - DENSITY_WINDOW_MS) {
      densityHistory.shift();
    }
    var indicator = document.getElementById("traffic-density-indicator");
    var textEl = document.getElementById("traffic-density-text");
    if (!indicator || !textEl) return;

    if (densityHistory.length < 2) {
      // Not enough data yet
      indicator.className = "traffic-density analyzing";
      textEl.textContent = "Đang phân tích...";
      return;
    }

    // Calculate rate: vehicles added in the window
    var oldest = densityHistory[0];
    var newest = densityHistory[densityHistory.length - 1];
    var vehiclesInWindow = newest.total - oldest.total;
    if (vehiclesInWindow < 0) vehiclesInWindow = 0;

    var level, label;
    if (vehiclesInWindow > DENSITY_THRESH_HIGH) {
      level = "heavy";
      label = "🔴 Đông phương tiện";
    } else if (vehiclesInWindow >= DENSITY_THRESH_LOW) {
      level = "normal";
      label = "🟡 Bình thường";
    } else {
      level = "light";
      label = "🟢 Thưa thớt";
    }
    indicator.className = "traffic-density " + level;
    textEl.textContent = label;
  }

  function resetTrafficDensity() {
    densityHistory = [];
    var indicator = document.getElementById("traffic-density-indicator");
    var textEl = document.getElementById("traffic-density-text");
    if (indicator) indicator.className = "traffic-density idle";
    if (textEl) textEl.textContent = "...";
  }

  function getVehicleSummary(summary) {
    var perClass = (summary && summary.per_class) || {};
    var totalFromSummary = (summary && typeof summary.total === "number") ? summary.total : 0;
    var totalFromPerClass = Object.keys(perClass).reduce(function (acc, key) {
      return acc + (perClass[key] || 0);
    }, 0);
    var total = totalFromSummary || totalFromPerClass;
    return {
      total: total,
      automobile: (perClass.car || 0) + (perClass.truck || 0) + (perClass.bus || 0),
      motorcycle: perClass.motorcycle || 0
    };
  }

  // ========== DIRECTION + FLOW RATE HELPERS ==========
  function updateDirectionCounts(data, prefix) {
    // prefix = "focus" (khung xem) hoặc "latest" (kết quả)
    var p = prefix || "focus";
    var dirs = data && data.directions;
    var diEl  = document.getElementById(p + "-di-count");
    var veEl  = document.getElementById(p + "-ve-count");
    var diStat = document.getElementById(p === "focus" ? "focus-di-stat" : "result-di-stat");
    var veStat = document.getElementById(p === "focus" ? "focus-ve-stat" : "result-ve-stat");
    if (!dirs) {
      if (diStat) diStat.style.display = "none";
      if (veStat) veStat.style.display = "none";
      return;
    }
    if (diStat) diStat.style.display = "";
    if (veStat) veStat.style.display = "";
    if (diEl)  diEl.textContent  = (dirs.di  && dirs.di.total)  || 0;
    if (veEl)  veEl.textContent  = (dirs.ve  && dirs.ve.total)  || 0;
  }

  function updateFlowRate(data, prefix) {
    var p = prefix || "focus";
    var frEl   = document.getElementById(p === "focus" ? "focus-flowrate" : "latest-flowrate");
    var frStat = document.getElementById(p === "focus" ? "focus-flowrate-stat" : "result-flowrate-stat");
    var vph = data && data.flow_rate_vph;
    if (!frStat) return;
    if (typeof vph === "number") {
      frStat.style.display = "";
      if (frEl) frEl.textContent = vph + " xe/gi\u1edd";
    } else {
      frStat.style.display = "none";
    }
  }

  function hideDirectionStats() {
    ["focus-di-stat", "focus-ve-stat", "focus-flowrate-stat",
     "result-di-stat", "result-ve-stat", "result-flowrate-stat"].forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = "none";
    });
  }

  function updateFocusCounts(summary) {
    var counts = getVehicleSummary(summary || {});
    if (focusTotalCount) focusTotalCount.textContent = counts.total;
    if (focusCarCount) focusCarCount.textContent = counts.automobile;
    if (focusMotorcycleCount) focusMotorcycleCount.textContent = counts.motorcycle;
  }

  function setFocusMode(label, note) {
    var modeEl = document.getElementById("focus-player-mode");
    var noteEl = document.getElementById("focus-player-note");
    if (modeEl) modeEl.textContent = label;
    if (noteEl) noteEl.textContent = note;
  }

  function updateResultCounts(summary) {
    var counts = getVehicleSummary(summary || {});
    if (latestTotalCount) latestTotalCount.textContent = counts.total;
    if (latestCarCount) latestCarCount.textContent = counts.automobile;
    if (latestMotorcycleCount) latestMotorcycleCount.textContent = counts.motorcycle;
  }

  function setResultMeta(statusText, sourceName, noteText) {
    if (latestSessionStatus) latestSessionStatus.textContent = statusText;
    if (latestSessionSource) latestSessionSource.textContent = sourceName || "—";
    if (latestResultNote) {
      var noteStrong = latestResultNote.querySelector("strong");
      if (noteStrong) noteStrong.textContent = noteText;
    }
  }

  function resetToInputView() {
    isProcessedView = false;
    if (focusPlayer && currentInputVideoUrl) {
      focusPlayer.hidden = false;
      focusPlayer.style.display = "";
      focusPlayer.src = currentInputVideoUrl;
      focusPlayer.load();
      focusPlayer.play().catch(function () {});
    }
    
    var liveStreamWrapper = document.getElementById("live-stream-wrapper");
    if (liveStreamWrapper) liveStreamWrapper.style.display = "none";
    var liveBadge = document.getElementById("live-badge");
    if (liveBadge) liveBadge.hidden = true;

    setFocusMode("Video gốc", "Chạy phân tích để xem kết quả.");
    setResultMeta("Chưa xem kết quả", "—", "");
    updateResultCounts({});
    resetTrafficDensity();
    hideDirectionStats();
  }

  function fetchAndPlayOutputForName(sourceName, fallbackSummary) {
    if (!sourceName) return;
    fetch("/api/monitoring/vscode-output?video_name=" + encodeURIComponent(String(sourceName).replace(/\.[^.]+$/, "")), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (out) {
        if (out && out.has_output && out.video_url) {
          playOutputVideo({ url: out.video_url, display_name: sourceName, summary: out.summary || fallbackSummary || {} });
        } else if (fallbackSummary) {
          updateFocusCounts(fallbackSummary);
          updateResultCounts(fallbackSummary);
        }
      })
      .catch(function () {
        if (fallbackSummary) {
          updateFocusCounts(fallbackSummary);
          updateResultCounts(fallbackSummary);
        }
      });
  }

  function isEmptySummary(summary) {
    if (!summary) return true;
    var perClass = summary.per_class || {};
    var hasPerClass = Object.keys(perClass).some(function (k) { return (perClass[k] || 0) > 0; });
    var total = (typeof summary.total === "number") ? summary.total : 0;
    return total <= 0 && !hasPerClass;
  }

  function fetchSessionAndPlay(sessionId, fallbackSourceName, fallbackSummary) {
    if (!sessionId) return;
    fetch("/api/sessions/" + encodeURIComponent(String(sessionId)), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (sess) {
        if (!sess || sess.error) throw new Error("no session");
        var url = sess.media_url;
        var summary = sess.summary || fallbackSummary || {};
        var displayName = sess.source_name || fallbackSourceName || currentVideoName;
        if (url) {
          playOutputVideo({ url: url, display_name: displayName, summary: summary });
        } else if (displayName) {
          fetchAndPlayOutputForName(displayName, summary);
        } else {
          updateFocusCounts(summary);
          updateResultCounts(summary);
        }
      })
      .catch(function () {
        if (fallbackSourceName) {
          fetchAndPlayOutputForName(fallbackSourceName, fallbackSummary || {});
        } else if (fallbackSummary) {
          updateFocusCounts(fallbackSummary);
          updateResultCounts(fallbackSummary);
        }
      });
  }

  function updateSelection(videoPath, videoUrl, videoName, roiReady, sourceId, camIndex) {
    // Stop live stream when switching videos
    if (isLiveStreaming) {
      stopLiveStream();
    }
    currentInputVideoUrl = videoUrl;
    currentVideoName = videoName;
    currentSourceId = sourceId ? parseInt(sourceId, 10) : null;
    
    // Always start by showing the Original Video (Video gốc) to prevent black screens.
    resetToInputView();
    
    // If there is a completed session, restore its counts but DON'T override the video player
    if (lastCompleted && lastCompleted.source_id && currentSourceId === lastCompleted.source_id) {
        updateFocusCounts(lastCompleted.summary || {});
        updateResultCounts(lastCompleted.summary || {});
        setResultMeta("Đã phân tích gần đây", videoName, "Kết quả các xe đã đếm được từ lần xem trước.");
    }
    // Update CAM label
    var camLabel = document.getElementById("selected-cam-label");
    if (camLabel) camLabel.textContent = "CAM " + (camIndex || "1");
    if (selectedVideoName) selectedVideoName.textContent = videoName;
    if (selectedRoiStatus) {
      selectedRoiStatus.textContent = roiReady === "yes" ? "Đã cấu hình" : "Chưa cấu hình";
    }
    if (editRoiLink) editRoiLink.href = "/monitoring/edit-roi-for-video?path=" + encodeURIComponent(videoPath);
    var runAnalysisBtn = document.getElementById("run-analysis-btn");
    if (runAnalysisBtn) runAnalysisBtn.disabled = roiReady !== "yes" || !currentSourceId;
    // Enable/disable live stream button based on ROI
    var startLiveBtn = document.getElementById("start-live-btn");
    if (startLiveBtn) startLiveBtn.disabled = roiReady !== "yes" || !currentSourceId;
    
    // Switch preview player
    var liveStreamWrapper = document.getElementById("live-stream-wrapper");
    if (liveStreamImg && liveStreamWrapper) liveStreamWrapper.style.display = "none";
    if (liveBadge) liveBadge.hidden = true;

    if (!currentInputVideoUrl) {
      if (focusPlayer) {
        focusPlayer.hidden = true;
        focusPlayer.style.display = "none";
        focusPlayer.src = "";
      }
      var streamWarning = roiReady === "yes" 
          ? "👉 Bấm 'Xem trực tiếp' để bắt đầu AI." 
          : "👉 Bấm 'Chỉnh ROI' để vẽ vùng đếm trước khi chạy AI.";
      setFocusMode("Đã Chọn Luồng Camera", streamWarning);
    } else {
      var wrapper = document.getElementById("live-stream-wrapper");
      if (wrapper) wrapper.style.display = "none";
      if (liveStreamImg) liveStreamImg.src = "";
    }
  }

  function refreshStopButtonState() {
    fetch("/api/monitoring/status", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var stopBtn = document.getElementById("stop-analysis-btn");
        if (stopBtn) stopBtn.disabled = !data.active_session_id;
      })
      .catch(function () {});
  }

  // ========== WEBSOCKET LIVE STATE ==========
  var _monitoringWS = null;
  var _wsReconnectTimer = null;
  var _lastCompletedHandledSessionId = null;

  function _handleMonitoringMessage(data) {
    var live = data.live_state;
    var activeId = data.active_session_id;

    // Update stop button
    var stopBtn = document.getElementById("stop-analysis-btn");
    if (stopBtn) stopBtn.disabled = !activeId;

    if (!live) return;
    var summary = live.summary || {};

    if (live.status === "running" || live.status === "queued") {
      updateFocusCounts(summary);
      updateResultCounts(summary);
      setResultMeta("Đang chạy phân tích", live.source_name || currentVideoName, "");
      var counts = getVehicleSummary(summary);
      updateTrafficDensity(counts.total);

    } else if (live.status === "completed") {
      updateFocusCounts(summary);
      updateResultCounts(summary);
      setResultMeta("Phân tích hoàn thành", live.source_name || currentVideoName, "");
      var completedCounts = getVehicleSummary(summary);
      updateTrafficDensity(completedCounts.total);

      // Only trigger video playback once per completed session
      if (live.session_id && _lastCompletedHandledSessionId !== live.session_id) {
        _lastCompletedHandledSessionId = live.session_id;
        lastCompleted = {
          source_id: live.source_id,
          source_name: live.source_name || currentVideoName,
          summary: summary
        };
        var runBtn = document.getElementById("run-analysis-btn");
        if (runBtn) { runBtn.disabled = false; runBtn.textContent = "Chạy phân tích"; }
        fetchSessionAndPlay(live.session_id, live.source_name || currentVideoName, summary);
      } else if (!live.session_id && live.output_video_path) {
        lastCompleted = { source_id: live.source_id, source_name: live.source_name || currentVideoName, summary: summary };
        fetchAndPlayOutputForName(live.source_name || currentVideoName, summary);
      }

    } else if (live.status === "stopped" || live.status === "cancelled") {
      updateFocusCounts(summary);
      updateResultCounts(summary);
      setResultMeta("Đã dừng phân tích", live.source_name || currentVideoName, "Phiên đã dừng. Bạn có thể chạy lại khi cần.");
      var runBtn2 = document.getElementById("run-analysis-btn");
      if (runBtn2) { runBtn2.disabled = false; runBtn2.textContent = "Chạy phân tích"; }

    } else if (live.status === "failed") {
      updateFocusCounts(summary);
      updateResultCounts(summary);
      setResultMeta("Đã dừng phân tích", live.source_name || currentVideoName, live.error_message || "Phiên gặp lỗi và đã dừng.");
      var runBtn3 = document.getElementById("run-analysis-btn");
      if (runBtn3) { runBtn3.disabled = false; runBtn3.textContent = "Chạy phân tích"; }
    }
  }

  function connectMonitoringWS() {
    if (_monitoringWS && (_monitoringWS.readyState === WebSocket.OPEN || _monitoringWS.readyState === WebSocket.CONNECTING)) {
      return;
    }
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var ws = new WebSocket(proto + "//" + location.host + "/ws/monitoring");
    _monitoringWS = ws;

    ws.onmessage = function (event) {
      try { _handleMonitoringMessage(JSON.parse(event.data)); } catch (e) {}
    };

    ws.onclose = function () {
      _wsReconnectTimer = setTimeout(connectMonitoringWS, 2000);
    };

    ws.onerror = function () { ws.close(); };
  }

  // Stubs for backward-compat (startAnalysis still calls stopLiveStatePoll)
  function stopLiveStatePoll() { /* no-op: WebSocket handles updates */ }
  function pollLiveState() { /* no-op: WebSocket handles updates */ }

  function startAnalysis() {
    if (!currentSourceId) {
      alert("Chưa chọn video hoặc video chưa có trong nguồn.");
      return;
    }
    var runBtn = document.getElementById("run-analysis-btn");
    if (runBtn) { runBtn.disabled = true; runBtn.textContent = "Đang chạy..."; }
    fetch("/api/monitoring/start-with-video", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ source_id: currentSourceId })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          var msg = data.error;
          if (data.error.indexOf("đang chạy") !== -1) {
            msg = "Đang có phiên phân tích chạy. Bấm \"Dừng phân tích\" để dừng trước khi chạy video mới.";
          }
          alert(msg);
          if (runBtn) { runBtn.disabled = false; runBtn.textContent = "Chạy phân tích"; }
          refreshStopButtonState();
          return;
        }
        setResultMeta("Đang chạy phân tích", data.source_name || currentVideoName, "Đang xử lý video, vui lòng đợi.");
        // WebSocket sẽ tự động nhận cập nhật — không cần setInterval nữa
      })
      .catch(function () {
        alert("Không thể bắt đầu phân tích.");
        if (runBtn) { runBtn.disabled = false; runBtn.textContent = "Chạy phân tích"; }
      });
  }

  function setSelectedTile(tile) {
    if (!tile || !focusPlayer) return;
    tiles.forEach(function (item) { item.classList.remove("is-selected"); });
    tile.classList.add("is-selected");
    var videoUrl = tile.getAttribute("data-video-url");
    var videoName = tile.getAttribute("data-video-name");
    var videoPath = tile.getAttribute("data-video-path");
    var roiReady = tile.getAttribute("data-video-roi");
    var sourceId = tile.getAttribute("data-source-id");
    var camIndex = tile.getAttribute("data-cam-index") || "1";
    updateSelection(videoPath, videoUrl, videoName, roiReady, sourceId, camIndex);
  }

  tiles.forEach(function (tile) {
    tile.addEventListener("click", function () { setSelectedTile(tile); });
  });

  libraryItems.forEach(function (item) {
    item.addEventListener("click", function () {
      var videoPath = item.getAttribute("data-video-path");
      var videoUrl = item.getAttribute("data-video-url");
      var videoName = item.getAttribute("data-video-name");
      var roiReady = item.getAttribute("data-video-roi");
      var sourceId = item.getAttribute("data-source-id");
      var camIndex = item.getAttribute("data-cam-index") || "1";
      updateSelection(videoPath, videoUrl, videoName, roiReady, sourceId, camIndex);
      var matchingTile = tiles.find(function (t) { return t.getAttribute("data-video-path") === videoPath; });
      if (matchingTile) {
        tiles.forEach(function (t) { t.classList.remove("is-selected"); });
        matchingTile.classList.add("is-selected");
      }
    });
  });

  function playOutputVideo(item) {
    isProcessedView = true;
    if (focusPlayer) {
      focusPlayer.hidden = false;
      focusPlayer.style.display = "";
    }
    focusPlayer.src = item.url;
    focusPlayer.load();
    focusPlayer.play().catch(function () {});
    setFocusMode("Video đã xử lý", "Mỗi xe trên video tương ứng với số đếm bên cạnh.");
    setResultMeta("Đã hoàn tất", item.display_name, "Đang giữ kết quả đếm cuối cùng. Chỉ reset khi đổi video hoặc refresh trang.");
    updateFocusCounts(item.summary || {});
    updateResultCounts(item.summary || {});
  }

  var runAnalysisBtn = document.getElementById("run-analysis-btn");
  if (runAnalysisBtn) runAnalysisBtn.addEventListener("click", function () { startAnalysis(); });



  var stopAnalysisBtn = document.getElementById("stop-analysis-btn");
  if (stopAnalysisBtn) {
    stopAnalysisBtn.addEventListener("click", function () {
      stopAnalysisBtn.disabled = true;
      fetch("/api/monitoring/stop", { method: "POST", credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function () {
          stopLiveStatePoll();
          var runBtn = document.getElementById("run-analysis-btn");
          if (runBtn) { runBtn.disabled = false; runBtn.textContent = "Chạy phân tích"; }
          refreshStopButtonState();
          setResultMeta("Đã dừng phân tích", currentVideoName, "Phiên đã dừng. Bạn có thể chạy lại khi cần.");
        })
        .catch(function () { refreshStopButtonState(); });
    });
  }

  var deleteVideoBtn = document.getElementById("delete-video-btn");
  if (deleteVideoBtn) {
    deleteVideoBtn.addEventListener("click", function () {
      if (!currentSourceId) return;
      if (!confirm("Bạn có chắc chắn muốn xóa video này?")) return;
      deleteVideoBtn.disabled = true;
      deleteVideoBtn.textContent = "Đang xóa...";
      fetch("/api/sources/" + currentSourceId, { method: "DELETE", credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function () { window.location.reload(); })
        .catch(function () { window.location.reload(); });
    });
  }

  refreshStopButtonState();

  function hydrateFromLiveState() {
    // One-time fetch on page load to restore UI state — ongoing updates via WebSocket
    var pLiveState = fetch("/api/monitoring/live-state", { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .catch(function () { return {}; });

    pLiveState.then(function (data) {
      var live = data.live_state || null;
      var activeId = data.active_session_id;

      if (live) {
        var status = live.status || "";
        var summary = live.summary || {};
        var sourceName = live.source_name || currentVideoName || "Phiên đang chạy";

        var matchingTile = null;
        if (typeof live.source_id === "number") {
          matchingTile = tiles.find(function (t) {
            var sid = t.getAttribute("data-source-id");
            return sid && parseInt(sid, 10) === live.source_id;
          }) || null;
        }
        if (!matchingTile && live.source_name) {
          matchingTile = tiles.find(function (t) {
            return t.getAttribute("data-video-name") === live.source_name;
          }) || null;
        }
        if (matchingTile) {
          setSelectedTile(matchingTile);
        } else if (!currentVideoName && !activeId && tiles.length) {
          setSelectedTile(tiles[0]);
        }

        if (activeId && (status === "running" || status === "queued")) {
          var runBtn = document.getElementById("run-analysis-btn");
          var stopBtn = document.getElementById("stop-analysis-btn");
          if (runBtn) { runBtn.disabled = true; runBtn.textContent = "Đang chạy..."; }
          if (stopBtn) { stopBtn.disabled = false; }
          updateFocusCounts(summary);
          updateResultCounts(summary);
          setResultMeta("Đang chạy phân tích", sourceName, "Đang xử lý video, vui lòng đợi.");
          // WebSocket sẽ tiếp tục cập nhật real-time

        } else if (status === "completed") {
          updateFocusCounts(summary);
          updateResultCounts(summary);
          setResultMeta("Phân tích hoàn thành", sourceName, "Phân tích xong. Kết quả hiển thị bên dưới.");
          lastCompleted = { source_id: live.source_id, source_name: sourceName, summary: summary };
          if (live.session_id) {
            _lastCompletedHandledSessionId = live.session_id;
            fetchSessionAndPlay(live.session_id, sourceName, summary);
          } else if (!isEmptySummary(summary)) {
            fetchAndPlayOutputForName(sourceName, summary);
          } else {
            fetch("/api/sessions?limit=5", { credentials: "same-origin" })
              .then(function (r) { return r.json(); })
              .then(function (payload) {
                var sessions = (payload && payload.sessions) || [];
                var match = sessions.find(function (s) {
                  return s.status === "completed" && (typeof live.source_id === "number" ? s.source_id === live.source_id : true);
                }) || sessions.find(function (s) { return s.status === "completed"; }) || null;
                if (match && match.media_url) {
                  playOutputVideo({ url: match.media_url, display_name: match.source_name || sourceName, summary: match.summary || {} });
                } else if (match) {
                  fetchAndPlayOutputForName(match.source_name || sourceName, match.summary || {});
                }
              })
              .catch(function () {});
          }
        } else if (status === "stopped" || status === "cancelled") {
          updateFocusCounts(summary);
          updateResultCounts(summary);
          setResultMeta("Đã dừng phân tích", sourceName, "Phiên đã dừng. Bạn có thể chạy lại khi cần.");
        } else if (status === "failed") {
          updateFocusCounts(summary);
          updateResultCounts(summary);
          setResultMeta("Đã dừng phân tích", sourceName, live.error_message || "Phiên gặp lỗi và đã dừng.");
        }
      } else if (!currentVideoName && tiles.length) {
        setSelectedTile(tiles[0]);
      }
    });
  }

  hydrateFromLiveState();
  connectMonitoringWS();  // Start WebSocket for ongoing real-time updates


  function uploadFile(file) {
    if (!file || !file.name.match(/\.(mp4|avi|mov|mkv)$/i)) {
      alert("Chỉ hỗ trợ mp4, avi, mov, mkv");
      return;
    }
    var uploadProgress = document.getElementById("upload-progress");
    var uploadProgressBar = document.getElementById("upload-progress-bar");
    var uploadProgressLabel = document.getElementById("upload-progress-label");
    if (uploadProgress) uploadProgress.hidden = false;
    if (uploadProgressLabel) uploadProgressLabel.hidden = false;
    if (uploadProgressBar) uploadProgressBar.style.width = "0%";
    if (uploadProgressLabel) uploadProgressLabel.textContent = "Đang tải lên...";
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/sources/upload");
    xhr.upload.addEventListener("progress", function (event) {
      if (!event.lengthComputable) return;
      var percent = Math.round((event.loaded / event.total) * 100);
      if (uploadProgressBar) uploadProgressBar.style.width = percent + "%";
      if (uploadProgressLabel) uploadProgressLabel.textContent = "Đang tải lên " + percent + "%";
    });
    xhr.onload = function () {
      try {
        var data = JSON.parse(xhr.responseText);
        if (!data.ok) throw new Error(data.error || "Tải video thất bại.");
        uploadProgressLabel.textContent = "Tải xong. Đang làm mới giao diện...";
        window.location.reload();
      } catch (error) {
        if (uploadProgress) uploadProgress.hidden = true;
        if (uploadProgressLabel) uploadProgressLabel.hidden = true;
        alert(error.message || "Tải video thất bại.");
      }
    };
    xhr.onerror = function () {
      if (uploadProgress) uploadProgress.hidden = true;
      if (uploadProgressLabel) uploadProgressLabel.hidden = true;
      alert("Không thể tải video lên.");
    };
    var formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  }

  var dropZone = document.getElementById("drop-zone");
  var fileInput = document.getElementById("file-input");
  if (dropZone && fileInput) {
    dropZone.addEventListener("click", function () { fileInput.click(); });
    dropZone.addEventListener("dragover", function (e) { e.preventDefault(); dropZone.classList.add("is-over"); });
    dropZone.addEventListener("dragleave", function () { dropZone.classList.remove("is-over"); });
    dropZone.addEventListener("drop", function (e) {
      e.preventDefault();
      dropZone.classList.remove("is-over");
      if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) uploadFile(fileInput.files[0]);
    });
  }

  // RTSP Add Stream Logic
  var addStreamBtn = document.getElementById("add-stream-btn");
  var streamNameInput = document.getElementById("stream-name-input");
  var streamUrlInput = document.getElementById("stream-url-input");
  var streamErrorMsg = document.getElementById("stream-error-message");

  if (addStreamBtn) {
    addStreamBtn.addEventListener("click", function() {
      var name = streamNameInput.value.trim();
      var url = streamUrlInput.value.trim();

      if (!name || !url) {
        streamErrorMsg.textContent = "Vui lòng nhập tên nhận diện và đường dẫn RTSP/HTTP.";
        streamErrorMsg.style.display = "block";
        return;
      }

      addStreamBtn.disabled = true;
      addStreamBtn.textContent = "Đang thử...";
      streamErrorMsg.style.display = "none";

      fetch("/api/monitoring/add-stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ name: name, url: url })
      })
      .then(function(res) { return res.json(); })
      .then(function(data) {
        if (!data.ok) {
          throw new Error(data.error || "Gặp lỗi kết nối.");
        }
        // Success
        streamErrorMsg.style.color = "#10b981"; // green
        streamErrorMsg.textContent = data.message || "Kết nối thành công! Đang làm mới...";
        streamErrorMsg.style.display = "block";
        setTimeout(function() {
          window.location.reload();
        }, 800);
      })
      .catch(function(err) {
        streamErrorMsg.style.color = "#ef4444"; // red
        streamErrorMsg.textContent = err.message || "URL không hợp lý hoặc lỗi mạng.";
        streamErrorMsg.style.display = "block";
        addStreamBtn.disabled = false;
        addStreamBtn.textContent = "Kết nối";
      });
    });
  }

})();
