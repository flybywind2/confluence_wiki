(() => {
  const panel = document.getElementById("admin-sync-jobs");
  const summary = document.getElementById("admin-sync-queue-summary");
  const runningList = document.getElementById("admin-sync-running-list");
  const queuedList = document.getElementById("admin-sync-queued-list");
  const recentList = document.getElementById("admin-sync-recent-list");
  const triggers = Array.from(document.querySelectorAll('[data-admin-sync-trigger="true"]'));

  if (!panel || !summary || !runningList || !queuedList || !recentList || triggers.length === 0) {
    return;
  }

  let pollTimer = null;

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

  const hasActiveJobs = (overview) => Boolean(overview?.running || (overview?.queued || []).length);

  const renderOverview = (overview) => {
    const counts = overview?.counts || {};
    const runningCount = Number(counts.running || 0);
    const queuedCount = Number(counts.queued || 0);
    summary.textContent = runningCount || queuedCount
      ? `실행 중 ${runningCount}건 · 대기 ${queuedCount}건`
      : "현재 대기열이 없습니다.";

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
