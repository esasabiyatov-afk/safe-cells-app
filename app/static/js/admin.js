"use strict";

(() => {
  const body = document.body;
  const state = {configured: null, token: null, snapshot: null, busy: false};
  const elements = {
    open: document.getElementById("adminOpen"),
    dialog: document.getElementById("adminDialog"),
    close: document.getElementById("adminDialogClose"),
    authForm: document.getElementById("adminAuthForm"),
    authNote: document.getElementById("adminAuthNote"),
    authError: document.getElementById("adminAuthError"),
    passwordLabel: document.getElementById("adminPasswordLabel"),
    password: document.getElementById("adminPassword"),
    passwordConfirmField: document.getElementById("adminPasswordConfirmField"),
    passwordConfirm: document.getElementById("adminPasswordConfirm"),
    authSubmit: document.getElementById("adminAuthSubmit"),
    content: document.getElementById("adminContent"),
    logout: document.getElementById("adminLogout"),
    error: document.getElementById("adminError"),
    success: document.getElementById("adminSuccess"),
    settingsForm: document.getElementById("adminSettingsForm"),
    expiringDays: document.getElementById("adminExpiringDays"),
    deposit: document.getElementById("adminDeposit"),
    tariffRows: document.getElementById("adminTariffRows"),
    settingsSubmit: document.getElementById("adminSettingsSubmit"),
    templateRows: document.getElementById("adminTemplateRows"),
    templateUploadForm: document.getElementById("adminTemplateUploadForm"),
    templateTarget: document.getElementById("adminTemplateTarget"),
    templateDisplay: document.getElementById("adminTemplateDisplay"),
    templateType: document.getElementById("adminTemplateType"),
    templateFile: document.getElementById("adminTemplateFile"),
    templateUpload: document.getElementById("adminTemplateUpload"),
    passwordForm: document.getElementById("adminPasswordForm"),
    currentPassword: document.getElementById("adminCurrentPassword"),
    newPassword: document.getElementById("adminNewPassword"),
    newPasswordConfirm: document.getElementById("adminNewPasswordConfirm"),
    passwordSubmit: document.getElementById("adminPasswordSubmit"),
  };

  function operationId() {
    return crypto.randomUUID();
  }

  async function jsonRequest(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.token) headers.set("X-Safe-Cells-Admin-Token", state.token);
    if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
    const response = await fetch(url, {...options, headers});
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.message || "Не удалось выполнить административную операцию.");
      error.status = response.status;
      throw error;
    }
    return payload;
  }

  function showError(target, message) {
    target.textContent = message;
    target.hidden = false;
  }

  function clearMessages() {
    elements.authError.hidden = true;
    elements.error.hidden = true;
    elements.success.hidden = true;
  }

  function showSuccess(message) {
    elements.success.textContent = message;
    elements.success.hidden = false;
    elements.error.hidden = true;
  }

  function setAuthMode() {
    const setup = state.configured === false;
    elements.authForm.hidden = false;
    elements.content.hidden = true;
    elements.passwordLabel.textContent = setup ? "Создайте административный пароль" : "Административный пароль";
    elements.password.autocomplete = setup ? "new-password" : "current-password";
    elements.passwordConfirmField.hidden = !setup;
    elements.passwordConfirm.required = setup;
    elements.authSubmit.textContent = setup ? "Создать пароль и открыть настройки" : "Войти";
    elements.authNote.textContent = setup
      ? "Первый администратор задаёт пароль не короче 12 символов с буквами и цифрами."
      : "Введите отдельный пароль административного раздела.";
  }

  function periodLabel(row) {
    return row.period_to_days === null
      ? `${row.period_from_days}+ дней`
      : `${row.period_from_days}–${row.period_to_days} дней`;
  }

  function renderTariffs() {
    elements.tariffRows.replaceChildren();
    for (const [index, row] of state.snapshot.tariffs.entries()) {
      const tr = document.createElement("tr");
      const height = document.createElement("td");
      const period = document.createElement("td");
      const rateCell = document.createElement("td");
      const input = document.createElement("input");
      height.textContent = `${row.height_mm} мм`;
      period.textContent = periodLabel(row);
      input.type = "number";
      input.min = "0";
      input.max = "10000000";
      input.required = true;
      input.value = String(row.price_per_day_minor);
      input.dataset.tariffIndex = String(index);
      input.setAttribute("aria-label", `Тариф ${row.height_mm} мм, ${periodLabel(row)}`);
      rateCell.append(input);
      tr.append(height, period, rateCell);
      elements.tariffRows.append(tr);
    }
  }

  function typeLabel(value) {
    return {opening: "Открытие", renewal: "Продление", closing: "Закрытие", manual: "Только вручную"}[value] || value;
  }

  function typeSelect(value) {
    const select = document.createElement("select");
    for (const [key, label] of Object.entries({opening: "Открытие", renewal: "Продление", closing: "Закрытие", manual: "Только вручную"})) {
      const option = document.createElement("option");
      option.value = key;
      option.textContent = label;
      option.selected = key === value;
      select.append(option);
    }
    return select;
  }

  function renderTemplates() {
    elements.templateRows.replaceChildren();
    elements.templateTarget.replaceChildren(new Option("Добавить новый шаблон", ""));
    if (!state.snapshot.templates.length) {
      const empty = document.createElement("p");
      empty.className = "dialog-note";
      empty.textContent = "Зарегистрированных шаблонов пока нет.";
      elements.templateRows.append(empty);
    }
    for (const template of state.snapshot.templates) {
      const row = document.createElement("div");
      row.className = "admin-template-row";
      row.dataset.templateId = template.template_id;
      const name = document.createElement("input");
      name.value = template.display_name;
      name.maxLength = 120;
      name.setAttribute("aria-label", "Название шаблона");
      const type = typeSelect(template.document_type);
      type.setAttribute("aria-label", "Комплект шаблона");
      const activeLabel = document.createElement("label");
      activeLabel.className = "admin-checkbox";
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = template.is_active;
      activeLabel.append(active, document.createTextNode(" Активен"));
      const file = document.createElement("span");
      file.className = "admin-template-file";
      file.textContent = template.relative_file_name;
      const save = document.createElement("button");
      save.type = "button";
      save.className = "secondary-button";
      save.textContent = "Сохранить";
      save.dataset.action = "save-template";
      row.append(name, type, activeLabel, file, save);
      elements.templateRows.append(row);

      const option = new Option(`${template.display_name} — заменить файл`, template.template_id);
      option.dataset.displayName = template.display_name;
      option.dataset.documentType = template.document_type;
      elements.templateTarget.append(option);
    }
  }

  function renderSettings() {
    elements.expiringDays.value = String(state.snapshot.config.expiring_soon_days);
    elements.deposit.value = String(state.snapshot.config.deposit_amount_minor);
    renderTariffs();
    renderTemplates();
  }

  async function loadSettings() {
    state.snapshot = await jsonRequest(body.dataset.adminSettingsUrl);
    renderSettings();
    elements.authForm.hidden = true;
    elements.content.hidden = false;
  }

  async function openAdmin() {
    if (!elements.dialog.open) elements.dialog.showModal();
    clearMessages();
    elements.authForm.hidden = true;
    elements.content.hidden = true;
    try {
      const status = await jsonRequest(body.dataset.adminStatusUrl);
      state.configured = status.configured;
      setAuthMode();
      elements.password.focus();
    } catch (error) {
      elements.authForm.hidden = false;
      showError(elements.authError, error.message);
    }
  }

  async function authenticate(event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    elements.authSubmit.disabled = true;
    elements.authError.hidden = true;
    try {
      let payload;
      if (state.configured) {
        payload = await jsonRequest(body.dataset.adminLoginUrl, {
          method: "POST",
          body: JSON.stringify({password: elements.password.value}),
        });
      } else {
        payload = await jsonRequest(body.dataset.adminSetupUrl, {
          method: "POST",
          body: JSON.stringify({
            operation_id: operationId(),
            password: elements.password.value,
            password_confirmation: elements.passwordConfirm.value,
          }),
        });
        state.configured = true;
      }
      state.token = payload.token;
      elements.password.value = "";
      elements.passwordConfirm.value = "";
      await loadSettings();
    } catch (error) {
      showError(elements.authError, error.message);
    } finally {
      state.busy = false;
      elements.authSubmit.disabled = false;
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    elements.settingsSubmit.disabled = true;
    clearMessages();
    try {
      const tariffs = state.snapshot.tariffs.map((row, index) => ({
        ...row,
        price_per_day_minor: Number(elements.tariffRows.querySelector(`[data-tariff-index="${index}"]`).value),
      }));
      const payload = await jsonRequest(body.dataset.adminSettingsUrl, {
        method: "PUT",
        body: JSON.stringify({
          operation_id: operationId(),
          config: {
            expiring_soon_days: Number(elements.expiringDays.value),
            deposit_amount_minor: Number(elements.deposit.value),
          },
          tariffs,
        }),
      });
      await loadSettings();
      showSuccess(payload.warning || "Параметры и тарифы сохранены.");
      document.getElementById("refreshButton")?.click();
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally {
      state.busy = false;
      elements.settingsSubmit.disabled = false;
    }
  }

  async function saveTemplateRow(event) {
    const button = event.target.closest("[data-action='save-template']");
    if (!button || state.busy) return;
    const row = button.closest(".admin-template-row");
    state.busy = true;
    button.disabled = true;
    clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminTemplatesUrl, {
        method: "PUT",
        body: JSON.stringify({
          operation_id: operationId(),
          template_id: row.dataset.templateId,
          display_name: row.querySelector("input[type='text'], input:not([type])").value,
          document_type: row.querySelector("select").value,
          is_active: row.querySelector("input[type='checkbox']").checked,
        }),
      });
      await loadSettings();
      showSuccess(payload.warning || "Настройка шаблона сохранена.");
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally {
      state.busy = false;
      button.disabled = false;
    }
  }

  function selectTemplateTarget() {
    const option = elements.templateTarget.selectedOptions[0];
    if (!option?.value) return;
    elements.templateDisplay.value = option.dataset.displayName || "";
    elements.templateType.value = option.dataset.documentType || "manual";
  }

  async function uploadTemplate(event) {
    event.preventDefault();
    if (state.busy || !elements.templateFile.files[0]) return;
    state.busy = true;
    elements.templateUpload.disabled = true;
    clearMessages();
    try {
      const form = new FormData();
      form.set("operation_id", operationId());
      form.set("document_type", elements.templateType.value);
      form.set("display_name", elements.templateDisplay.value);
      form.set("file", elements.templateFile.files[0]);
      if (elements.templateTarget.value) form.set("template_id", elements.templateTarget.value);
      const payload = await jsonRequest(body.dataset.adminTemplatesUrl, {method: "POST", body: form});
      elements.templateUploadForm.reset();
      await loadSettings();
      showSuccess(payload.warning || "DOCX-шаблон проверен и сохранён.");
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally {
      state.busy = false;
      elements.templateUpload.disabled = false;
    }
  }

  async function changePassword(event) {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    elements.passwordSubmit.disabled = true;
    clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminPasswordUrl, {
        method: "PUT",
        body: JSON.stringify({
          operation_id: operationId(),
          current_password: elements.currentPassword.value,
          new_password: elements.newPassword.value,
          password_confirmation: elements.newPasswordConfirm.value,
        }),
      });
      state.token = payload.token;
      elements.passwordForm.reset();
      showSuccess(payload.warning || "Административный пароль изменён.");
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally {
      state.busy = false;
      elements.passwordSubmit.disabled = false;
    }
  }

  function sessionEnded(error) {
    state.token = null;
    state.configured = true;
    setAuthMode();
    showError(elements.authError, error.message);
  }

  async function logout(closeDialog = false) {
    const token = state.token;
    state.token = null;
    state.snapshot = null;
    if (token) {
      fetch(body.dataset.adminLogoutUrl, {
        method: "POST",
        headers: {"X-Safe-Cells-Admin-Token": token},
      }).catch(() => {});
    }
    if (closeDialog && elements.dialog.open) elements.dialog.close();
    else {
      state.configured = true;
      setAuthMode();
    }
  }

  elements.open.addEventListener("click", openAdmin);
  elements.close.addEventListener("click", () => logout(true));
  elements.dialog.addEventListener("cancel", (event) => {event.preventDefault(); logout(true);});
  elements.authForm.addEventListener("submit", authenticate);
  elements.logout.addEventListener("click", () => logout(false));
  elements.settingsForm.addEventListener("submit", saveSettings);
  elements.templateRows.addEventListener("click", saveTemplateRow);
  elements.templateTarget.addEventListener("change", selectTemplateTarget);
  elements.templateUploadForm.addEventListener("submit", uploadTemplate);
  elements.passwordForm.addEventListener("submit", changePassword);
})();
