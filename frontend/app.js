document.addEventListener('DOMContentLoaded', () => {
  const chatWindow = document.getElementById('chat-window');
  const messageInput = document.getElementById('message-input');
  const sendBtn = document.getElementById('send-btn');
  const startDialogBtn = document.getElementById('start-dialog-btn');
  const toggleConfigBtn = document.getElementById('toggle-config-btn');
  const configPanel = document.getElementById('config-panel');
  const configForm = document.getElementById('config-form');
  const newDialogModal = document.getElementById('new-dialog-modal');
  const newDialogForm = document.getElementById('new-dialog-form');
  const cancelDialogBtn = document.getElementById('cancel-dialog-btn');
  const dialogInfo = document.getElementById('dialog-info');
  const toast = document.getElementById('toast');

  let conversationId = null;
  let isSending = false;

  function appendMessage(role, text) {
    const wrapper = document.createElement('div');
    wrapper.classList.add('message', role === 'user' ? 'user' : 'assistant');
    wrapper.dataset.role = role;
    wrapper.textContent = text;
    chatWindow.appendChild(wrapper);
    chatWindow.scrollTop = chatWindow.scrollHeight;
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
      document.getElementById('model-name').value = config.model?.name ?? '';
      document.getElementById('prompt-template').value = config.prompt_template ?? '';
    } catch (err) {
      console.error(err);
      showToast(err.message, true);
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
    configPanel.classList.toggle('hidden');
  });

  configForm.addEventListener('submit', saveConfig);

  fetchConfig();
});
