(() => {
  const panel = document.getElementById("admin-sync-jobs");
  const summary = document.getElementById("admin-sync-queue-summary");
  const currentPanel = document.getElementById("admin-sync-current");
  const currentTitle = document.getElementById("admin-sync-current-title");
  const currentStatus = document.getElementById("admin-sync-current-status");
  const progressFill = document.getElementById("admin-sync-progress-fill");
  const progressLabel = document.getElementById("admin-sync-progress-label");
  const cancelButton = document.getElementById("admin-sync-cancel");
  const eventsList = document.getElementById("admin-sync-events");
  const runningList = document.getElementById("admin-sync-running-list");
  const queuedList = document.getElementById("admin-sync-queued-list");
  const recentList = document.getElementById("admin-sync-recent-list");
  const triggers = Array.from(document.querySelectorAll('[data-admin-sync-trigger="true"]'));

  if (
    !panel ||
    !summary ||
    !currentPanel ||
    !currentTitle ||
    !currentStatus ||
    !progressFill ||
    !progressLabel ||
    !cancelButton ||
    !eventsList ||
    !runningList ||
    !queuedList ||
    !recentList ||
    triggers.length === 0
  ) {
    return;
  }

  let pollTimer = null;
  let currentRunningJobId = null;

  const stopPolling = () => {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const renderBucket = (container, jobs, emptyMessage) => {
    container.innerHTML = "";
    if (!jobs || jobs.length === 0) {
      const item = document.createElement("li");
      item.className = "empty-state";
      item.textContent = emptyMessage;
      container.appendChild(item);
      return;
    }
    for (const job of jobs) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = job.query || job.space_key || "작업";
      item.appendChild(title);

      const meta = document.createElement("span");
      meta.className = "admin-sync-job-meta";
      const parts = [job.job_type_label || "", `${Number(job.progress || 0)}%`];
      if (job.queue_position && job.queue_position > 0) {
        parts.push(`${job.queue_position}번째`);
      }
      meta.textContent = parts.join(" · ");
      item.appendChild(meta);

      const message = document.createElement("span");
      message.className = "admin-sync-job-message";
      message.textContent = job.error || job.message || "";
      item.appendChild(message);

      container.appendChild(item);
    }
  };

  const renderCurrentJob = (job) => {
    if (!job) {
      currentPanel.hidden = true;
      currentRunningJobId = null;
      cancelButton.hidden = true;
      cancelButton.disabled = false;
      cancelButton.textContent = "실행 취소";
      progressFill.style.width = "0%";
      progressLabel.textContent = "0%";
      currentStatus.textContent = "대기 중입니다.";
      eventsList.innerHTML = "";
      return;
    }

    currentPanel.hidden = false;
    currentRunningJobId = job.id || null;
    currentTitle.textContent = job.query || job.space_key || "실행 중인 작업";
    const progress = Number(job.progress || 0);
    progressFill.style.width = `${progress}%`;
    progressLabel.textContent = `${progress}%`;
    currentStatus.textContent = job.error || job.message || "처리 중입니다.";
    if (job.job_type === "bootstrap" || job.job_type === "incremental") {
      cancelButton.hidden = false;
      cancelButton.disabled = Boolean(job.cancel_requested);
      cancelButton.textContent = job.cancel_requested ? "취소 요청 중..." : "실행 취소";
    } else {
      cancelButton.hidden = true;
      cancelButton.disabled = false;
      cancelButton.textContent = "실행 취소";
    }
    eventsList.innerHTML = "";
    for (const event of job.events || []) {
      const item = document.createElement("li");
      const headline = document.createElement("strong");
      headline.textContent = event.message || "";
      item.appendChild(headline);

      const meta = document.createElement("span");
      meta.className = "admin-sync-job-meta";
      const parts = [event.status || "", Number.isFinite(Number(event.progress)) ? `${event.progress}%` : ""];
      meta.textContent = parts.filter(Boolean).join(" · ");
      item.appendChild(meta);
      eventsList.appendChild(item);
    }
  };

  const hasActiveJobs = (overview) => Boolean(overview?.running || (overview?.queued || []).length);

  const renderOverview = (overview) => {
    const counts = overview?.counts || {};
    const runningCount = Number(counts.running || 0);
    const queuedCount = Number(counts.queued || 0);
    summary.textContent = runningCount || queuedCount
      ? `실행 중 ${runningCount}건 · 대기 ${queuedCount}건`
      : "현재 대기열이 없습니다.";

    renderCurrentJob(overview?.running || null);
    renderBucket(runningList, overview?.running ? [overview.running] : [], "실행 중인 작업이 없습니다.");
    renderBucket(queuedList, overview?.queued || [], "대기 중인 작업이 없습니다.");
    renderBucket(recentList, overview?.recent || [], "최근 작업이 없습니다.");
  };

  const fetchOverview = async () => {
    const response = await fetch("/api/query-jobs?types=bootstrap,incremental");
    const overview = await response.json();
    if (!response.ok) {
      throw new Error(overview.detail || "진행 상황을 불러오지 못했습니다.");
    }
    renderOverview(overview);
    return overview;
  };

  const schedulePoll = () => {
    stopPolling();
    pollTimer = window.setTimeout(async () => {
      try {
        const overview = await fetchOverview();
        if (hasActiveJobs(overview)) {
          schedulePoll();
        }
      } catch (_error) {
        schedulePoll();
      }
    }, 1200);
  };

  const submitSyncJob = async (form) => {
    const mode = form.dataset.jobMode || "";
    const spaceKey = form.dataset.spaceKey || "";
    const rootPageId = form.dataset.rootPageId || "";
    try {
      const response = await fetch("/api/query-jobs/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          space_key: spaceKey,
          root_page_id: rootPageId || null,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "작업 시작에 실패했습니다.");
      }
      const overview = await fetchOverview();
      if (hasActiveJobs(overview)) {
        schedulePoll();
      }
    } catch (error) {
      summary.textContent = error.message || "작업 시작에 실패했습니다.";
    }
  };

  cancelButton.addEventListener("click", async () => {
    if (!currentRunningJobId || cancelButton.disabled) {
      return;
    }
    cancelButton.disabled = true;
    cancelButton.textContent = "취소 요청 중...";
    try {
      const response = await fetch(`/api/query-jobs/${currentRunningJobId}/cancel`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "작업 취소에 실패했습니다.");
      }
      const overview = await fetchOverview();
      if (hasActiveJobs(overview)) {
        schedulePoll();
      }
    } catch (error) {
      cancelButton.disabled = false;
      cancelButton.textContent = "실행 취소";
      summary.textContent = error.message || "작업 취소에 실패했습니다.";
    }
  });

  for (const form of triggers) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitSyncJob(form);
    });
  }

  fetchOverview().then((overview) => {
    if (hasActiveJobs(overview)) {
      schedulePoll();
    }
  }).catch(() => {});
})();
