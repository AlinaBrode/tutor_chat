document.addEventListener('DOMContentLoaded', () => {
  const chatWindow = document.getElementById('chat-window');
  const messageInput = document.getElementById('message-input');
  const sendBtn = document.getElementById('send-btn');
  const startDialogBtn = document.getElementById('start-dialog-btn');
  const toggleConfigBtn = document.getElementById('toggle-config-btn');
  const toggleEstimationBtn = document.getElementById('toggle-estimation-btn');
  const toggleExportBtn = document.getElementById('toggle-export-btn');
  const configPanel = document.getElementById('config-panel');
  const configForm = document.getElementById('config-form');
  const modelSelect = document.getElementById('model-name');
  const estimationPanel = document.getElementById('estimation-panel');
  const estimationForm = document.getElementById('estimation-form');
  const panelResizer = document.getElementById('panel-resizer');
  const exportPanel = document.getElementById('export-panel');
  const exportSelect = document.getElementById('export-conversation-select');
  const exportPreview = document.getElementById('export-preview');
  const downloadConversationBtn = document.getElementById('download-conversation-btn');
  const downloadAllConversationsBtn = document.getElementById('download-all-conversations-btn');
  const newDialogModal = document.getElementById('new-dialog-modal');
  const newDialogForm = document.getElementById('new-dialog-form');
  const cancelDialogBtn = document.getElementById('cancel-dialog-btn');
  const dialogInfo = document.getElementById('dialog-info');
  const toast = document.getElementById('toast');
  const estimationScore = document.getElementById('estimation-score');
  const estimationFeedback = document.getElementById('estimation-feedback');
  const appMain = document.querySelector('.app-main');

  let conversationId = null;
  let isSending = false;
  let isEstimating = false;
  const DEFAULT_MODELS = [
    { name: 'gemini-flash-latest', display_name: 'Gemini Flash' },
    { name: 'gemini-pro', display_name: 'Gemini Pro' },
  ];
  let availableModels = [...DEFAULT_MODELS];
  let currentSidePanel = null;
  let savedPanelWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--panel-width'), 10) || 360;
  let isResizingPanel = false;
  let activePointerId = null;
  const PANEL_MIN_WIDTH = 240;
  const PANEL_MAX_WIDTH = 640;
  const MIN_CHAT_WIDTH = 320;
  let conversationsLoaded = false;
  let conversationsLoading = false;
  let exportConversations = [];
  let exportCurrentConversationId = null;
  let exportPreviewText = '';

  function typesetMath(target) {
    const elements = Array.isArray(target) ? target : [target];
    if (!window.MathJax?.typesetPromise) {
      return;
    }
    window.MathJax.typesetPromise(elements).catch((err) => {
      console.error('MathJax rendering error', err);
    });
  }

  function clampPanelWidth(width) {
    if (!appMain) {
      return width;
    }
    const rect = appMain.getBoundingClientRect();
    const resizerWidth = panelResizer && !panelResizer.classList.contains('hidden')
      ? panelResizer.offsetWidth || 6
      : 6;
    const maxAllowed = Math.max(PANEL_MIN_WIDTH, rect.width - MIN_CHAT_WIDTH - resizerWidth);
    const maxWidth = Math.min(PANEL_MAX_WIDTH, maxAllowed);
    if (maxWidth <= PANEL_MIN_WIDTH) {
      return PANEL_MIN_WIDTH;
    }
    return Math.min(Math.max(width, PANEL_MIN_WIDTH), maxWidth);
  }

  function applyPanelWidth(panel, width) {
    if (!panel) {
      return;
    }
    const clamped = clampPanelWidth(width || savedPanelWidth);
    panel.style.width = `${clamped}px`;
    panel.style.flex = `0 0 ${clamped}px`;
    savedPanelWidth = clamped;
  }

  function getPanelWidth(panel) {
    if (!panel) {
      return savedPanelWidth;
    }
    const rect = panel.getBoundingClientRect();
    return rect.width || savedPanelWidth;
  }

  function ensureResizerPosition(panel) {
    if (!panelResizer || !appMain || !panel) {
      return;
    }
    if (panelResizer.nextElementSibling !== panel) {
      appMain.insertBefore(panelResizer, panel);
    }
  }

  function showResizer(panel) {
    if (!panelResizer) {
      return;
    }
    ensureResizerPosition(panel);
    panelResizer.classList.remove('hidden');
    panelResizer.setAttribute('aria-hidden', 'false');
  }

  function hideResizer() {
    if (!panelResizer) {
      return;
    }
    panelResizer.classList.add('hidden');
    panelResizer.setAttribute('aria-hidden', 'true');
  }

  function showSidePanel(panel) {
    if (!panel) {
      return;
    }

    if (currentSidePanel && currentSidePanel !== panel) {
      savedPanelWidth = getPanelWidth(currentSidePanel) || savedPanelWidth;
      currentSidePanel.classList.add('hidden');
    }

    if (panel.classList.contains('hidden')) {
      panel.classList.remove('hidden');
    }

    currentSidePanel = panel;
    applyPanelWidth(panel, savedPanelWidth);
    showResizer(panel);
  }

  function hideSidePanel(panel) {
    if (!panel) {
      return;
    }

    if (!panel.classList.contains('hidden')) {
      savedPanelWidth = getPanelWidth(panel) || savedPanelWidth;
      panel.classList.add('hidden');
    }

    if (currentSidePanel === panel) {
      currentSidePanel = null;
      hideResizer();
    }
  }

  function togglePanel(panel) {
    if (!panel) {
      return;
    }
    if (currentSidePanel === panel && !panel.classList.contains('hidden')) {
      hideSidePanel(panel);
    } else {
      showSidePanel(panel);
    }
  }

  function resetExportPreview(message = 'Выберите диалог, чтобы увидеть содержимое.') {
    if (exportPreview) {
      exportPreview.textContent = message;
    }
    exportPreviewText = '';
    exportCurrentConversationId = null;
    if (downloadConversationBtn) {
      downloadConversationBtn.disabled = true;
    }
    if (exportSelect && !conversationsLoaded) {
      exportSelect.value = '';
    }
  }

  function formatConversationLabel(conversation) {
    const rawDate = conversation.created_at;
    let dateText = 'Без даты';
    if (rawDate) {
      const parsed = new Date(rawDate);
      if (!Number.isNaN(parsed.getTime())) {
        dateText = parsed.toLocaleString();
      }
    }
    const snippet = (conversation.first_user_message || '')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 80);
    const suffix = snippet ? ` — ${snippet}${snippet.length === 80 ? '…' : ''}` : '';
    return `${dateText}${suffix}`;
  }

  function populateConversationOptions(conversations = []) {
    if (!exportSelect) {
      return;
    }
    exportSelect.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.disabled = true;
    placeholder.textContent = conversations.length ? 'Выберите диалог' : 'Диалоги не найдены';
    placeholder.selected = true;
    exportSelect.appendChild(placeholder);

    conversations.forEach((conversation) => {
      if (!conversation?.id) {
        return;
      }
      const option = document.createElement('option');
      option.value = conversation.id;
      option.textContent = formatConversationLabel(conversation);
      exportSelect.appendChild(option);
    });

    exportSelect.disabled = conversations.length === 0;
  }

  async function fetchConversationList() {
    if (conversationsLoaded || conversationsLoading || !exportSelect) {
      return;
    }
    conversationsLoading = true;
    try {
      const res = await fetch('/api/conversations');
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось получить список диалогов');
      }
      const data = await res.json();
      exportConversations = Array.isArray(data.conversations) ? data.conversations : [];
      conversationsLoaded = true;
      populateConversationOptions(exportConversations);
      resetExportPreview(
        exportConversations.length
          ? 'Выберите диалог, чтобы увидеть содержимое.'
          : 'Сохранённых диалогов пока нет.'
      );
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Не удалось получить список диалогов';
      showToast(message, true);
      populateConversationOptions([]);
      resetExportPreview(message);
    } finally {
      conversationsLoading = false;
    }
  }

  function buildConversationText(conversation) {
    if (!conversation) {
      return '';
    }
    const lines = [];
    const prompt = conversation.prompt_template || '';
    if (prompt) {
      lines.push('Промпт:');
      lines.push(prompt);
      lines.push('');
    }

    const roleLabels = {
      user: 'Ученик',
      assistant: 'Учитель',
      system: 'Система',
    };

    (conversation.messages || []).forEach((message) => {
      if (!message?.content) {
        return;
      }
      const label = roleLabels[message.role] || 'Сообщение';
      lines.push(`${label}: ${message.content}`);
      lines.push('');
    });

    return lines.join('\n').trim() || 'Диалог пуст.';
  }

  function updateExportPreviewText(text, conversationId) {
    exportPreviewText = text;
    exportCurrentConversationId = conversationId;
    if (exportPreview) {
      exportPreview.textContent = text;
    }
    if (downloadConversationBtn) {
      downloadConversationBtn.disabled = !text;
    }
  }

  async function loadConversationForExport(conversationId) {
    if (!conversationId) {
      resetExportPreview();
      return;
    }
    if (exportPreview) {
      exportPreview.textContent = 'Загружаем диалог…';
    }
    if (downloadConversationBtn) {
      downloadConversationBtn.disabled = true;
    }
    try {
      const res = await fetch(`/api/conversations/${conversationId}/export`);
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось загрузить диалог');
      }
      const data = await res.json();
      const conversation = data.conversation;
      const text = buildConversationText(conversation);
      updateExportPreviewText(text, conversationId);
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Не удалось загрузить диалог';
      showToast(message, true);
      resetExportPreview(message);
    }
  }

  function downloadConversation() {
    if (!exportPreviewText || !exportCurrentConversationId) {
      return;
    }
    const blob = new Blob([exportPreviewText], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `conversation_${exportCurrentConversationId}.txt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function extractFileName(contentDisposition) {
    if (!contentDisposition) {
      return null;
    }
    const match = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(contentDisposition);
    if (!match) {
      return null;
    }
    return decodeURIComponent(match[1] || match[2] || '').trim() || null;
  }

  async function downloadAllConversations() {
    if (!downloadAllConversationsBtn) {
      return;
    }
    downloadAllConversationsBtn.disabled = true;
    try {
      const res = await fetch('/api/export/all');
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось экспортировать диалоги');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const disposition = res.headers.get('Content-Disposition');
      const filename = extractFileName(disposition) || 'conversation_export.xlsx';
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Не удалось экспортировать диалоги';
      showToast(message, true);
    } finally {
      downloadAllConversationsBtn.disabled = false;
    }
  }

  function populateModelOptions(preferredValue = '') {
    if (!modelSelect) {
      return;
    }

    const currentValue = preferredValue ?? modelSelect.value ?? '';
    modelSelect.innerHTML = '';

    const models = availableModels || [];

    if (!models.length) {
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.disabled = true;
      placeholder.textContent = 'Список моделей недоступен';
      placeholder.selected = true;
      modelSelect.appendChild(placeholder);
    } else {
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.disabled = true;
      placeholder.textContent = 'Выберите модель';
      placeholder.selected = true;
      modelSelect.appendChild(placeholder);

      models.forEach((model) => {
        if (!model?.name) {
          return;
        }
        const option = document.createElement('option');
        option.value = model.name;
        option.textContent = model.display_name || model.name;
        if (model.description) {
          option.title = model.description;
        }
        modelSelect.appendChild(option);
      });
    }

    if (currentValue) {
      let option = Array.from(modelSelect.options).find((opt) => opt.value === currentValue);
      if (!option) {
        option = document.createElement('option');
        option.value = currentValue;
        option.textContent = `${currentValue} (custom)`;
        modelSelect.appendChild(option);
      }
      modelSelect.value = currentValue;
    }
  }

  async function fetchModels(preferredValue = '') {
    if (!modelSelect) {
      return;
    }

    try {
      const res = await fetch('/api/models');
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось получить список моделей');
      }
      const data = await res.json();
      if (Array.isArray(data.models)) {
        availableModels = data.models.filter((model) => Boolean(model?.name));
      } else {
        availableModels = [...DEFAULT_MODELS];
      }
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Не удалось получить список моделей';
      showToast(message, true);
      if (!availableModels.length) {
        availableModels = [...DEFAULT_MODELS];
      }
    } finally {
      populateModelOptions(preferredValue);
    }
  }

  function appendMessage(role, text) {
    const wrapper = document.createElement('div');
    wrapper.classList.add('message', role === 'user' ? 'user' : 'assistant');
    wrapper.dataset.role = role;
    wrapper.textContent = text;
    chatWindow.appendChild(wrapper);
    chatWindow.scrollTop = chatWindow.scrollHeight;

    typesetMath(wrapper);
  }

  function resetChat() {
    chatWindow.innerHTML = '';
  }

  function setConversationActive(active) {
    messageInput.disabled = !active;
    sendBtn.disabled = !active;
    if (active) {
      messageInput.focus();
    }
  }

  function showToast(message, isError = false) {
    toast.textContent = message;
    toast.classList.remove('hidden');
    toast.classList.add('visible');
    toast.style.background = isError ? 'var(--danger-color)' : '#323232';
    setTimeout(() => {
      toast.classList.remove('visible');
      toast.classList.add('hidden');
    }, 3200);
  }

  function resetEstimationResult() {
    if (estimationScore) {
      estimationScore.textContent = '—';
    }
    if (estimationFeedback) {
      estimationFeedback.textContent = '—';
    }
  }

  function updateEstimationResult(score, feedback) {
    if (estimationScore) {
      estimationScore.textContent = score ?? '—';
    }
    if (estimationFeedback) {
      estimationFeedback.textContent = feedback ?? '—';
      typesetMath(estimationFeedback);
    }
  }

  function toggleModal(show) {
    if (show) {
      newDialogModal.classList.remove('hidden');
    } else {
      newDialogModal.classList.add('hidden');
      newDialogForm.reset();
    }
  }

  async function fetchConfig() {
    try {
      const res = await fetch('/api/config');
      if (!res.ok) throw new Error('Не удалось загрузить конфигурацию');
      const config = await res.json();
      const currentModel = config.model?.name ?? '';
      populateModelOptions(currentModel);
      document.getElementById('prompt-template').value = config.prompt_template ?? '';
      document.getElementById('estimation-template').value = config.estimation_template ?? '';
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Не удалось загрузить конфигурацию';
      showToast(message, true);
    }
  }

  function updateDialogInfo(data) {
    const items = [];
    if (data.task) {
      items.push(`Задача: ${data.task}`);
    }
    if (data.task_image) {
      items.push('Изображение задания загружено');
    }
    if (data.solution_image) {
      items.push('Изображение решения загружено');
    }
    if (!items.length) {
      dialogInfo.classList.add('hidden');
      dialogInfo.textContent = '';
      return;
    }
    dialogInfo.innerHTML = items.map(text => `<span>${text}</span>`).join('<br>');
    dialogInfo.classList.remove('hidden');
  }

  async function submitEstimation(event) {
    event.preventDefault();
    if (!estimationForm || isEstimating) {
      return;
    }

    isEstimating = true;
    const submitButton = estimationForm.querySelector('button[type="submit"]');
    if (submitButton) {
      submitButton.disabled = true;
    }
    resetEstimationResult();

    try {
      const formData = new FormData(estimationForm);
      const res = await fetch('/api/estimation', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        const message = error.error || 'Не удалось получить оценку';
        throw new Error(message);
      }
      const data = await res.json();
      updateEstimationResult(data.score, data.feedback);
      showToast('Оценка получена');
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : 'Не удалось получить оценку';
      showToast(message, true);
      updateEstimationResult(null, `[Ошибка] ${message}`);
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
      }
      isEstimating = false;
    }
  }

  if (panelResizer) {
    panelResizer.addEventListener('pointerdown', (event) => {
      if (!currentSidePanel || !appMain) {
        return;
      }
      event.preventDefault();
      panelResizer.setPointerCapture(event.pointerId);
      isResizingPanel = true;
      activePointerId = event.pointerId;
      document.body.classList.add('resizing-side-panel');
    });

    panelResizer.addEventListener('pointermove', (event) => {
      if (!isResizingPanel || event.pointerId !== activePointerId || !currentSidePanel || !appMain) {
        return;
      }
      const mainRect = appMain.getBoundingClientRect();
      let newWidth = mainRect.right - event.clientX;
      const resizerWidth = panelResizer.offsetWidth || 6;
      newWidth -= resizerWidth / 2;
      const clamped = clampPanelWidth(newWidth);
      applyPanelWidth(currentSidePanel, clamped);
    });

    const finishResize = (event) => {
      if (!isResizingPanel || event.pointerId !== activePointerId) {
        return;
      }
      isResizingPanel = false;
      activePointerId = null;
      document.body.classList.remove('resizing-side-panel');
      if (panelResizer.hasPointerCapture(event.pointerId)) {
        panelResizer.releasePointerCapture(event.pointerId);
      }
    };

    panelResizer.addEventListener('pointerup', finishResize);
    panelResizer.addEventListener('pointercancel', finishResize);
  }

  async function createDialog(formData) {
    try {
      const res = await fetch('/api/dialogs', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось создать диалог');
      }
      const data = await res.json();
      conversationId = data.conversation_id;
      resetChat();
      setConversationActive(true);
      updateDialogInfo(data.conversation || {});
      showToast('Диалог создан, можно начинать общение');
    } catch (err) {
      console.error(err);
      showToast(err.message, true);
    }
  }

  async function sendMessage() {
    if (!conversationId) {
      showToast('Создайте новый диалог перед отправкой сообщения', true);
      return;
    }
    const content = messageInput.value.trim();
    if (!content) {
      showToast('Введите сообщение', true);
      return;
    }
    if (isSending) {
      return;
    }

    isSending = true;
    sendBtn.disabled = true;

    appendMessage('user', content);
    messageInput.value = '';

    try {
      const res = await fetch(`/api/dialogs/${conversationId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ message: content })
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Ошибка при отправке сообщения');
      }
      const data = await res.json();
      appendMessage('assistant', data.assistant_message?.content ?? '[нет ответа]');
    } catch (err) {
      console.error(err);
      showToast(err.message, true);
      appendMessage('assistant', '[Ошибка при получении ответа от LLM]');
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      messageInput.focus();
    }
  }

  function formToJSON(form) {
    const formData = new FormData(form);
    const result = {};
    for (const [key, value] of formData.entries()) {
      if (key.includes('.')) {
        const [group, field] = key.split('.');
        result[group] = result[group] || {};
        result[group][field] = value;
      } else {
        result[key] = value;
      }
    }
    return result;
  }

  async function saveConfig(event) {
    event.preventDefault();
    const payload = formToJSON(configForm);
    try {
      const res = await fetch('/api/config', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const error = await res.json().catch(() => ({}));
        throw new Error(error.error || 'Не удалось сохранить настройки');
      }
      showToast('Настройки сохранены');
    } catch (err) {
      console.error(err);
      showToast(err.message, true);
    }
  }

  // Event wiring
  startDialogBtn.addEventListener('click', () => toggleModal(true));
  cancelDialogBtn.addEventListener('click', () => toggleModal(false));

  newDialogForm.addEventListener('submit', (event) => {
    event.preventDefault();
    const formData = new FormData(newDialogForm);
    toggleModal(false);
    createDialog(formData);
  });

  sendBtn.addEventListener('click', sendMessage);

  messageInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  messageInput.addEventListener('input', () => {
    messageInput.style.height = 'auto';
    messageInput.style.height = `${messageInput.scrollHeight}px`;
  });

  toggleConfigBtn.addEventListener('click', () => {
    togglePanel(configPanel);
  });

  if (toggleEstimationBtn) {
    toggleEstimationBtn.addEventListener('click', () => {
      togglePanel(estimationPanel);
    });
  }

  if (toggleExportBtn) {
    toggleExportBtn.addEventListener('click', async () => {
      const willOpen = currentSidePanel !== exportPanel || (exportPanel && exportPanel.classList.contains('hidden'));
      togglePanel(exportPanel);
      if (willOpen && exportPanel && !exportPanel.classList.contains('hidden')) {
        await fetchConversationList();
      }
    });
  }

  configForm.addEventListener('submit', saveConfig);

  if (estimationForm) {
    estimationForm.addEventListener('submit', submitEstimation);
  }

  if (exportSelect) {
    exportSelect.addEventListener('change', (event) => {
      const selectedId = event.target.value;
      if (!selectedId) {
        resetExportPreview();
        return;
      }
      loadConversationForExport(selectedId);
    });
  }

  if (downloadConversationBtn) {
    downloadConversationBtn.addEventListener('click', downloadConversation);
  }

  if (downloadAllConversationsBtn) {
    downloadAllConversationsBtn.addEventListener('click', downloadAllConversations);
  }

  populateModelOptions();
  populateConversationOptions([]);
  resetExportPreview();

  (async () => {
    await fetchModels();
    await fetchConfig();
  })();
});
