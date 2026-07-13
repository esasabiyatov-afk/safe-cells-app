"use strict";

(() => {
  const body = document.body;
  const state = {configured: null, accessMode: "password", token: null, snapshot: null, busy: false};
  const elements = {
    open: document.getElementById("adminOpen"), dialog: document.getElementById("adminDialog"), close: document.getElementById("adminDialogClose"),
    authForm: document.getElementById("adminAuthForm"), authNote: document.getElementById("adminAuthNote"), authError: document.getElementById("adminAuthError"),
    passwordField: document.getElementById("adminPasswordField"), passwordLabel: document.getElementById("adminPasswordLabel"), password: document.getElementById("adminPassword"),
    passwordConfirmField: document.getElementById("adminPasswordConfirmField"), passwordConfirm: document.getElementById("adminPasswordConfirm"),
    acknowledgementField: document.getElementById("adminAcknowledgementField"), acknowledgement: document.getElementById("adminAcknowledgement"), authSubmit: document.getElementById("adminAuthSubmit"),
    content: document.getElementById("adminContent"), logout: document.getElementById("adminLogout"), error: document.getElementById("adminError"), success: document.getElementById("adminSuccess"),
    tabs: [...document.querySelectorAll("[data-admin-tab]")], panels: [...document.querySelectorAll("[data-admin-panel]")],
    generalForm: document.getElementById("adminGeneralForm"), tariffsForm: document.getElementById("adminTariffsForm"),
    expiringDays: document.getElementById("adminExpiringDays"), deposit: document.getElementById("adminDeposit"), tariffRows: document.getElementById("adminTariffRows"), penaltyRows: document.getElementById("adminPenaltyRows"),
    generalSubmit: document.getElementById("adminGeneralSubmit"), tariffsSubmit: document.getElementById("adminTariffsSubmit"),
    templateRows: document.getElementById("adminTemplateRows"), templateUploadForm: document.getElementById("adminTemplateUploadForm"), templateTarget: document.getElementById("adminTemplateTarget"),
    templateDisplay: document.getElementById("adminTemplateDisplay"), templateType: document.getElementById("adminTemplateType"), templateFile: document.getElementById("adminTemplateFile"), templateUpload: document.getElementById("adminTemplateUpload"),
    employeeRows: document.getElementById("adminEmployeeRows"), employeeAddForm: document.getElementById("adminEmployeeAddForm"),
    employeeName: document.getElementById("adminEmployeeName"), employeeAdd: document.getElementById("adminEmployeeAdd"),
    accessForm: document.getElementById("adminAccessForm"), accessPassword: document.getElementById("adminAccessPassword"), accessAcknowledgement: document.getElementById("adminAccessAcknowledgement"), accessSubmit: document.getElementById("adminAccessSubmit"),
    passwordForm: document.getElementById("adminPasswordForm"), currentPassword: document.getElementById("adminCurrentPassword"), newPassword: document.getElementById("adminNewPassword"), newPasswordConfirm: document.getElementById("adminNewPasswordConfirm"), passwordSubmit: document.getElementById("adminPasswordSubmit"),
  };

  const operationId = () => crypto.randomUUID();

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

  function showError(target, message) { target.textContent = message; target.hidden = false; }
  function clearMessages() { elements.authError.hidden = true; elements.error.hidden = true; elements.success.hidden = true; }
  function showSuccess(message) { elements.success.textContent = message; elements.success.hidden = false; elements.error.hidden = true; }

  function selectTab(name) {
    for (const tab of elements.tabs) {
      const active = tab.dataset.adminTab === name;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    }
    for (const panel of elements.panels) panel.hidden = panel.dataset.adminPanel !== name;
  }

  function setAuthMode() {
    const acknowledgement = state.accessMode === "acknowledgement";
    const setup = !acknowledgement && state.configured === false;
    elements.authForm.hidden = false;
    elements.content.hidden = true;
    elements.passwordField.hidden = acknowledgement;
    elements.password.required = !acknowledgement;
    elements.passwordConfirmField.hidden = !setup;
    elements.passwordConfirm.required = setup;
    elements.acknowledgementField.hidden = !acknowledgement;
    elements.acknowledgement.required = acknowledgement;
    if (acknowledgement) {
      elements.authNote.textContent = "Пароль не требуется. Подтвердите, что административные параметры меняет руководитель отдела.";
      elements.authSubmit.textContent = "Принять и открыть настройки";
    } else if (setup) {
      elements.passwordLabel.textContent = "Создайте общий пароль отдела";
      elements.password.autocomplete = "new-password";
      elements.authSubmit.textContent = "Создать пароль и открыть настройки";
      elements.authNote.textContent = "Первый вход: задайте один общий пароль не короче 12 символов с буквами и цифрами.";
    } else {
      elements.passwordLabel.textContent = "Общий пароль отдела";
      elements.password.autocomplete = "current-password";
      elements.authSubmit.textContent = "Открыть настройки";
      elements.authNote.textContent = "Введите единый пароль, принятый в отделе.";
    }
  }

  function periodLabel(row) { return row.period_to_days === null ? `${row.period_from_days}+ дней` : `${row.period_from_days}–${row.period_to_days} дней`; }
  function typeLabel(value) { return {opening: "При открытии", renewal: "При продлении", closing: "При закрытии", manual: "Только вручную"}[value] || value; }
  function typeSelect(value) {
    const select = document.createElement("select");
    for (const [key, label] of Object.entries({opening: "При открытии", renewal: "При продлении", closing: "При закрытии", manual: "Только вручную"})) {
      const option = new Option(label, key); option.selected = key === value; select.append(option);
    }
    return select;
  }

  function renderTariffs() {
    elements.tariffRows.replaceChildren();
    elements.penaltyRows.replaceChildren();
    state.snapshot.tariffs.forEach((row, index) => {
      const tr = document.createElement("tr");
      const input = document.createElement("input");
      input.type = "number"; input.min = "0"; input.max = "10000000"; input.required = true; input.value = String(row.price_per_day_minor); input.dataset.tariffIndex = String(index);
      input.setAttribute("aria-label", `Тариф ${row.height_mm} мм, ${periodLabel(row)}`);
      const height = document.createElement("td"); height.textContent = `${row.height_mm} мм`;
      const period = document.createElement("td"); period.textContent = periodLabel(row);
      const rate = document.createElement("td"); rate.append(input);
      tr.append(height, period, rate); elements.tariffRows.append(tr);
      if (row.period_from_days === 1 && row.period_to_days === 30) {
        const label = document.createElement("label"); label.className = "admin-penalty-card";
        const title = document.createElement("span"); title.textContent = `${row.height_mm} мм`;
        const penaltyInput = document.createElement("input");
        penaltyInput.type = "number"; penaltyInput.min = "0"; penaltyInput.max = "10000000"; penaltyInput.required = true; penaltyInput.value = input.value; penaltyInput.dataset.penaltyTariffIndex = String(index);
        penaltyInput.setAttribute("aria-label", `Штрафная ставка для высоты ${row.height_mm} мм`);
        const suffix = document.createElement("small"); suffix.textContent = "сом за день";
        label.append(title, penaltyInput, suffix); elements.penaltyRows.append(label);
        input.addEventListener("input", () => { penaltyInput.value = input.value; });
        penaltyInput.addEventListener("input", () => { input.value = penaltyInput.value; });
      }
    });
  }

  function renderTemplates() {
    elements.templateRows.replaceChildren();
    elements.templateTarget.replaceChildren(new Option("Добавить новый шаблон", ""));
    if (!state.snapshot.templates.length) {
      const empty = document.createElement("p"); empty.className = "dialog-note"; empty.textContent = "Зарегистрированных шаблонов пока нет."; elements.templateRows.append(empty);
    }
    for (const template of state.snapshot.templates) {
      const row = document.createElement("article"); row.className = "admin-template-row"; row.dataset.templateId = template.template_id;
      const controls = document.createElement("div"); controls.className = "admin-template-controls";
      const name = document.createElement("input"); name.type = "text"; name.value = template.display_name; name.maxLength = 120; name.setAttribute("aria-label", "Название шаблона");
      const type = typeSelect(template.document_type); type.setAttribute("aria-label", "Когда используется шаблон");
      const activeLabel = document.createElement("label"); activeLabel.className = "admin-checkbox";
      const active = document.createElement("input"); active.type = "checkbox"; active.checked = template.is_active; activeLabel.append(active, document.createTextNode(" Используется"));
      controls.append(name, type, activeLabel);
      const details = document.createElement("div"); details.className = "admin-template-details";
      const file = document.createElement("span"); file.textContent = `Файл: ${template.relative_file_name}`;
      const status = document.createElement("span"); status.className = template.file_present ? "template-status-ok" : "template-status-missing"; status.textContent = template.file_present ? "Файл найден" : "Файл отсутствует";
      const usage = document.createElement("span"); usage.textContent = `Использование: ${typeLabel(template.document_type)}`;
      const fields = document.createElement("span"); fields.textContent = template.required_placeholders.length ? `Заполняемые поля: ${template.required_placeholders.join(", ")}` : "Без полей: готовый документ копируется без заполнения";
      details.append(file, status, usage, fields);
      const actions = document.createElement("div"); actions.className = "admin-template-actions";
      const download = document.createElement("button"); download.type = "button"; download.className = "secondary-button"; download.dataset.action = "download-template"; download.textContent = "Получить копию"; download.disabled = !template.file_present;
      const save = document.createElement("button"); save.type = "button"; save.className = "secondary-button"; save.dataset.action = "save-template"; save.textContent = "Сохранить";
      actions.append(download, save); row.append(controls, details, actions); elements.templateRows.append(row);
      const option = new Option(`${template.display_name} — заменить файл`, template.template_id); option.dataset.displayName = template.display_name; option.dataset.documentType = template.document_type; elements.templateTarget.append(option);
    }
  }

  function renderEmployees() {
    elements.employeeRows.replaceChildren();
    if (!state.snapshot.employees.length) {
      const empty = document.createElement("p");
      empty.className = "dialog-note";
      empty.textContent = "Список пока пуст. Добавьте первого сотрудника.";
      elements.employeeRows.append(empty);
    }
    for (const employee of state.snapshot.employees) {
      const row = document.createElement("article");
      row.className = "admin-employee-row";
      row.dataset.employeeId = employee.employee_id;
      const name = document.createElement("input");
      name.type = "text";
      name.maxLength = 128;
      name.required = true;
      name.value = employee.full_name;
      name.setAttribute("aria-label", "Полное имя сотрудника");
      const activeLabel = document.createElement("label");
      activeLabel.className = "admin-checkbox";
      const active = document.createElement("input");
      active.type = "checkbox";
      active.checked = employee.is_active;
      activeLabel.append(active, document.createTextNode(" Активен"));
      const save = document.createElement("button");
      save.type = "button";
      save.className = "secondary-button";
      save.dataset.action = "save-employee";
      save.textContent = "Сохранить";
      row.append(name, activeLabel, save);
      elements.employeeRows.append(row);
    }
  }

  function renderSettings() {
    elements.expiringDays.value = String(state.snapshot.config.expiring_soon_days);
    elements.deposit.value = String(state.snapshot.config.deposit_amount_minor);
    state.accessMode = state.snapshot.access_mode;
    elements.accessPassword.checked = state.accessMode === "password";
    elements.accessAcknowledgement.checked = state.accessMode === "acknowledgement";
    renderTariffs(); renderTemplates(); renderEmployees();
  }

  async function loadSettings() {
    state.snapshot = await jsonRequest(body.dataset.adminSettingsUrl);
    renderSettings(); elements.authForm.hidden = true; elements.content.hidden = false; selectTab("general");
  }

  async function openAdmin() {
    if (!elements.dialog.open) elements.dialog.showModal();
    clearMessages(); elements.authForm.hidden = true; elements.content.hidden = true;
    try {
      const status = await jsonRequest(body.dataset.adminStatusUrl);
      state.configured = status.configured; state.accessMode = status.access_mode; setAuthMode();
      (state.accessMode === "acknowledgement" ? elements.acknowledgement : elements.password).focus();
    } catch (error) { elements.authForm.hidden = false; showError(elements.authError, error.message); }
  }

  async function authenticate(event) {
    event.preventDefault(); if (state.busy) return; state.busy = true; elements.authSubmit.disabled = true; elements.authError.hidden = true;
    try {
      let payload;
      if (state.accessMode === "acknowledgement") {
        payload = await jsonRequest(body.dataset.adminAcknowledgeUrl, {method: "POST", body: JSON.stringify({accepted: elements.acknowledgement.checked})});
      } else if (state.configured) {
        payload = await jsonRequest(body.dataset.adminLoginUrl, {method: "POST", body: JSON.stringify({password: elements.password.value})});
      } else {
        payload = await jsonRequest(body.dataset.adminSetupUrl, {method: "POST", body: JSON.stringify({operation_id: operationId(), password: elements.password.value, password_confirmation: elements.passwordConfirm.value})}); state.configured = true;
      }
      state.token = payload.token; elements.authForm.reset(); await loadSettings();
    } catch (error) { showError(elements.authError, error.message); }
    finally { state.busy = false; elements.authSubmit.disabled = false; }
  }

  function currentSettingsPayload() {
    return {
      operation_id: operationId(),
      config: {expiring_soon_days: Number(elements.expiringDays.value), deposit_amount_minor: Number(elements.deposit.value)},
      tariffs: state.snapshot.tariffs.map((row, index) => ({...row, price_per_day_minor: Number(elements.tariffRows.querySelector(`[data-tariff-index="${index}"]`).value)})),
    };
  }

  async function saveSettings(event, button, successMessage, tabName) {
    event.preventDefault(); if (state.busy) return; state.busy = true; button.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminSettingsUrl, {method: "PUT", body: JSON.stringify(currentSettingsPayload())});
      await loadSettings(); selectTab(tabName); showSuccess(payload.warning || successMessage); window.dispatchEvent(new Event("safe-cells:refresh"));
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; button.disabled = false; }
  }

  async function saveTemplate(row, button) {
    state.busy = true; button.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminTemplatesUrl, {method: "PUT", body: JSON.stringify({operation_id: operationId(), template_id: row.dataset.templateId, display_name: row.querySelector("input[type='text']").value, document_type: row.querySelector("select").value, is_active: row.querySelector("input[type='checkbox']").checked})});
      await loadSettings(); showSuccess(payload.warning || "Настройка шаблона сохранена.");
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; button.disabled = false; }
  }

  async function downloadTemplate(row, button) {
    button.disabled = true; clearMessages();
    try {
      const url = body.dataset.adminTemplateFileUrl.replace("__TEMPLATE_ID__", encodeURIComponent(row.dataset.templateId));
      const response = await fetch(url, {headers: {"X-Safe-Cells-Admin-Token": state.token}});
      if (!response.ok) { const payload = await response.json().catch(() => ({})); const error = new Error(payload.message || "Не удалось получить файл шаблона."); error.status = response.status; throw error; }
      const blob = await response.blob(); const template = state.snapshot.templates.find(item => item.template_id === row.dataset.templateId);
      const anchor = document.createElement("a"); anchor.href = URL.createObjectURL(blob); anchor.download = template?.relative_file_name || "template.docx"; anchor.click(); setTimeout(() => URL.revokeObjectURL(anchor.href), 1000);
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { button.disabled = false; }
  }

  function templateAction(event) {
    const button = event.target.closest("[data-action]"); if (!button || state.busy) return;
    const row = button.closest(".admin-template-row");
    if (button.dataset.action === "save-template") saveTemplate(row, button);
    if (button.dataset.action === "download-template") downloadTemplate(row, button);
  }

  async function saveEmployee(row, button) {
    state.busy = true; button.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminEmployeesUrl, {
        method: "PUT",
        body: JSON.stringify({
          operation_id: operationId(), employee_id: row.dataset.employeeId,
          full_name: row.querySelector("input[type='text']").value,
          is_active: row.querySelector("input[type='checkbox']").checked, create: false,
        }),
      });
      await loadSettings(); selectTab("employees"); showSuccess(payload.warning || "Данные сотрудника сохранены.");
      window.dispatchEvent(new Event("safe-cells:employees-changed"));
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; button.disabled = false; }
  }

  function employeeAction(event) {
    const button = event.target.closest("[data-action='save-employee']");
    if (!button || state.busy) return;
    saveEmployee(button.closest(".admin-employee-row"), button);
  }

  async function addEmployee(event) {
    event.preventDefault(); if (state.busy || !elements.employeeAddForm.checkValidity()) return;
    state.busy = true; elements.employeeAdd.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminEmployeesUrl, {
        method: "PUT",
        body: JSON.stringify({
          operation_id: operationId(), employee_id: operationId(),
          full_name: elements.employeeName.value, is_active: true, create: true,
        }),
      });
      elements.employeeAddForm.reset(); await loadSettings(); selectTab("employees");
      showSuccess(payload.warning || "Сотрудник добавлен.");
      window.dispatchEvent(new Event("safe-cells:employees-changed"));
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.employeeAdd.disabled = false; }
  }

  function selectTemplateTarget() {
    const option = elements.templateTarget.selectedOptions[0]; if (!option?.value) return;
    elements.templateDisplay.value = option.dataset.displayName || ""; elements.templateType.value = option.dataset.documentType || "manual";
  }

  async function uploadTemplate(event) {
    event.preventDefault(); if (state.busy || !elements.templateFile.files[0]) return; state.busy = true; elements.templateUpload.disabled = true; clearMessages();
    try {
      const form = new FormData(); form.set("operation_id", operationId()); form.set("document_type", elements.templateType.value); form.set("display_name", elements.templateDisplay.value); form.set("file", elements.templateFile.files[0]); if (elements.templateTarget.value) form.set("template_id", elements.templateTarget.value);
      const payload = await jsonRequest(body.dataset.adminTemplatesUrl, {method: "POST", body: form}); elements.templateUploadForm.reset(); await loadSettings(); selectTab("templates"); showSuccess(payload.warning || "DOCX проверен и сохранён. Поля подстановки могут отсутствовать.");
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.templateUpload.disabled = false; }
  }

  async function saveAccess(event) {
    event.preventDefault(); if (state.busy) return; state.busy = true; elements.accessSubmit.disabled = true; clearMessages();
    try {
      const mode = elements.accessPassword.checked ? "password" : "acknowledgement";
      const payload = await jsonRequest(body.dataset.adminAccessUrl, {method: "PUT", body: JSON.stringify({operation_id: operationId(), access_mode: mode})});
      state.accessMode = mode; state.snapshot.access_mode = mode; showSuccess(payload.warning || "Способ входа в настройки сохранён.");
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.accessSubmit.disabled = false; }
  }

  async function changePassword(event) {
    event.preventDefault(); if (state.busy) return; state.busy = true; elements.passwordSubmit.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminPasswordUrl, {method: "PUT", body: JSON.stringify({operation_id: operationId(), current_password: elements.currentPassword.value, new_password: elements.newPassword.value, password_confirmation: elements.newPasswordConfirm.value})});
      state.token = payload.token; elements.passwordForm.reset(); showSuccess(payload.warning || "Общий пароль отдела изменён.");
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.passwordSubmit.disabled = false; }
  }

  function sessionEnded(error) { state.token = null; setAuthMode(); showError(elements.authError, error.message); }
  async function logout(closeDialog = false) {
    const token = state.token; state.token = null; state.snapshot = null;
    if (token) fetch(body.dataset.adminLogoutUrl, {method: "POST", headers: {"X-Safe-Cells-Admin-Token": token}}).catch(() => {});
    if (closeDialog && elements.dialog.open) {
      elements.dialog.close();
      window.dispatchEvent(new Event("safe-cells:employees-changed"));
    } else setAuthMode();
  }

  elements.open.addEventListener("click", openAdmin); elements.close.addEventListener("click", () => logout(true));
  elements.dialog.addEventListener("cancel", event => {event.preventDefault(); logout(true);}); elements.authForm.addEventListener("submit", authenticate); elements.logout.addEventListener("click", () => logout(false));
  elements.tabs.forEach(tab => tab.addEventListener("click", () => selectTab(tab.dataset.adminTab)));
  elements.generalForm.addEventListener("submit", event => saveSettings(event, elements.generalSubmit, "Общие параметры сохранены.", "general"));
  elements.tariffsForm.addEventListener("submit", event => saveSettings(event, elements.tariffsSubmit, "Тарифы сохранены.", "tariffs"));
  elements.templateRows.addEventListener("click", templateAction); elements.templateTarget.addEventListener("change", selectTemplateTarget); elements.templateUploadForm.addEventListener("submit", uploadTemplate);
  elements.employeeRows.addEventListener("click", employeeAction); elements.employeeAddForm.addEventListener("submit", addEmployee);
  elements.accessForm.addEventListener("submit", saveAccess); elements.passwordForm.addEventListener("submit", changePassword);
})();
