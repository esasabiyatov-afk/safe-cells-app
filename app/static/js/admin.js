"use strict";

(() => {
  const body = document.body;
  const state = {
    configured: null, accessMode: "password", recoveryMode: false, token: null,
    snapshot: null, backups: null, legacyPreview: null, cellDraft: [], busy: false,
    legacyAbsMatches: new Map(), legacyAbsCandidates: new Map(),
    tariffPeriods: [], tariffSizes: [], tariffRates: [], newSizeRates: new Map(),
  };
  const elements = {
    open: document.getElementById("adminOpen"), dialog: document.getElementById("adminDialog"), close: document.getElementById("adminDialogClose"),
    authForm: document.getElementById("adminAuthForm"), authNote: document.getElementById("adminAuthNote"), authError: document.getElementById("adminAuthError"),
    passwordField: document.getElementById("adminPasswordField"), passwordLabel: document.getElementById("adminPasswordLabel"), password: document.getElementById("adminPassword"),
    passwordConfirmField: document.getElementById("adminPasswordConfirmField"), passwordConfirm: document.getElementById("adminPasswordConfirm"),
    acknowledgementField: document.getElementById("adminAcknowledgementField"), acknowledgement: document.getElementById("adminAcknowledgement"), authSubmit: document.getElementById("adminAuthSubmit"),
    content: document.getElementById("adminContent"), logout: document.getElementById("adminLogout"), error: document.getElementById("adminError"), success: document.getElementById("adminSuccess"),
    tabs: [...document.querySelectorAll("[data-admin-tab]")], panels: [...document.querySelectorAll("[data-admin-panel]")],
    generalForm: document.getElementById("adminGeneralForm"), tariffsForm: document.getElementById("adminTariffsForm"),
    expiringDays: document.getElementById("adminExpiringDays"), deposit: document.getElementById("adminDeposit"), absSessionMinutes: document.getElementById("adminAbsSessionMinutes"),
    displayDateWords: document.getElementById("adminDisplayDateWords"), showUiHints: document.getElementById("adminShowUiHints"),
    reminderDictionary: document.getElementById("adminReminderDictionary"), tariffRows: document.getElementById("adminTariffRows"),
    tariffPeriodRows: document.getElementById("adminTariffPeriodRows"), tariffPeriodAdd: document.getElementById("adminTariffPeriodAdd"),
    penaltyLinked: document.getElementById("adminPenaltyLinked"), penaltyManual: document.getElementById("adminPenaltyManual"), penaltyManualFields: document.getElementById("adminPenaltyManualFields"), penaltyRows: document.getElementById("adminPenaltyRows"),
    generalSubmit: document.getElementById("adminGeneralSubmit"), tariffsSubmit: document.getElementById("adminTariffsSubmit"),
    reminderTemplatesForm: document.getElementById("adminReminderTemplatesForm"), reminderExpiring: document.getElementById("adminReminderExpiring"),
    reminderOverdue: document.getElementById("adminReminderOverdue"), reminderTemplatesSubmit: document.getElementById("adminReminderTemplatesSubmit"),
    templateRows: document.getElementById("adminTemplateRows"), templateUploadForm: document.getElementById("adminTemplateUploadForm"), templateTarget: document.getElementById("adminTemplateTarget"),
    templateDisplay: document.getElementById("adminTemplateDisplay"), templateType: document.getElementById("adminTemplateType"), templateFile: document.getElementById("adminTemplateFile"), templateUpload: document.getElementById("adminTemplateUpload"),
    employeeRows: document.getElementById("adminEmployeeRows"), employeeAddForm: document.getElementById("adminEmployeeAddForm"),
    employeeName: document.getElementById("adminEmployeeName"), employeeAdd: document.getElementById("adminEmployeeAdd"),
    cellCount: document.getElementById("adminCellCount"), retiredCellCount: document.getElementById("adminRetiredCellCount"),
    cellAddForm: document.getElementById("adminCellAddForm"), cellNumber: document.getElementById("adminCellNumber"),
    cellHeight: document.getElementById("adminCellHeight"), cellWidth: document.getElementById("adminCellWidth"), cellDepth: document.getElementById("adminCellDepth"), cellAdd: document.getElementById("adminCellAdd"),
    cellDraft: document.getElementById("adminCellDraft"), cellDraftRows: document.getElementById("adminCellDraftRows"),
    cellDraftSummary: document.getElementById("adminCellDraftSummary"), cellDraftClear: document.getElementById("adminCellDraftClear"),
    cellNewTariffs: document.getElementById("adminCellNewTariffs"), cellNewTariffRows: document.getElementById("adminCellNewTariffRows"),
    cellSaveBatch: document.getElementById("adminCellSaveBatch"), cellRows: document.getElementById("adminCellRows"),
    cellSearch: document.getElementById("adminCellSearch"),
    accessForm: document.getElementById("adminAccessForm"), accessPassword: document.getElementById("adminAccessPassword"), accessAcknowledgement: document.getElementById("adminAccessAcknowledgement"), accessSubmit: document.getElementById("adminAccessSubmit"),
    passwordForm: document.getElementById("adminPasswordForm"), currentPasswordField: document.getElementById("adminCurrentPasswordField"), currentPassword: document.getElementById("adminCurrentPassword"), newPassword: document.getElementById("adminNewPassword"), newPasswordConfirm: document.getElementById("adminNewPasswordConfirm"), passwordSubmit: document.getElementById("adminPasswordSubmit"),
    backupStatus: document.getElementById("adminBackupStatus"), backupRows: document.getElementById("adminBackupRows"), backupCheck: document.getElementById("adminBackupCheck"),
    backupDetails: document.getElementById("adminBackupDetails"), legacyDetails: document.getElementById("adminLegacyDetails"),
    legacyPreviewForm: document.getElementById("adminLegacyPreviewForm"), legacyFile: document.getElementById("adminLegacyFile"), legacyPreviewButton: document.getElementById("adminLegacyPreview"),
    legacyResult: document.getElementById("adminLegacyResult"), legacySummary: document.getElementById("adminLegacySummary"), legacyIssues: document.getElementById("adminLegacyIssues"),
    legacyConfirmationField: document.getElementById("adminLegacyConfirmationField"), legacyConfirmation: document.getElementById("adminLegacyConfirmation"), legacyImport: document.getElementById("adminLegacyImport"),
    legacyAbsSection: document.getElementById("adminLegacyAbsSection"), legacyAbsMatch: document.getElementById("adminLegacyAbsMatch"), legacyAbsStatus: document.getElementById("adminLegacyAbsStatus"), legacyAbsRows: document.getElementById("adminLegacyAbsRows"), legacySkipAbs: document.getElementById("adminLegacySkipAbs"),
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

  async function absRequest(url, bodyPayload) {
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": body.dataset.privateToken,
      },
      body: JSON.stringify(bodyPayload),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && payload.login_required) {
        window.dispatchEvent(new Event("safe-cells:abs-login-required"));
      }
      throw new Error(payload.message || "Не удалось получить данные из АБС.");
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

  function updateTabAvailability() {
    for (const tab of elements.tabs) {
      tab.disabled = state.recoveryMode && tab.dataset.adminTab !== "service";
    }
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
    if (state.recoveryMode) {
      elements.authNote.textContent = acknowledgement
        ? "База недоступна. Подтвердите вход в контролируемый режим восстановления по последнему проверенному комплекту."
        : "База недоступна. Введите общий пароль для контролируемого восстановления из последнего проверенного комплекта.";
      elements.authSubmit.textContent = "Открыть режим восстановления";
    } else if (acknowledgement) {
      elements.authNote.textContent = "Пароль не требуется. Подтвердите, что административные параметры меняет руководитель отдела.";
      elements.authSubmit.textContent = "Принять и открыть настройки";
    } else if (setup) {
      elements.passwordLabel.textContent = "Создайте общий пароль отдела";
      elements.password.autocomplete = "new-password";
      elements.authSubmit.textContent = "Создать пароль и открыть настройки";
      elements.authNote.textContent = "При желании задайте любой непустой общий пароль.";
    } else {
      elements.passwordLabel.textContent = "Общий пароль отдела";
      elements.password.autocomplete = "current-password";
      elements.authSubmit.textContent = "Открыть настройки";
      elements.authNote.textContent = "Введите единый пароль, принятый в отделе.";
    }
  }

  function periodLabel(row) { return row.period_to_days === null ? `${row.period_from_days}+ дней` : `${row.period_from_days}–${row.period_to_days} дней`; }
  function sizeKey(row) { return `${row.height_mm}x${row.width_mm}x${row.depth_mm}`; }
  function sizeLabel(row) { return `${row.height_mm} × ${row.width_mm} × ${row.depth_mm}`; }
  function typeLabel(value) { return {opening: "При открытии", renewal: "При продлении", closing: "При закрытии", manual: "Только вручную"}[value] || value; }
  function typeSelect(value) {
    const select = document.createElement("select");
    for (const [key, label] of Object.entries({opening: "При открытии", renewal: "При продлении", closing: "При закрытии", manual: "Только вручную"})) {
      const option = new Option(label, key); option.selected = key === value; select.append(option);
    }
    return select;
  }

  function initializeTariffEditor() {
    state.tariffSizes = state.snapshot.cells.allowed_sizes.map(row => ({...row}));
    const firstSize = state.tariffSizes[0];
    const firstRows = firstSize
      ? state.snapshot.tariffs.filter(row => sizeKey(row) === sizeKey(firstSize))
      : [];
    state.tariffPeriods = firstRows.map(row => ({
      period_from_days: row.period_from_days,
      period_to_days: row.period_to_days,
    }));
    state.tariffRates = state.tariffSizes.map(size =>
      state.tariffPeriods.map(period => {
        const row = state.snapshot.tariffs.find(item =>
          sizeKey(item) === sizeKey(size)
          && item.period_from_days === period.period_from_days
        );
        return row?.price_per_day_minor ?? "";
      })
    );
  }

  function savedTariffPeriods() {
    const firstSize = state.snapshot.cells.allowed_sizes[0];
    if (!firstSize) return [];
    return state.snapshot.tariffs
      .filter(row => sizeKey(row) === sizeKey(firstSize))
      .sort((left, right) => left.period_from_days - right.period_from_days)
      .map(row => ({
        period_from_days: row.period_from_days,
        period_to_days: row.period_to_days,
      }));
  }

  function collectTariffRates() {
    for (const input of elements.tariffRows.querySelectorAll("[data-size-index][data-period-index]")) {
      const sizeIndex = Number(input.dataset.sizeIndex);
      const periodIndex = Number(input.dataset.periodIndex);
      if (state.tariffRates[sizeIndex]) state.tariffRates[sizeIndex][periodIndex] = input.value;
    }
  }

  function recomputePeriodStarts() {
    let start = 1;
    state.tariffPeriods.forEach((period, index) => {
      period.period_from_days = start;
      if (index === state.tariffPeriods.length - 1) {
        period.period_to_days = null;
      } else {
        const end = Number(period.period_to_days);
        period.period_to_days = Number.isInteger(end) && end >= start ? end : start;
        start = period.period_to_days + 1;
      }
    });
  }

  function renderTariffPeriods() {
    elements.tariffPeriodRows.replaceChildren();
    state.tariffPeriods.forEach((period, index) => {
      const row = document.createElement("div");
      row.className = "admin-range-row";
      const start = document.createElement("strong");
      start.textContent = `От ${period.period_from_days}`;
      row.append(start);
      if (period.period_to_days === null) {
        const open = document.createElement("span");
        open.textContent = "Без ограничения";
        row.append(open);
      } else {
        const label = document.createElement("label");
        label.append(document.createTextNode("до "));
        const input = document.createElement("input");
        input.type = "number"; input.min = String(period.period_from_days);
        input.max = "100000"; input.required = true;
        input.value = String(period.period_to_days);
        input.dataset.periodEndIndex = String(index);
        label.append(input); row.append(label);
        if (state.tariffPeriods.length > 1) {
          const remove = document.createElement("button");
          remove.type = "button"; remove.className = "secondary-button";
          remove.dataset.periodRemove = String(index); remove.textContent = "Убрать";
          row.append(remove);
        }
      }
      elements.tariffPeriodRows.append(row);
    });
  }

  function renderTariffs() {
    elements.tariffRows.replaceChildren();
    elements.penaltyRows.replaceChildren();
    state.tariffSizes.forEach((size, sizeIndex) => {
      state.tariffPeriods.forEach((period, periodIndex) => {
        const tr = document.createElement("tr");
        const input = document.createElement("input");
        input.type = "number"; input.min = "0"; input.max = "10000000";
        input.required = true; input.value = String(state.tariffRates[sizeIndex][periodIndex] ?? "");
        input.dataset.sizeIndex = String(sizeIndex);
        input.dataset.periodIndex = String(periodIndex);
        input.setAttribute("aria-label", `Тариф ${sizeLabel(size)}, ${periodLabel(period)}`);
        const sizeCell = document.createElement("td"); sizeCell.textContent = sizeLabel(size);
        const periodCell = document.createElement("td"); periodCell.textContent = periodLabel(period);
        const rate = document.createElement("td"); rate.append(input);
        tr.append(sizeCell, periodCell, rate); elements.tariffRows.append(tr);
      });
    });
    for (const row of state.snapshot.penalty.manual_rates) {
      const label = document.createElement("label"); label.className = "admin-penalty-card";
      const title = document.createElement("span"); title.textContent = `${sizeLabel(row)} мм`;
      const input = document.createElement("input");
      input.type = "number"; input.min = "0"; input.max = "10000000"; input.value = String(row.price_per_day_minor); input.dataset.penaltySize = sizeKey(row);
      input.setAttribute("aria-label", `Ручная штрафная ставка для размера ${sizeLabel(row)}`);
      const suffix = document.createElement("small"); suffix.textContent = "сом за день";
      label.append(title, input, suffix); elements.penaltyRows.append(label);
    }
    elements.penaltyLinked.checked = state.snapshot.penalty.mode === "linked";
    elements.penaltyManual.checked = state.snapshot.penalty.mode === "manual";
    updatePenaltyMode();
    renderTariffPeriods();
  }

  function updatePenaltyMode() {
    const manual = elements.penaltyManual.checked;
    elements.penaltyManualFields.hidden = !manual;
    for (const input of elements.penaltyRows.querySelectorAll("input")) {
      input.disabled = !manual;
      input.required = manual;
    }
  }

  function updatePeriodEnd(input) {
    collectTariffRates();
    const index = Number(input.dataset.periodEndIndex);
    state.tariffPeriods[index].period_to_days = Number(input.value);
    recomputePeriodStarts();
    renderTariffs();
  }

  function addTariffPeriod() {
    collectTariffRates();
    if (!state.tariffPeriods.length || state.tariffPeriods.length >= 20) return;
    const lastIndex = state.tariffPeriods.length - 1;
    const last = state.tariffPeriods[lastIndex];
    const end = last.period_from_days + 29;
    state.tariffPeriods.splice(lastIndex, 0, {
      period_from_days: last.period_from_days,
      period_to_days: end,
    });
    state.tariffRates.forEach(rates => {
      const inherited = rates[lastIndex] ?? "";
      rates.splice(lastIndex, 0, inherited);
    });
    recomputePeriodStarts();
    renderTariffs();
  }

  function removeTariffPeriod(index) {
    collectTariffRates();
    if (state.tariffPeriods.length <= 1 || index < 0 || index >= state.tariffPeriods.length - 1) return;
    state.tariffPeriods.splice(index, 1);
    state.tariffRates.forEach(rates => rates.splice(index, 1));
    recomputePeriodStarts();
    renderTariffs();
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

  function renderCellDraft() {
    for (const input of elements.cellNewTariffRows.querySelectorAll("[data-new-rate-key]")) {
      state.newSizeRates.set(input.dataset.newRateKey, input.value);
    }
    const rows = [...state.cellDraft].sort((a, b) => Number(a.number) - Number(b.number));
    elements.cellDraft.hidden = rows.length === 0;
    elements.cellDraftRows.replaceChildren();
    elements.cellDraftSummary.textContent = rows.length
      ? `Подготовлено: ${rows.length}. Проверьте каждый номер и размер.`
      : "";
    for (const cell of rows) {
      const tr = document.createElement("tr");
      const number = document.createElement("td"); number.textContent = `№${cell.number}`;
      const dimensions = document.createElement("td"); dimensions.textContent = `${sizeLabel(cell)} мм`;
      const actions = document.createElement("td");
      const remove = document.createElement("button");
      remove.type = "button"; remove.className = "secondary-button"; remove.dataset.draftRemove = cell.number; remove.textContent = "Убрать";
      actions.append(remove); tr.append(number, dimensions, actions); elements.cellDraftRows.append(tr);
    }
    const existingSizes = new Set(state.snapshot.cells.allowed_sizes.map(sizeKey));
    const newSizes = [];
    const seen = new Set();
    for (const cell of rows) {
      const key = sizeKey(cell);
      if (!existingSizes.has(key) && !seen.has(key)) {
        newSizes.push(cell);
        seen.add(key);
      }
    }
    elements.cellNewTariffs.hidden = newSizes.length === 0;
    elements.cellNewTariffRows.replaceChildren();
    for (const size of newSizes) {
      const section = document.createElement("section");
      section.className = "admin-new-size-card";
      const title = document.createElement("h5");
      title.textContent = `Размер ${sizeLabel(size)} мм`;
      const grid = document.createElement("div");
      grid.className = "admin-new-size-rate-grid";
      savedTariffPeriods().forEach((period, index) => {
        const label = document.createElement("label");
        label.className = "contract-field";
        const caption = document.createElement("span");
        caption.textContent = periodLabel(period);
        const input = document.createElement("input");
        input.type = "number"; input.min = "0"; input.max = "10000000";
        input.required = true;
        input.dataset.newRateKey = `${sizeKey(size)}|${index}`;
        input.value = state.newSizeRates.get(input.dataset.newRateKey) || "";
        label.append(caption, input); grid.append(label);
      });
      if (state.snapshot.penalty.mode === "manual") {
        const label = document.createElement("label");
        label.className = "contract-field";
        const caption = document.createElement("span");
        caption.textContent = "Штраф за день";
        const input = document.createElement("input");
        input.type = "number"; input.min = "0"; input.max = "10000000";
        input.required = true;
        input.dataset.newRateKey = `penalty:${sizeKey(size)}`;
        input.value = state.newSizeRates.get(input.dataset.newRateKey) || "";
        label.append(caption, input); grid.append(label);
      }
      section.append(title, grid);
      elements.cellNewTariffRows.append(section);
    }
  }

  function renderCellRows() {
    elements.cellRows.replaceChildren();
    const query = elements.cellSearch.value.trim();
    const cells = state.snapshot.cells.items.filter(cell => !query || cell.number.includes(query));
    for (const cell of cells) {
      const tr = document.createElement("tr");
      if (!cell.is_active) tr.classList.add("is-retired");
      const number = document.createElement("td"); number.textContent = `№${cell.number}`;
      const dimensions = document.createElement("td"); dimensions.textContent = `${sizeLabel(cell)} мм`;
      const status = document.createElement("td");
      status.textContent = cell.is_active
        ? (cell.is_occupied ? "Действует · занята" : "Действует · свободна")
        : `Выведена${cell.retirement_reason ? ` · ${cell.retirement_reason}` : ""}`;
      const actions = document.createElement("td"); actions.className = "admin-cell-actions";
      if (cell.is_active && !cell.is_occupied) {
        const retire = document.createElement("button");
        retire.type = "button"; retire.className = "secondary-button"; retire.dataset.cellAction = "retire"; retire.dataset.cellNumber = cell.number; retire.textContent = "Вывести";
        actions.append(retire);
      } else if (!cell.is_active) {
        const restore = document.createElement("button");
        restore.type = "button"; restore.className = "secondary-button"; restore.dataset.cellAction = "restore"; restore.dataset.cellNumber = cell.number; restore.textContent = "Вернуть";
        actions.append(restore);
      }
      if (!cell.is_occupied && cell.created_in_admin) {
        const remove = document.createElement("button");
        remove.type = "button"; remove.className = "secondary-button danger-outline"; remove.dataset.cellAction = "delete"; remove.dataset.cellNumber = cell.number; remove.textContent = "Удалить ошибочную";
        actions.append(remove);
      }
      tr.append(number, dimensions, status, actions); elements.cellRows.append(tr);
    }
    if (!cells.length) {
      const tr = document.createElement("tr"); const td = document.createElement("td");
      td.colSpan = 4; td.textContent = "Ячейки с таким номером не найдены."; tr.append(td); elements.cellRows.append(tr);
    }
  }

  function renderSettings() {
    elements.expiringDays.value = String(state.snapshot.config.expiring_soon_days);
    elements.deposit.value = String(state.snapshot.config.deposit_amount_minor);
    elements.absSessionMinutes.value = String(state.snapshot.config.abs_session_minutes);
    elements.displayDateWords.checked = state.snapshot.config.display_date_words === true;
    elements.showUiHints.checked = state.snapshot.config.show_ui_hints === true;
    elements.reminderExpiring.value = state.snapshot.reminder_templates.expiring;
    elements.reminderOverdue.value = state.snapshot.reminder_templates.overdue;
    elements.cellCount.textContent = String(state.snapshot.cells.count);
    elements.retiredCellCount.textContent = String(state.snapshot.cells.retired_count);
    initializeTariffEditor();
    state.accessMode = state.snapshot.access_mode;
    elements.accessPassword.checked = state.accessMode === "password";
    elements.accessAcknowledgement.checked = state.accessMode === "acknowledgement";
    const passwordConfigured = state.snapshot.password_configured === true;
    elements.accessPassword.disabled = !passwordConfigured;
    elements.currentPasswordField.hidden = !passwordConfigured;
    elements.currentPassword.required = passwordConfigured;
    elements.passwordSubmit.textContent = passwordConfigured
      ? "Сменить общий пароль"
      : "Создать и включить пароль";
    renderTariffs(); renderTemplates(); renderEmployees(); renderCellDraft(); renderCellRows(); renderReminderDictionary();
  }

  function renderReminderDictionary() {
    elements.reminderDictionary.replaceChildren();
    let currentGroup = "";
    for (const item of state.snapshot.template_fields || []) {
      if (item.group !== currentGroup) {
        currentGroup = item.group;
        const heading = document.createElement("h4");
        heading.className = "admin-placeholder-group";
        heading.textContent = currentGroup;
        elements.reminderDictionary.append(heading);
      }
      const row = document.createElement("article");
      row.className = "admin-placeholder-row";
      const code = document.createElement("button");
      code.type = "button";
      code.className = "admin-placeholder-code";
      code.dataset.placeholderCopy = item.code;
      code.textContent = item.code;
      code.title = "Скопировать код";
      const description = document.createElement("span");
      description.textContent = item.description;
      const usage = document.createElement("small");
      usage.className = "admin-placeholder-usage";
      usage.textContent = item.usage;
      const details = document.createElement("span");
      details.className = "admin-placeholder-description";
      details.append(description, usage);
      row.append(code, details);
      elements.reminderDictionary.append(row);
    }
  }

  function formatBytes(value) {
    if (!Number.isFinite(value)) return "—";
    if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} КБ`;
    return `${(value / 1024 / 1024).toFixed(1)} МБ`;
  }

  function renderBackups() {
    const snapshot = state.backups;
    elements.backupRows.replaceChildren();
    elements.backupStatus.replaceChildren();
    const integrity = document.createElement("strong");
    integrity.textContent = snapshot.integrity.write_blocked
      ? "Запись заблокирована: обнаружено повреждение базы"
      : snapshot.integrity.working === "ok" && snapshot.integrity.archive === "ok"
        ? "Обе активные базы прошли quick_check"
        : "Проверка активных баз не завершена";
    const details = document.createElement("span");
    const other = snapshot.instances.other_active;
    details.textContent = `Рабочая: ${snapshot.integrity.working}; архивная: ${snapshot.integrity.archive}; проверенных комплектов: ${snapshot.valid_count}; других активных экземпляров: ${other === null ? "не удалось проверить" : other}.`;
    elements.backupStatus.append(integrity, details);
    if (!snapshot.sets.length) {
      const empty = document.createElement("p"); empty.className = "dialog-note"; empty.textContent = "Завершённых резервных комплектов пока нет."; elements.backupRows.append(empty); return;
    }
    for (const item of snapshot.sets) {
      const row = document.createElement("article"); row.className = `admin-backup-row ${item.valid ? "is-valid" : "is-invalid"}`;
      const summary = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = item.valid ? new Date(item.created_at).toLocaleString("ru-RU") : "Непроверенный комплект";
      const status = document.createElement("span"); status.textContent = item.valid ? "Проверен: quick_check и SHA-256 совпадают" : item.error;
      summary.append(title, status);
      const sizes = document.createElement("span"); sizes.textContent = item.valid ? `Рабочая ${formatBytes(item.files.working.size)}, архивная ${formatBytes(item.files.archive.size)}` : "Восстановление запрещено";
      const restore = document.createElement("button"); restore.type = "button"; restore.className = "secondary-button"; restore.dataset.action = "restore-backup"; restore.dataset.setId = item.set_id; restore.textContent = "Восстановить комплект"; restore.disabled = !item.valid || !snapshot.restore_allowed;
      row.append(summary, sizes, restore); elements.backupRows.append(row);
    }
  }

  async function loadBackups() {
    state.backups = await jsonRequest(body.dataset.adminBackupsUrl);
    renderBackups();
  }

  async function loadSettings() {
    state.snapshot = await jsonRequest(body.dataset.adminSettingsUrl);
    renderSettings(); elements.authForm.hidden = true; elements.content.hidden = false; selectTab("general");
  }

  async function openAdmin() {
    if (!elements.dialog.open) elements.dialog.showModal();
    clearMessages(); elements.authForm.hidden = true; elements.content.hidden = true;
    if (state.token && !state.recoveryMode) {
      try {
        await loadSettings();
      } catch (error) {
        if (error.status === 401) return sessionEnded(error);
        elements.authForm.hidden = false;
        showError(elements.authError, error.message);
      }
      return;
    }
    try {
      const status = await jsonRequest(body.dataset.adminStatusUrl);
      state.configured = status.configured; state.accessMode = status.access_mode; state.recoveryMode = status.recovery_mode === true; updateTabAvailability(); setAuthMode();
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
      state.token = payload.token; elements.authForm.reset();
      if (state.recoveryMode) {
        elements.authForm.hidden = true; elements.content.hidden = false; await loadBackups(); selectTab("service"); elements.backupDetails.open = true;
      } else await loadSettings();
    } catch (error) { showError(elements.authError, error.message); }
    finally { state.busy = false; elements.authSubmit.disabled = false; }
  }

  function currentSettingsPayload() {
    collectTariffRates();
    const tariffs = [];
    state.tariffSizes.forEach((size, sizeIndex) => {
      state.tariffPeriods.forEach((period, periodIndex) => {
        tariffs.push({
          ...size,
          period_from_days: period.period_from_days,
          period_to_days: period.period_to_days,
          price_per_day_minor: Number(state.tariffRates[sizeIndex][periodIndex]),
        });
      });
    });
    return {
      operation_id: operationId(),
      config: {
        expiring_soon_days: Number(elements.expiringDays.value),
        deposit_amount_minor: Number(elements.deposit.value),
        abs_session_minutes: Number(elements.absSessionMinutes.value),
        display_date_words: elements.displayDateWords.checked,
        show_ui_hints: elements.showUiHints.checked,
      },
      tariffs,
      penalty: {
        mode: elements.penaltyManual.checked ? "manual" : "linked",
        manual_rates: state.snapshot.penalty.manual_rates.map(row => ({
          height_mm: row.height_mm,
          width_mm: row.width_mm,
          depth_mm: row.depth_mm,
          price_per_day_minor: Number(elements.penaltyRows.querySelector(`[data-penalty-size="${sizeKey(row)}"]`).value),
        })),
      },
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

  async function saveReminderTemplates(event) {
    event.preventDefault(); if (state.busy || !elements.reminderTemplatesForm.checkValidity()) return;
    state.busy = true; elements.reminderTemplatesSubmit.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminReminderTemplatesUrl, {
        method: "PUT",
        body: JSON.stringify({
          operation_id: operationId(),
          templates: {
            expiring: elements.reminderExpiring.value,
            overdue: elements.reminderOverdue.value,
          },
        }),
      });
      await loadSettings(); selectTab("templates");
      showSuccess(payload.warning || "Тексты WhatsApp сохранены.");
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally {
      state.busy = false; elements.reminderTemplatesSubmit.disabled = false;
    }
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

  function addCell(event) {
    event.preventDefault(); if (!elements.cellAddForm.checkValidity()) return;
    const number = String(Number(elements.cellNumber.value));
    if (state.cellDraft.some(cell => cell.number === number) || state.snapshot.cells.items.some(cell => cell.number === number)) {
      showError(elements.error, `Ячейка №${number} уже есть в базе или подготовленном списке.`); return;
    }
    state.cellDraft.push({
      number,
      height_mm: Number(elements.cellHeight.value),
      width_mm: Number(elements.cellWidth.value),
      depth_mm: Number(elements.cellDepth.value),
    });
    elements.cellNumber.value = ""; clearMessages(); renderCellDraft(); elements.cellNumber.focus();
  }

  async function saveCellBatch() {
    if (state.busy || !state.cellDraft.length) return;
    state.busy = true; elements.cellSaveBatch.disabled = true; clearMessages();
    try {
      for (const input of elements.cellNewTariffRows.querySelectorAll("[data-new-rate-key]")) {
        if (!input.checkValidity() || input.value === "") {
          input.reportValidity();
          throw new Error("Заполните все тарифы для новых размеров.");
        }
        state.newSizeRates.set(input.dataset.newRateKey, input.value);
      }
      const existingSizes = new Set(state.snapshot.cells.allowed_sizes.map(sizeKey));
      const newSizes = [];
      const seen = new Set();
      for (const cell of state.cellDraft) {
        const key = sizeKey(cell);
        if (!existingSizes.has(key) && !seen.has(key)) {
          newSizes.push(cell); seen.add(key);
        }
      }
      const newTariffs = [];
      const newPenaltyRates = [];
      for (const size of newSizes) {
        savedTariffPeriods().forEach((period, index) => {
          newTariffs.push({
            height_mm: size.height_mm,
            width_mm: size.width_mm,
            depth_mm: size.depth_mm,
            period_from_days: period.period_from_days,
            period_to_days: period.period_to_days,
            price_per_day_minor: Number(state.newSizeRates.get(`${sizeKey(size)}|${index}`)),
          });
        });
        if (state.snapshot.penalty.mode === "manual") {
          newPenaltyRates.push({
            height_mm: size.height_mm,
            width_mm: size.width_mm,
            depth_mm: size.depth_mm,
            price_per_day_minor: Number(state.newSizeRates.get(`penalty:${sizeKey(size)}`)),
          });
        }
      }
      const payload = await jsonRequest(body.dataset.adminCellsUrl, {
        method: "POST",
        body: JSON.stringify({
          operation_id: operationId(),
          cells: state.cellDraft,
          new_tariffs: newTariffs,
          new_penalty_rates: newPenaltyRates,
        }),
      });
      const count = payload.cells.length; state.cellDraft = []; state.newSizeRates.clear();
      await loadSettings(); selectTab("cells"); showSuccess(payload.warning || `Сохранено новых ячеек: ${count}.`);
      window.dispatchEvent(new Event("safe-cells:refresh"));
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally {
      state.busy = false; elements.cellSaveBatch.disabled = false;
    }
  }

  async function changeCellLifecycle(button) {
    if (state.busy) return;
    const action = button.dataset.cellAction; const number = button.dataset.cellNumber;
    let reason = "";
    if (action === "retire") {
      reason = window.prompt(`Укажите причину вывода ячейки №${number} из эксплуатации:`) || "";
      if (!reason.trim()) return;
    }
    const questions = {
      retire: `Вывести свободную ячейку №${number} из эксплуатации?`,
      restore: `Вернуть ячейку №${number} в работу?`,
      delete: `Окончательно удалить ошибочно добавленную пустую ячейку №${number}?`,
    };
    if (!window.confirm(questions[action])) return;
    state.busy = true; button.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminCellsLifecycleUrl, {
        method: "PUT",
        body: JSON.stringify({operation_id: operationId(), number, action, reason}),
      });
      await loadSettings(); selectTab("cells");
      const messages = {retire: `Ячейка №${number} выведена из эксплуатации.`, restore: `Ячейка №${number} возвращена в работу.`, delete: `Ошибочная ячейка №${number} удалена.`};
      showSuccess(payload.warning || messages[action]); window.dispatchEvent(new Event("safe-cells:refresh"));
    } catch (error) {
      if (error.status === 401) return sessionEnded(error);
      showError(elements.error, error.message);
    } finally { state.busy = false; button.disabled = false; }
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
      const creating = state.snapshot.password_configured !== true;
      const payload = await jsonRequest(body.dataset.adminPasswordUrl, {method: "PUT", body: JSON.stringify({operation_id: operationId(), current_password: elements.currentPassword.value, new_password: elements.newPassword.value, password_confirmation: elements.newPasswordConfirm.value})});
      state.token = payload.token; elements.passwordForm.reset(); await loadSettings(); selectTab("access"); showSuccess(payload.warning || (creating ? "Общий пароль создан и включён." : "Общий пароль отдела изменён."));
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.passwordSubmit.disabled = false; }
  }

  async function checkBackups() {
    if (state.busy) return; state.busy = true; elements.backupCheck.disabled = true; clearMessages();
    try {
      await jsonRequest(body.dataset.adminBackupsCheckUrl, {method: "POST"}); await loadBackups(); showSuccess("Проверка целостности завершена.");
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.backupCheck.disabled = false; }
  }

  function resetLegacyPreview() {
    state.legacyPreview = null;
    state.legacyAbsMatches.clear();
    state.legacyAbsCandidates.clear();
    elements.legacyResult.hidden = true;
    elements.legacyIssues.replaceChildren();
    elements.legacyConfirmation.checked = false;
    elements.legacyConfirmationField.hidden = true;
    elements.legacyAbsSection.hidden = true;
    elements.legacyAbsRows.replaceChildren();
    elements.legacyAbsStatus.textContent = "";
    elements.legacySkipAbs.checked = false;
    elements.legacyImport.disabled = true;
  }

  function legacyRows() {
    return Array.isArray(state.legacyPreview?.abs_lookup_rows)
      ? state.legacyPreview.abs_lookup_rows : [];
  }

  function updateLegacyImportAvailability() {
    const rows = legacyRows();
    const absReady = !rows.length
      || state.legacyAbsMatches.size === rows.length
      || elements.legacySkipAbs.checked;
    elements.legacyImport.disabled = !(
      state.legacyPreview?.ready && elements.legacyConfirmation.checked && absReady
    );
  }

  function renderLegacyAbsRows() {
    elements.legacyAbsRows.replaceChildren();
    for (const row of legacyRows()) {
      const card = document.createElement("div");
      card.className = "admin-section";
      const heading = document.createElement("strong");
      heading.textContent = `Ячейка № ${row.cell_number}: ${row.client_full_name}`;
      card.append(heading);
      const match = state.legacyAbsMatches.get(row.cell_number);
      if (match) {
        const status = document.createElement("p");
        status.className = "template-status-ok";
        status.textContent = `Привязан клиент ID ${match.abs_customer_id}. Телефоны получены.`;
        card.append(status);
      } else {
        const candidates = state.legacyAbsCandidates.get(row.cell_number);
        if (Array.isArray(candidates) && candidates.length) {
          const note = document.createElement("p");
          note.textContent = "Найдено несколько клиентов. Выберите правильного:";
          card.append(note);
          const actions = document.createElement("div");
          actions.className = "dialog-actions";
          for (const candidate of candidates) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "secondary-button";
            button.textContent = candidate.summary || `Клиент ID ${candidate.customer_id}`;
            button.addEventListener("click", async () => {
              button.disabled = true;
              try {
                await selectLegacyAbsCustomer(row, candidate.customer_id);
              } catch (error) {
                elements.legacyAbsStatus.textContent = error.message;
              } finally {
                button.disabled = false;
              }
            });
            actions.append(button);
          }
          card.append(actions);
        } else if (candidates === null) {
          const missing = document.createElement("p");
          missing.textContent = "Совпадений не найдено. Можно повторить поиск или перенести без привязки.";
          card.append(missing);
        }
      }
      elements.legacyAbsRows.append(card);
    }
    updateLegacyImportAvailability();
  }

  async function selectLegacyAbsCustomer(row, customerId) {
    const payload = await absRequest(body.dataset.absCustomerUrl, {customer_id: customerId});
    if (!payload.client_phone && !payload.client_whatsapp_phone) {
      throw new Error(`У клиента для ячейки № ${row.cell_number} не найден ни один телефон.`);
    }
    state.legacyAbsMatches.set(row.cell_number, {
      cell_number: row.cell_number,
      abs_customer_id: payload.abs_customer_id,
      client_full_name: payload.client_full_name || row.client_full_name,
      client_phone: payload.client_phone || null,
      client_whatsapp_phone: payload.client_whatsapp_phone || null,
    });
    state.legacyAbsCandidates.delete(row.cell_number);
    renderLegacyAbsRows();
  }

  async function matchLegacyAbsClients() {
    if (!state.legacyPreview?.ready) return;
    elements.legacyAbsMatch.disabled = true;
    elements.legacyAbsStatus.textContent = "Выполняется поиск по ФИО…";
    try {
      for (const row of legacyRows()) {
        if (state.legacyAbsMatches.has(row.cell_number)) continue;
        const payload = await absRequest(body.dataset.absSearchUrl, {
          query: row.client_full_name,
        });
        const results = Array.isArray(payload.results) ? payload.results : [];
        if (results.length === 1) {
          await selectLegacyAbsCustomer(row, results[0].customer_id);
        } else {
          state.legacyAbsCandidates.set(
            row.cell_number, results.length ? results : null,
          );
        }
        renderLegacyAbsRows();
      }
      const total = legacyRows().length;
      const matched = state.legacyAbsMatches.size;
      elements.legacyAbsStatus.textContent = matched === total
        ? `Все договоры сопоставлены с АБС: ${matched}.`
        : `Сопоставлено ${matched} из ${total}. Для дублей выберите клиента вручную.`;
    } catch (error) {
      elements.legacyAbsStatus.textContent = `${error.message} После входа нажмите поиск ещё раз.`;
    } finally {
      elements.legacyAbsMatch.disabled = false;
      renderLegacyAbsRows();
    }
  }

  function renderLegacyPreview(payload) {
    state.legacyPreview = payload;
    elements.legacyIssues.replaceChildren();
    elements.legacyResult.hidden = false;
    elements.legacySummary.textContent = `Всего ячеек: ${payload.cells_count}. Договоров: ${payload.contracts_count}. Свободных: ${payload.free_count}. Служебно занятых: ${payload.manual_count}. Строк с паспортными данными: ${payload.passport_details_count}. Полных реквизитов: ${payload.identity_complete_count}. Известных залогов: ${payload.deposit_known_count}.`;
    for (const issue of payload.issues) {
      const item = document.createElement("li");
      item.textContent = issue.cell_number ? `Ячейка № ${issue.cell_number}: ${issue.message}` : issue.message;
      elements.legacyIssues.append(item);
    }
    if (!payload.issues.length) {
      const item = document.createElement("li");
      item.textContent = "Ошибок не найдено. Запись ещё не выполнялась.";
      item.className = "template-status-ok";
      elements.legacyIssues.append(item);
    }
    elements.legacyConfirmation.checked = false;
    elements.legacyConfirmationField.hidden = !payload.ready;
    elements.legacyAbsSection.hidden = !payload.ready || !legacyRows().length;
    renderLegacyAbsRows();
    elements.legacyImport.disabled = true;
  }

  async function previewLegacyImport(event) {
    event.preventDefault();
    if (state.busy || !elements.legacyFile.files[0]) return;
    state.busy = true; elements.legacyPreviewButton.disabled = true; clearMessages(); resetLegacyPreview();
    try {
      const form = new FormData(); form.set("file", elements.legacyFile.files[0]);
      const payload = await jsonRequest(body.dataset.adminLegacyPreviewUrl, {method: "POST", body: form});
      renderLegacyPreview(payload);
      if (!payload.ready) showError(elements.error, "Исправьте перечисленные ошибки в Excel и проверьте файл заново.");
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; elements.legacyPreviewButton.disabled = false; }
  }

  async function confirmLegacyImport() {
    if (state.busy || !state.legacyPreview?.ready || !elements.legacyConfirmation.checked || !elements.legacyFile.files[0]) return;
    const accepted = window.confirm("Будут перенесены все старые договоры одним действием. Перед записью приложение создаст резервную копию обеих баз. Продолжить?");
    if (!accepted) return;
    state.busy = true; elements.legacyImport.disabled = true; clearMessages();
    try {
      const form = new FormData();
      form.set("file", elements.legacyFile.files[0]);
      form.set("expected_sha256", state.legacyPreview.sha256);
      form.set("confirmation", state.legacyPreview.confirmation);
      form.set("operation_id", operationId());
      form.set("abs_matches", JSON.stringify([...state.legacyAbsMatches.values()]));
      const payload = await jsonRequest(body.dataset.adminLegacyConfirmUrl, {method: "POST", body: form});
      elements.legacyPreviewForm.reset(); resetLegacyPreview();
      showSuccess(payload.warning || `Перенесено договоров: ${payload.contracts_count}. Главный экран обновлён.`);
      window.dispatchEvent(new Event("safe-cells:refresh"));
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; updateLegacyImportAvailability(); }
  }

  async function restoreBackup(button) {
    if (state.busy || !state.backups?.restore_allowed) return;
    const accepted = window.confirm("Закройте приложение на других компьютерах. Повреждённые текущие файлы будут сохранены отдельно. Продолжить восстановление обеих баз?");
    if (!accepted) return;
    state.busy = true; button.disabled = true; clearMessages();
    try {
      const payload = await jsonRequest(body.dataset.adminBackupsRestoreUrl, {method: "POST", body: JSON.stringify({operation_id: operationId(), set_id: button.dataset.setId, confirmation: state.backups.restore_confirmation})});
      state.recoveryMode = false; updateTabAvailability(); await loadSettings(); await loadBackups(); selectTab("service"); elements.backupDetails.open = true; showSuccess(payload.warning || "Обе базы восстановлены. Повреждённые исходные файлы сохранены отдельно."); window.dispatchEvent(new Event("safe-cells:refresh"));
    } catch (error) { if (error.status === 401) return sessionEnded(error); showError(elements.error, error.message); }
    finally { state.busy = false; button.disabled = false; }
  }

  function backupAction(event) {
    const button = event.target.closest("[data-action='restore-backup']");
    if (button) restoreBackup(button);
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

  function closeSettings() {
    if (elements.dialog.open) elements.dialog.close();
  }

  window.addEventListener("safe-cells:admin-session", (event) => {
    state.token = event.detail?.token || null;
    state.snapshot = null;
    if (!state.token && elements.dialog.open) elements.dialog.close();
  });

  elements.open.addEventListener("click", openAdmin); elements.close.addEventListener("click", closeSettings);
  elements.dialog.addEventListener("cancel", event => event.preventDefault()); elements.authForm.addEventListener("submit", authenticate); elements.logout.addEventListener("click", closeSettings);
  elements.tabs.forEach(tab => tab.addEventListener("click", async () => {
    selectTab(tab.dataset.adminTab);
    if (tab.dataset.adminTab === "service" && state.token) {
      try { await loadBackups(); } catch (error) { showError(elements.error, error.message); }
    }
  }));
  elements.penaltyLinked.addEventListener("change", updatePenaltyMode); elements.penaltyManual.addEventListener("change", updatePenaltyMode);
  elements.tariffPeriodAdd.addEventListener("click", addTariffPeriod);
  elements.tariffPeriodRows.addEventListener("change", event => {
    const input = event.target.closest("[data-period-end-index]");
    if (input) updatePeriodEnd(input);
  });
  elements.tariffPeriodRows.addEventListener("click", event => {
    const button = event.target.closest("[data-period-remove]");
    if (button) removeTariffPeriod(Number(button.dataset.periodRemove));
  });
  elements.generalForm.addEventListener("submit", event => saveSettings(event, elements.generalSubmit, "Общие параметры сохранены.", "general"));
  elements.tariffsForm.addEventListener("submit", event => saveSettings(event, elements.tariffsSubmit, "Тарифы сохранены.", "tariffs"));
  elements.reminderTemplatesForm.addEventListener("submit", saveReminderTemplates);
  elements.reminderDictionary.addEventListener("click", async event => {
    const button = event.target.closest("[data-placeholder-copy]");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.placeholderCopy);
      showSuccess(`Скопировано: ${button.dataset.placeholderCopy}`);
    } catch {
      showError(elements.error, "Не удалось скопировать код. Выделите его вручную.");
    }
  });
  elements.templateRows.addEventListener("click", templateAction); elements.templateTarget.addEventListener("change", selectTemplateTarget); elements.templateUploadForm.addEventListener("submit", uploadTemplate);
  elements.employeeRows.addEventListener("click", employeeAction); elements.employeeAddForm.addEventListener("submit", addEmployee);
  elements.cellAddForm.addEventListener("submit", addCell);
  elements.cellDraftRows.addEventListener("click", event => {
    const button = event.target.closest("[data-draft-remove]"); if (!button) return;
    state.cellDraft = state.cellDraft.filter(cell => cell.number !== button.dataset.draftRemove);
    renderCellDraft();
  });
  elements.cellDraftClear.addEventListener("click", () => {
    state.cellDraft = []; state.newSizeRates.clear(); renderCellDraft();
  });
  elements.cellSaveBatch.addEventListener("click", saveCellBatch);
  elements.cellRows.addEventListener("click", event => {
    const button = event.target.closest("[data-cell-action]"); if (button) changeCellLifecycle(button);
  });
  elements.cellSearch.addEventListener("input", renderCellRows);
  elements.accessForm.addEventListener("submit", saveAccess); elements.passwordForm.addEventListener("submit", changePassword);
  elements.backupCheck.addEventListener("click", checkBackups); elements.backupRows.addEventListener("click", backupAction);
  elements.legacyPreviewForm.addEventListener("submit", previewLegacyImport);
  elements.legacyFile.addEventListener("change", resetLegacyPreview);
  elements.legacyConfirmation.addEventListener("change", updateLegacyImportAvailability);
  elements.legacySkipAbs.addEventListener("change", updateLegacyImportAvailability);
  elements.legacyAbsMatch.addEventListener("click", matchLegacyAbsClients);
  elements.legacyImport.addEventListener("click", confirmLegacyImport);
})();
