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
    !resultLink
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
    window.setTimeout(() => input.focus(), 0);
  };

  const closeModal = () => {
    modal.hidden = true;
    backdrop.hidden = true;
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
    submitButton.disabled = snapshot.status === "running" || snapshot.status === "queued";
    input.disabled = snapshot.status === "running" || snapshot.status === "queued";

    if (finished) {
      stopPolling();
      currentJobId = null;
    }
  };

  const pollStatus = async (jobId) => {
    try {
      const response = await fetch(`/api/query-jobs/${encodeURIComponent(jobId)}`);
      const snapshot = await response.json();
      if (!response.ok) {
        throw new Error(snapshot.detail || "진행 상태를 불러오지 못했습니다.");
      }
      renderSnapshot(snapshot);
      if (snapshot.status === "running" || snapshot.status === "queued") {
        pollTimer = window.setTimeout(() => pollStatus(jobId), 1000);
      }
    } catch (error) {
      stopPolling();
      submitButton.disabled = false;
      input.disabled = false;
      inlineStatus.textContent = error.message || "진행 상태를 확인하는 중 오류가 발생했습니다.";
    }
  };

  openButton.addEventListener("click", () => {
    openModal();
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

    stopPolling();
    resetProgress();
    progressBox.hidden = false;
    submitButton.disabled = true;
    input.disabled = true;
    inlineStatus.textContent = "생성 작업을 시작하는 중입니다.";

    try {
      const response = await fetch("/api/query-jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          selected_space: selectedSpace === "all" ? null : selectedSpace,
        }),
      });
      const snapshot = await response.json();
      if (!response.ok) {
        throw new Error(snapshot.detail || "생성 작업을 시작하지 못했습니다.");
      }
      currentJobId = snapshot.id;
      renderSnapshot(snapshot);
      if (currentJobId) {
        pollStatus(currentJobId);
      }
    } catch (error) {
      submitButton.disabled = false;
      input.disabled = false;
      inlineStatus.textContent = error.message || "생성 작업 시작 중 오류가 발생했습니다.";
    }
  });

  resetProgress();
})();
