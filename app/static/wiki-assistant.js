(() => {
  const fab = document.getElementById("assistant-fab");
  const modal = document.getElementById("assistant-modal");
  const backdrop = document.getElementById("assistant-backdrop");
  const closeButton = document.getElementById("assistant-close");
  const form = document.getElementById("assistant-form");
  const questionInput = document.getElementById("assistant-question");
  const thread = document.getElementById("assistant-thread");
  const status = document.getElementById("assistant-status");
  const submitButton = form?.querySelector(".assistant-submit");
  const selectedSpace = document.body.dataset.selectedSpace || "all";

  if (!fab || !modal || !backdrop || !form || !questionInput || !thread || !status || !submitButton) return;

  const openModal = () => {
    modal.hidden = false;
    backdrop.hidden = false;
    fab.setAttribute("aria-expanded", "true");
    window.setTimeout(() => questionInput.focus(), 0);
  };

  const closeModal = () => {
    modal.hidden = true;
    backdrop.hidden = true;
    fab.setAttribute("aria-expanded", "false");
  };

  const appendQuestion = (text) => {
    const bubble = document.createElement("div");
    bubble.className = "assistant-question-bubble";
    bubble.textContent = text;
    thread.appendChild(bubble);
  };

  const createSaveButton = (question, payload) => {
    const actionRow = document.createElement("div");
    actionRow.className = "assistant-answer-actions";

    if (selectedSpace === "all") {
      const note = document.createElement("span");
      note.className = "assistant-save-note";
      note.textContent = "분석 문서 저장은 특정 space를 선택한 화면에서만 가능합니다.";
      actionRow.appendChild(note);
      return actionRow;
    }

    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.className = "assistant-save";
    saveButton.textContent = `${selectedSpace} space에 저장`;

    const savedLink = document.createElement("a");
    savedLink.className = "assistant-saved-link";
    savedLink.hidden = true;
    savedLink.textContent = "저장된 분석 문서 보기";

    saveButton.addEventListener("click", async () => {
      saveButton.disabled = true;
      status.textContent = "분석 문서를 저장하는 중입니다...";
      try {
        const response = await fetch("/api/ask/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            space_key: selectedSpace,
            question,
            scope: payload.scope,
            answer: payload.answer,
            sources: payload.sources,
          }),
        });
        const saved = await response.json();
        if (!response.ok) {
          throw new Error(saved.detail || "분석 문서 저장에 실패했습니다.");
        }
        saveButton.hidden = true;
        savedLink.href = saved.href;
        savedLink.hidden = false;
        status.textContent = `${selectedSpace} space에 분석 문서를 저장했습니다.`;
      } catch (error) {
        saveButton.disabled = false;
        status.textContent = error.message || "분석 문서 저장 중 오류가 발생했습니다.";
      }
    });

    actionRow.appendChild(saveButton);
    actionRow.appendChild(savedLink);
    return actionRow;
  };

  const appendAnswer = (payload, question) => {
    const wrapper = document.createElement("div");
    wrapper.className = "assistant-answer";

    const body = document.createElement("div");
    body.className = "assistant-answer-body";
    body.textContent = payload.answer || "답변을 만들지 못했습니다.";
    wrapper.appendChild(body);

    if (Array.isArray(payload.sources) && payload.sources.length > 0) {
      const sourceBox = document.createElement("div");
      sourceBox.className = "assistant-sources";
      sourceBox.innerHTML = "<strong>참고 문서</strong>";

      const list = document.createElement("ul");
      for (const source of payload.sources) {
        const item = document.createElement("li");
        const link = document.createElement("a");
        link.href = source.href || `/spaces/${source.space_key}/pages/${source.slug}`;
        link.textContent = `${source.space_key} · ${source.title}`;
        item.appendChild(link);
        if (source.excerpt) {
          const excerpt = document.createElement("p");
          excerpt.textContent = source.excerpt;
          item.appendChild(excerpt);
        }
        list.appendChild(item);
      }
      sourceBox.appendChild(list);
      wrapper.appendChild(sourceBox);
    }

    wrapper.appendChild(createSaveButton(question, payload));
    thread.appendChild(wrapper);
    thread.scrollTop = thread.scrollHeight;
  };

  fab.addEventListener("click", openModal);
  closeButton?.addEventListener("click", closeModal);
  backdrop.addEventListener("click", closeModal);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.hidden) closeModal();
  });
  questionInput.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = questionInput.value.trim();
    if (!question) {
      status.textContent = "질문을 입력해주세요.";
      questionInput.focus();
      return;
    }

    const selectedScopeInput = document.querySelector('input[name="assistant-scope"]:checked');
    const scope = selectedScopeInput ? selectedScopeInput.value : "global";
    status.textContent = "답변을 생성하는 중입니다...";
    submitButton.disabled = true;
    appendQuestion(question);
    questionInput.value = "";
    thread.querySelector(".assistant-empty")?.remove();

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          scope,
          selected_space: selectedSpace,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "질문 처리에 실패했습니다.");
      }
      appendAnswer(payload, question);
      status.textContent = scope === "global" ? "전체 위키 기준 답변입니다." : `${selectedSpace} space 기준 답변입니다.`;
    } catch (error) {
      appendAnswer({ answer: error.message || "질문 처리 중 오류가 발생했습니다.", sources: [], scope }, question);
      status.textContent = "오류가 발생했습니다.";
    } finally {
      submitButton.disabled = false;
      questionInput.focus();
    }
  });
})();
