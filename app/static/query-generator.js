(() => {
  const openButton = document.getElementById("query-generator-open");
  const modal = document.getElementById("query-generator-modal");
  const backdrop = document.getElementById("query-generator-backdrop");
  const closeButton = document.getElementById("query-generator-close");
  const form = document.getElementById("query-generator-form");
  const input = document.getElementById("query-generator-input");
  const scope = document.getElementById("query-generator-scope");
  const inlineStatus = document.getElementById("query-generator-inline-status");
  const submitButton = document.getElementById("query-generator-submit");
  const progressBox = document.getElementById("query-generator-progress");
  const progressFill = document.getElementById("query-generator-progress-fill");
  const progressLabel = document.getElementById("query-generator-progress-label");
  const progressStatus = document.getElementById("query-generator-status");
  const eventsList = document.getElementById("query-generator-events");
  const resultLink = document.getElementById("query-generator-result");
  const queueSummary = document.getElementById("query-generator-queue-summary");
  const runningList = document.getElementById("query-generator-running-list");
  const queuedList = document.getElementById("query-generator-queued-list");
  const recentList = document.getElementById("query-generator-recent-list");
  const selectedSpace = document.body.dataset.selectedSpace || "all";
  const selectedSpaceName = document.body.dataset.selectedSpaceName || "전체 위키";

  if (
    !openButton ||
    !modal ||
    !backdrop ||
    !closeButton ||
    !form ||
    !input ||
    !scope ||
    !inlineStatus ||
    !submitButton ||
    !progressBox ||
    !progressFill ||
    !progressLabel ||
    !progressStatus ||
    !eventsList ||
    !resultLink ||
    !queueSummary ||
    !runningList ||
    !queuedList ||
    !recentList
  ) {
    return;
  }

  let currentJobId = null;
  let pollTimer = null;

  const scopeText =
    selectedSpace === "all"
      ? "현재 범위: 전체 raw 문서"
      : `현재 범위: ${selectedSpaceName} raw 문서`;
  scope.textContent = scopeText;

  const stopPolling = () => {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const openModal = () => {
    modal.hidden = false;
    backdrop.hidden = false;
    fetchQueueOverview().catch(() => {});
    window.setTimeout(() => input.focus(), 0);
  };

  const openModalWithQuery = (query) => {
    if (query) {
      input.value = query;
    }
    inlineStatus.textContent = "";
    openModal();
  };

  const openModalForRegenerate = (title) => {
    if (title) {
      input.value = title;
    }
    inlineStatus.textContent = "지식 문서를 대기열에 추가하는 중입니다.";
    openModal();
  };

  const closeModal = () => {
    modal.hidden = true;
    backdrop.hidden = true;
    stopPolling();
  };

  const resetProgress = () => {
    progressBox.hidden = true;
    progressFill.style.width = "0%";
    progressLabel.textContent = "0%";
    progressStatus.textContent = "대기 중입니다.";
    eventsList.innerHTML = "";
    resultLink.hidden = true;
    resultLink.removeAttribute("href");
  };

  const renderQueueBucket = (container, jobs, emptyMessage) => {
    container.innerHTML = "";
    if (!jobs || jobs.length === 0) {
      const item = document.createElement("li");
      item.className = "query-generator-queue-empty";
      item.textContent = emptyMessage;
      container.appendChild(item);
      return;
    }
    for (const job of jobs) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = job.query || "이름 없는 작업";
      item.appendChild(title);

      const meta = document.createElement("span");
      meta.className = "query-generator-event-status";
      const parts = [job.job_type_label || "", job.status || "", Number.isFinite(Number(job.progress)) ? `${job.progress}%` : ""];
      if (job.queue_position && job.queue_position > 0) {
        parts.push(`${job.queue_position}번째`);
      }
      meta.textContent = parts.filter(Boolean).join(" · ");
      item.appendChild(meta);

      const message = document.createElement("span");
      message.className = "query-generator-queue-message";
      message.textContent = job.error || job.message || "";
      item.appendChild(message);

      if (job.href) {
        const link = document.createElement("a");
        link.className = "source-link query-generator-queue-link";
        link.href = job.href;
        link.textContent = "문서 보기";
        item.appendChild(link);
      }

      container.appendChild(item);
    }
  };

  const renderQueueOverview = (overview) => {
    const counts = overview?.counts || {};
    const runningCount = Number(counts.running || 0);
    const queuedCount = Number(counts.queued || 0);
    if (!runningCount && !queuedCount) {
      queueSummary.textContent = "현재 대기열이 없습니다.";
    } else {
      queueSummary.textContent = `실행 중 ${runningCount}건 · 대기 ${queuedCount}건`;
    }
    renderQueueBucket(
      runningList,
      overview?.running ? [overview.running] : [],
      "실행 중인 작업이 없습니다."
    );
    renderQueueBucket(
      queuedList,
      overview?.queued || [],
      "대기 중인 작업이 없습니다."
    );
    renderQueueBucket(
      recentList,
      overview?.recent || [],
      "최근 작업이 없습니다."
    );
  };

  const renderEvents = (events) => {
    eventsList.innerHTML = "";
    for (const event of events || []) {
      const item = document.createElement("li");
      const message = document.createElement("strong");
      message.textContent = event.message || "";
      item.appendChild(message);

      const statusLine = document.createElement("span");
      statusLine.className = "query-generator-event-status";
      const progress = Number.isFinite(Number(event.progress)) ? `${event.progress}%` : "";
      statusLine.textContent = [event.status || "", progress].filter(Boolean).join(" · ");
      item.appendChild(statusLine);
      eventsList.appendChild(item);
    }
  };

  const renderSnapshot = (snapshot) => {
    progressBox.hidden = false;
    const progress = Number(snapshot.progress || 0);
    progressFill.style.width = `${progress}%`;
    progressLabel.textContent = `${progress}%`;
    progressStatus.textContent = snapshot.error || snapshot.message || "처리 중입니다.";
    inlineStatus.textContent = snapshot.error || snapshot.message || "";
    renderEvents(snapshot.events || []);

    if (snapshot.href) {
      resultLink.href = snapshot.href;
      resultLink.hidden = false;
    } else {
      resultLink.hidden = true;
      resultLink.removeAttribute("href");
    }

    const finished = snapshot.status === "completed" || snapshot.status === "failed";

    if (finished) {
      currentJobId = null;
    }
    return !finished;
  };

  const fetchQueueOverview = async () => {
    const response = await fetch("/api/query-jobs");
    const overview = await response.json();
    if (!response.ok) {
      throw new Error(overview.detail || "대기열을 불러오지 못했습니다.");
    }
    renderQueueOverview(overview);
    return overview;
  };

  const startQueuedJob = async (url, payload, pendingMessage) => {
    stopPolling();
    resetProgress();
    progressBox.hidden = false;
    submitButton.disabled = true;
    inlineStatus.textContent = pendingMessage;

    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const snapshot = await response.json();
      if (!response.ok) {
        throw new Error(snapshot.detail || "생성 작업을 시작하지 못했습니다.");
      }
      currentJobId = snapshot.id;
      renderSnapshot(snapshot);
      submitButton.disabled = false;
      pollStatus(currentJobId);
    } catch (error) {
      submitButton.disabled = false;
      inlineStatus.textContent = error.message || "작업 시작 중 오류가 발생했습니다.";
    }
  };

  const pollStatus = async (jobId) => {
    try {
      let hasActiveCurrent = false;
      if (jobId) {
        const response = await fetch(`/api/query-jobs/${encodeURIComponent(jobId)}`);
        const snapshot = await response.json();
        if (!response.ok) {
          throw new Error(snapshot.detail || "진행 상태를 불러오지 못했습니다.");
        }
        hasActiveCurrent = renderSnapshot(snapshot);
      }
      const overview = await fetchQueueOverview();
      const hasActiveQueue = Number(overview?.counts?.total_active || 0) > 0;
      if (hasActiveCurrent || hasActiveQueue) {
        pollTimer = window.setTimeout(() => pollStatus(currentJobId || jobId || null), 1000);
      } else {
        submitButton.disabled = false;
      }
    } catch (error) {
      stopPolling();
      submitButton.disabled = false;
      inlineStatus.textContent = error.message || "진행 상태를 확인하는 중 오류가 발생했습니다.";
    }
  };

  openButton.addEventListener("click", () => {
    openModal();
  });
  document.addEventListener("click", (event) => {
    const button = event.target instanceof Element ? event.target.closest("[data-query-seed]") : null;
    if (!button) return;
    const query = button.getAttribute("data-query-seed") || "";
    openModalWithQuery(query);
  });
  closeButton.addEventListener("click", closeModal);
  backdrop.addEventListener("click", closeModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) {
      closeModal();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) {
      inlineStatus.textContent = "생성할 키워드나 주제를 입력해주세요.";
      input.focus();
      return;
    }

    await startQueuedJob(
      "/api/query-jobs",
      {
        query,
        selected_space: selectedSpace === "all" ? null : selectedSpace,
      },
      "생성 작업을 시작하는 중입니다."
    );
  });

  document.addEventListener("submit", async (event) => {
    const formElement = event.target instanceof HTMLFormElement ? event.target : null;
    if (!formElement || formElement.getAttribute("data-queue-regenerate") !== "true") {
      return;
    }
    event.preventDefault();

    const kind = formElement.getAttribute("data-regenerate-kind") || "";
    const slug = formElement.getAttribute("data-regenerate-slug") || "";
    const title = formElement.getAttribute("data-regenerate-title") || slug;
    const formSelectedSpace = formElement.getAttribute("data-regenerate-space") || "";
    if (!kind || !slug) {
      return;
    }

    openModalForRegenerate(title);
    await startQueuedJob(
      "/api/query-jobs/knowledge",
      {
        kind,
        slug,
        title,
        selected_space: formSelectedSpace || null,
      },
      "재작성 작업을 시작하는 중입니다."
    );
  });

  resetProgress();
  fetchQueueOverview().catch(() => {});
})();
