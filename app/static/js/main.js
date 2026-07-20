"use strict";

const STATUS_LABELS = {
  free: "Свободна",
  normal: "В норме",
  expiring: "Истекает",
  overdue: "Просрочена",
};

const NETWORK_ERROR_MESSAGE = "Не удалось получить данные с сетевого диска. Проверьте подключение к сети";

const state = {
  cells: [],
  counts: { free: 0, normal: 0, expiring: 0, overdue: 0 },
  privateMatches: null,
  searchSequence: 0,
  asOfDate: null,
  activeRentalCell: null,
  activeQuote: null,
  activeOperationId: null,
  contractSubmitting: false,
  statementImporting: false,
  statementImportSequence: 0,
  quoteSequence: 0,
  activeOccupiedCell: null,
  clientNameRequestSequence: 0,
  privateRequestSequence: 0,
  privateVisible: false,
  activeRenewalQuote: null,
  renewalOperationId: null,
  renewalQuoteSequence: 0,
  renewalSubmitting: false,
  activeClosureQuote: null,
  closureOperationId: null,
  closureQuoteSequence: 0,
  closureSubmitting: false,
  editOperationId: null,
  editSubmitting: false,
  documentSubmitting: false,
  employeeSubmitting: false,
  manualOperationId: null,
  blockOperationId: null,
  blockSubmitting: false,
};

const elements = {
  body: document.body,
  grid: document.getElementById("vaultGrid"),
  empty: document.getElementById("emptyState"),
  search: document.getElementById("searchInput"),
  status: document.getElementById("statusFilter"),
  height: document.getElementById("heightFilter"),
  errorBanner: document.getElementById("errorBanner"),
  errorMessage: document.getElementById("errorMessage"),
  successBanner: document.getElementById("successBanner"),
  successMessage: document.getElementById("successMessage"),
  connection: document.getElementById("connectionState"),
  updatedAt: document.getElementById("updatedAt"),
  resultCount: document.getElementById("resultCount"),
  statFree: document.getElementById("statFree"),
  statOccupied: document.getElementById("statOccupied"),
  statNormal: document.getElementById("statNormal"),
  statExpiring: document.getElementById("statExpiring"),
  statOverdue: document.getElementById("statOverdue"),
  dialog: document.getElementById("cellDialog"),
  dialogClose: document.getElementById("dialogClose"),
  dialogTitle: document.getElementById("dialogTitle"),
  dialogStatus: document.getElementById("dialogStatus"),
  dialogSize: document.getElementById("dialogSize"),
  dialogClientLabel: document.getElementById("dialogClientLabel"),
  dialogClient: document.getElementById("dialogClient"),
  dialogStartDate: document.getElementById("dialogStartDate"),
  dialogEndDate: document.getElementById("dialogEndDate"),
  dialogRentDays: document.getElementById("dialogRentDays"),
  dialogDays: document.getElementById("dialogDays"),
  cellDialogKicker: document.getElementById("cellDialogKicker"),
  privateCardSection: document.getElementById("privateCardSection"),
  contractCardActions: document.getElementById("contractCardActions"),
  blockedCardActions: document.getElementById("blockedCardActions"),
  blockedActionError: document.getElementById("blockedActionError"),
  blockReleaseAction: document.getElementById("blockReleaseAction"),
  privateToggle: document.getElementById("privateToggle"),
  privateError: document.getElementById("privateError"),
  privateDetails: document.getElementById("privateDetails"),
  privateIdCardNumber: document.getElementById("privateIdCardNumber"),
  privateIdCardIssuer: document.getElementById("privateIdCardIssuer"),
  privateIdCardIssueDate: document.getElementById("privateIdCardIssueDate"),
  privateAccountNumber: document.getElementById("privateAccountNumber"),
  privateCreatedAt: document.getElementById("privateCreatedAt"),
  privateCreatedBy: document.getElementById("privateCreatedBy"),
  historyControls: document.getElementById("historyControls"),
  historyToggle: document.getElementById("historyToggle"),
  renewalHistory: document.getElementById("renewalHistory"),
  renewalEmpty: document.getElementById("renewalEmpty"),
  renewalList: document.getElementById("renewalList"),
  renewAction: document.getElementById("renewAction"),
  renewalDialog: document.getElementById("renewalDialog"),
  renewalDialogClose: document.getElementById("renewalDialogClose"),
  renewalDialogTitle: document.getElementById("renewalDialogTitle"),
  renewalCellSummary: document.getElementById("renewalCellSummary"),
  renewalForm: document.getElementById("renewalForm"),
  renewalOldEnd: document.getElementById("renewalOldEnd"),
  renewalDate: document.getElementById("renewalDate"),
  renewalNewStart: document.getElementById("renewalNewStart"),
  renewalEndDate: document.getElementById("renewalEndDate"),
  renewalDays: document.getElementById("renewalDays"),
  renewalError: document.getElementById("renewalError"),
  renewalPeriod: document.getElementById("renewalPeriod"),
  renewalTariff: document.getElementById("renewalTariff"),
  renewalPrice: document.getElementById("renewalPrice"),
  renewalPenaltyDays: document.getElementById("renewalPenaltyDays"),
  renewalPenaltyPanel: document.getElementById("renewalPenaltyPanel"),
  renewalPenaltyAmount: document.getElementById("renewalPenaltyAmount"),
  renewalTotal: document.getElementById("renewalTotal"),
  renewalBack: document.getElementById("renewalBack"),
  renewalSubmit: document.getElementById("renewalSubmit"),
  closeAction: document.getElementById("closeAction"),
  editAction: document.getElementById("editAction"),
  editDialog: document.getElementById("editDialog"),
  editDialogClose: document.getElementById("editDialogClose"),
  editDialogTitle: document.getElementById("editDialogTitle"),
  editForm: document.getElementById("editForm"),
  editError: document.getElementById("editError"),
  editClientFullName: document.getElementById("editClientFullName"),
  editAccountNumber: document.getElementById("editAccountNumber"),
  editIdCardNumber: document.getElementById("editIdCardNumber"),
  editIdCardIssuer: document.getElementById("editIdCardIssuer"),
  editIdCardIssueDate: document.getElementById("editIdCardIssueDate"),
  editBack: document.getElementById("editBack"),
  editSubmit: document.getElementById("editSubmit"),
  documentAction: document.getElementById("documentAction"),
  documentDialog: document.getElementById("documentDialog"),
  documentDialogClose: document.getElementById("documentDialogClose"),
  documentForm: document.getElementById("documentForm"),
  documentTemplate: document.getElementById("documentTemplate"),
  documentError: document.getElementById("documentError"),
  documentBack: document.getElementById("documentBack"),
  documentSubmit: document.getElementById("documentSubmit"),
  employeeSelect: document.getElementById("employeeSelect"),
  employeeDialog: document.getElementById("employeeDialog"),
  employeeForm: document.getElementById("employeeForm"),
  employeeChoices: document.getElementById("employeeChoices"),
  employeeDialogNote: document.getElementById("employeeDialogNote"),
  employeeOpenSettings: document.getElementById("employeeOpenSettings"),
  employeeError: document.getElementById("employeeError"),
  operationResultDialog: document.getElementById("operationResultDialog"),
  operationResultTitle: document.getElementById("operationResultTitle"),
  operationResultSummary: document.getElementById("operationResultSummary"),
  operationDocumentsSuccess: document.getElementById("operationDocumentsSuccess"),
  operationDocumentList: document.getElementById("operationDocumentList"),
  operationDocumentsWarning: document.getElementById("operationDocumentsWarning"),
  operationResultClose: document.getElementById("operationResultClose"),
  closureDialog: document.getElementById("closureDialog"),
  closureDialogClose: document.getElementById("closureDialogClose"),
  closureDialogTitle: document.getElementById("closureDialogTitle"),
  closureCellSummary: document.getElementById("closureCellSummary"),
  closureForm: document.getElementById("closureForm"),
  closureReason: document.getElementById("closureReason"),
  closureError: document.getElementById("closureError"),
  closureDate: document.getElementById("closureDate"),
  closureKind: document.getElementById("closureKind"),
  closureUnusedDays: document.getElementById("closureUnusedDays"),
  closurePenaltyDays: document.getElementById("closurePenaltyDays"),
  closurePenaltyAmount: document.getElementById("closurePenaltyAmount"),
  closureDepositLabel: document.getElementById("closureDepositLabel"),
  closureDepositNote: document.getElementById("closureDepositNote"),
  closureDepositRefund: document.getElementById("closureDepositRefund"),
  closureBack: document.getElementById("closureBack"),
  closureSubmit: document.getElementById("closureSubmit"),
  rentalDialog: document.getElementById("rentalDialog"),
  rentalDialogClose: document.getElementById("rentalDialogClose"),
  rentalDialogTitle: document.getElementById("rentalDialogTitle"),
  rentalCellSummary: document.getElementById("rentalCellSummary"),
  rentalForm: document.getElementById("rentalForm"),
  rentalStartDate: document.getElementById("rentalStartDate"),
  rentalEndDate: document.getElementById("rentalEndDate"),
  rentalDays: document.getElementById("rentalDays"),
  rentalError: document.getElementById("rentalError"),
  quoteDays: document.getElementById("quoteDays"),
  quoteTariff: document.getElementById("quoteTariff"),
  quoteRentPrice: document.getElementById("quoteRentPrice"),
  quoteDeposit: document.getElementById("quoteDeposit"),
  rentalBack: document.getElementById("rentalBack"),
  rentalContinue: document.getElementById("rentalContinue"),
  manualOccupy: document.getElementById("manualOccupy"),
  manualOccupationDialog: document.getElementById("manualOccupationDialog"),
  manualOccupationClose: document.getElementById("manualOccupationClose"),
  manualOccupationTitle: document.getElementById("manualOccupationTitle"),
  manualOccupationCellSummary: document.getElementById("manualOccupationCellSummary"),
  manualOccupationForm: document.getElementById("manualOccupationForm"),
  manualOccupationLabel: document.getElementById("manualOccupationLabel"),
  manualOccupationError: document.getElementById("manualOccupationError"),
  manualOccupationBack: document.getElementById("manualOccupationBack"),
  manualOccupationSubmit: document.getElementById("manualOccupationSubmit"),
  contractDialog: document.getElementById("contractDialog"),
  contractDialogClose: document.getElementById("contractDialogClose"),
  contractDialogTitle: document.getElementById("contractDialogTitle"),
  contractPeriodSummary: document.getElementById("contractPeriodSummary"),
  contractRentSummary: document.getElementById("contractRentSummary"),
  contractDepositSummary: document.getElementById("contractDepositSummary"),
  contractForm: document.getElementById("contractForm"),
  contractError: document.getElementById("contractError"),
  statementFile: document.getElementById("statementFile"),
  statementFileState: document.getElementById("statementFileState"),
  statementImport: document.getElementById("statementImport"),
  statementImportStatus: document.getElementById("statementImportStatus"),
  clientFullName: document.getElementById("clientFullName"),
  accountNumber: document.getElementById("accountNumber"),
  idCardNumber: document.getElementById("idCardNumber"),
  idCardIssuer: document.getElementById("idCardIssuer"),
  idCardIssueDate: document.getElementById("idCardIssueDate"),
  contractBack: document.getElementById("contractBack"),
  contractSubmit: document.getElementById("contractSubmit"),
};

function setConnection(mode, text) {
  elements.connection.classList.remove("online", "offline");
  if (mode) {
    elements.connection.classList.add(mode);
  }
  elements.connection.querySelector("span:last-child").textContent = text;
}

function fillEmployeeSelect(select, employees, selectedId) {
  select.replaceChildren(new Option("Выберите сотрудника", ""));
  for (const employee of employees) {
    select.append(new Option(employee.full_name, employee.employee_id));
  }
  select.value = selectedId || "";
}

function renderEmployeeChoices(employees, selectedId) {
  const fragment = document.createDocumentFragment();
  for (const employee of employees) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "employee-choice-card";
    button.dataset.employeeId = employee.employee_id;
    button.textContent = employee.full_name;
    if (employee.employee_id === selectedId) {
      button.classList.add("is-selected");
    }
    button.addEventListener("click", () => selectEmployee(employee.employee_id));
    fragment.append(button);
  }
  elements.employeeChoices.replaceChildren(fragment);
}

function renderEmployeeDirectory(payload) {
  const employees = Array.isArray(payload.employees) ? payload.employees : [];
  fillEmployeeSelect(elements.employeeSelect, employees, payload.selected_employee_id);
  renderEmployeeChoices(employees, payload.selected_employee_id);
  elements.employeeError.hidden = true;
  const isEmpty = employees.length === 0;
  elements.employeeOpenSettings.hidden = !isEmpty;
  elements.employeeDialogNote.textContent = isEmpty
    ? "Список сотрудников пока пуст. Добавьте первого сотрудника в настройках."
    : "Выберите своё имя. Оно будет записано в операции и подставлено в документы.";
  const adminDialog = document.getElementById("adminDialog");
  if ((isEmpty || payload.selection_required) && !adminDialog?.open && !elements.employeeDialog.open) {
    elements.employeeDialog.showModal();
  }
}

async function loadEmployeeDirectory() {
  try {
    const response = await fetch(elements.body.dataset.employeeDirectoryUrl, {cache: "no-store"});
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось получить список сотрудников");
    renderEmployeeDirectory(payload);
  } catch (error) {
    elements.employeeError.textContent = errorMessage(error, "Не удалось получить список сотрудников");
    elements.employeeError.hidden = false;
    if (!elements.employeeDialog.open) elements.employeeDialog.showModal();
  }
}

async function selectEmployee(employeeId) {
  if (!employeeId || state.employeeSubmitting) return;
  state.employeeSubmitting = true;
  elements.employeeChoices.querySelectorAll("button").forEach((button) => {
    button.disabled = true;
  });
  elements.employeeError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.employeeSelectUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Safe-Cells-Token": elements.body.dataset.privateToken},
      body: JSON.stringify({employee_id: employeeId}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось выбрать сотрудника");
    elements.employeeSelect.value = payload.employee_id;
    if (elements.employeeDialog.open) elements.employeeDialog.close();
  } catch (error) {
    elements.employeeError.textContent = errorMessage(error, "Не удалось выбрать сотрудника");
    elements.employeeError.hidden = false;
    await loadEmployeeDirectory();
  } finally {
    state.employeeSubmitting = false;
    elements.employeeChoices.querySelectorAll("button").forEach((button) => {
      button.disabled = false;
    });
  }
}

async function saveEmployeeSelection(event) {
  event.preventDefault();
}

function showError(message) {
  elements.errorMessage.textContent = message;
  elements.errorBanner.hidden = false;
  setConnection("offline", "Офлайн");
}

function showSuccess(message) {
  elements.successMessage.textContent = message;
  elements.successBanner.hidden = false;
}

function clearSuccess() {
  elements.successMessage.textContent = "";
  elements.successBanner.hidden = true;
}

function errorMessage(error, fallback) {
  if (error instanceof TypeError) {
    return NETWORK_ERROR_MESSAGE;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

function showOperationResult(summary, payload) {
  const documents = Array.isArray(payload.documents)
    ? payload.documents
    : payload.file_name ? [payload.file_name] : [];
  elements.operationResultTitle.textContent = "Операция выполнена";
  elements.operationResultSummary.textContent = summary;
  elements.operationDocumentList.replaceChildren();
  for (const generatedDocument of documents) {
    const item = document.createElement("li");
    item.textContent = typeof generatedDocument === "string"
      ? generatedDocument
      : generatedDocument.file_name || generatedDocument.display_name || "Документ DOCX";
    elements.operationDocumentList.append(item);
  }
  const hasDocuments = documents.length > 0;
  elements.operationDocumentsSuccess.hidden = !hasDocuments;
  elements.operationDocumentsWarning.hidden = hasDocuments;
  if (!hasDocuments) {
    const details = payload.document_warning || "Не удалось сформировать документы.";
    elements.operationDocumentsWarning.textContent = `Операция сохранена, но документы не сформированы: ${details}`;
  }
  if (!elements.operationResultDialog.open) elements.operationResultDialog.showModal();
}

function clearError() {
  elements.errorBanner.hidden = true;
  elements.errorMessage.textContent = "";
  setConnection("online", "Онлайн");
}

function populateHeightFilter(cells) {
  const previousValue = elements.height.value;
  const heights = [...new Set(cells.map((cell) => cell.height_mm))].sort((a, b) => a - b);
  elements.height.replaceChildren();

  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "Все размеры";
  elements.height.appendChild(allOption);

  for (const height of heights) {
    const option = document.createElement("option");
    option.value = String(height);
    option.textContent = `${height} мм`;
    elements.height.appendChild(option);
  }

  if (heights.includes(Number(previousValue))) {
    elements.height.value = previousValue;
  }
}

function renderStats() {
  elements.statFree.textContent = state.counts.free;
  elements.statOccupied.textContent = state.counts.normal + state.counts.expiring
    + state.counts.overdue;
  elements.statNormal.textContent = state.counts.normal;
  elements.statExpiring.textContent = state.counts.expiring;
  elements.statOverdue.textContent = state.counts.overdue;
}

function clearDisplayedData() {
  if (elements.closureDialog.open) {
    closeClosureDialog(false);
  }
  if (elements.renewalDialog.open) {
    closeRenewalDialog(false);
  }
  if (elements.manualOccupationDialog.open) {
    closeManualOccupationDialog();
  }
  if (elements.dialog.open) {
    closeCellDialog();
  }
  state.cells = [];
  state.counts = { free: 0, normal: 0, expiring: 0, overdue: 0 };
  state.privateMatches = null;
  state.asOfDate = null;
  elements.statFree.textContent = "—";
  elements.statOccupied.textContent = "—";
  elements.statNormal.textContent = "—";
  elements.statExpiring.textContent = "—";
  elements.statOverdue.textContent = "—";
  elements.grid.replaceChildren();
  elements.empty.hidden = true;
  elements.resultCount.textContent = "Данные недоступны";
  elements.updatedAt.textContent = "Актуальные данные не получены";
  populateHeightFilter([]);
}

function filteredCells() {
  const query = elements.search.value.trim().toLocaleLowerCase("ru");
  const status = elements.status.value;
  const height = elements.height.value;

  return state.cells.filter((cell) => {
    if (status && cell.status !== status) {
      return false;
    }
    if (height && String(cell.height_mm) !== height) {
      return false;
    }
    if (query) {
      const localMatch = String(cell.number).toLocaleLowerCase("ru").includes(query);
      const privateMatch = state.privateMatches?.has(String(cell.number)) ?? false;
      if (!localMatch && !privateMatch) {
        return false;
      }
    }
    return true;
  });
}

function formatDate(isoDate) {
  if (!isoDate) {
    return "Не применяется";
  }
  const [year, month, day] = isoDate.split("-").map(Number);
  return new Intl.DateTimeFormat("ru-RU").format(new Date(year, month - 1, day));
}

function daysLabel(cell) {
  if (cell.days_remaining === null) {
    return "Не применяется";
  }
  if (cell.days_remaining < 0) {
    return `Просрочено: ${Math.abs(cell.days_remaining)} дн.`;
  }
  if (cell.days_remaining === 0) {
    return "Окончание сегодня";
  }
  return `Осталось: ${cell.days_remaining} дн.`;
}

function renderOccupiedOperationalDetails(cell) {
  elements.dialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.dialogStatus.textContent = cell.block_kind === "lost_key"
    ? "Ключ утерян"
    : (cell.occupation_label || STATUS_LABELS[cell.status]);
  elements.dialogStatus.className = `status-badge ${cell.status}${
    cell.block_kind === "lost_key" ? " lost-key-label" : ""
  }`;
  elements.dialogSize.textContent = `${cell.height_mm}×${cell.width_mm}×${cell.depth_mm}`;
  if (cell.block_kind) {
    elements.cellDialogKicker.textContent = "Состояние ячейки";
    elements.dialogClientLabel.textContent = cell.block_kind === "manual" ? "Пометка" : "Клиент";
    elements.dialogClient.textContent = cell.block_kind === "manual"
      ? cell.occupation_label
      : "Получение данных…";
    elements.dialogStartDate.textContent = "Не применяется";
    elements.dialogEndDate.textContent = "Не применяется";
    elements.dialogRentDays.textContent = "Без срока";
    elements.dialogDays.textContent = "Не применяется";
    elements.privateCardSection.hidden = true;
    elements.contractCardActions.hidden = true;
    elements.blockedCardActions.hidden = false;
    elements.blockedActionError.hidden = true;
    elements.blockedActionError.textContent = "";
    elements.blockReleaseAction.textContent = cell.block_kind === "lost_key"
      ? "Ключ восстановлен"
      : "Освободить ячейку";
    return;
  }
  elements.cellDialogKicker.textContent = "Карточка занятой ячейки";
  elements.dialogClientLabel.textContent = "Клиент";
  elements.dialogClient.textContent = "Получение данных…";
  elements.dialogStartDate.textContent = formatDate(cell.start_date);
  elements.dialogEndDate.textContent = formatDate(cell.end_date);
  elements.dialogRentDays.textContent = `${cell.total_days} дн.`;
  elements.dialogDays.textContent = daysLabel(cell);
  elements.privateCardSection.hidden = false;
  elements.contractCardActions.hidden = false;
  elements.blockedCardActions.hidden = true;
}

async function loadOpenedClientName(cell) {
  const sequence = ++state.clientNameRequestSequence;
  try {
    const response = await fetch(elements.body.dataset.clientNameUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
      body: JSON.stringify({
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось получить ФИО клиента");
    }
    if (
      sequence === state.clientNameRequestSequence
      && elements.dialog.open
      && state.activeOccupiedCell?.contract_ref === cell.contract_ref
    ) {
      elements.dialogClient.textContent = payload.client_full_name;
    }
  } catch (error) {
    if (sequence === state.clientNameRequestSequence && elements.dialog.open) {
      elements.dialogClient.textContent = cell.client_display_name || "Не удалось получить ФИО";
    }
  }
}

async function loadBlockedClientName(cell) {
  const sequence = ++state.clientNameRequestSequence;
  try {
    const response = await fetch(elements.body.dataset.lostKeyClientUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
      body: JSON.stringify({cell_number: cell.number}),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось получить ФИО клиента");
    }
    if (
      sequence === state.clientNameRequestSequence
      && elements.dialog.open
      && state.activeOccupiedCell?.block_kind === "lost_key"
      && String(state.activeOccupiedCell.number) === String(cell.number)
    ) {
      elements.dialogClient.textContent = `${payload.client_full_name} — ключ утерян`;
    }
  } catch (error) {
    if (sequence === state.clientNameRequestSequence && elements.dialog.open) {
      elements.dialogClient.textContent = `${cell.client_display_name || "Клиент"} — ключ утерян`;
    }
  }
}

function openCellDialog(cell) {
  if (cell.status === "free") {
    openRentalCalculator(cell);
    return;
  }
  state.activeOccupiedCell = cell;
  state.blockOperationId = cell.block_kind ? createOperationId() : null;
  hidePrivateDetails();
  renderOccupiedOperationalDetails(cell);
  elements.dialog.showModal();
  if (cell.block_kind === "lost_key") {
    loadBlockedClientName(cell);
  } else if (!cell.block_kind) {
    loadOpenedClientName(cell);
  }
}

function formatDateTime(value) {
  if (!value) {
    return "Не указана";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

function clearPrivateValues() {
  elements.privateIdCardNumber.textContent = "";
  elements.privateIdCardIssuer.textContent = "";
  elements.privateIdCardIssueDate.textContent = "";
  elements.privateAccountNumber.textContent = "";
  elements.privateCreatedAt.textContent = "";
  elements.privateCreatedBy.textContent = "";
  elements.renewalList.replaceChildren();
}

function hidePrivateDetails() {
  state.privateRequestSequence += 1;
  state.privateVisible = false;
  clearPrivateValues();
  elements.privateDetails.hidden = true;
  elements.historyControls.hidden = true;
  elements.renewalHistory.hidden = true;
  elements.renewalEmpty.hidden = false;
  elements.privateError.hidden = true;
  elements.privateError.textContent = "";
  elements.privateToggle.disabled = false;
  elements.privateToggle.textContent = "Показать данные";
  elements.historyToggle.textContent = "Показать историю продлений";
}

function renderRenewals(renewals) {
  const fragment = document.createDocumentFragment();
  for (const renewal of renewals) {
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${formatDate(renewal.new_start_date)} — ${formatDate(renewal.new_end_date)} · ${renewal.renewal_days} дн.`;
    const details = document.createElement("span");
    const penalty = renewal.penalty_days > 0
      ? `, штраф ${renewal.penalty_days} дн. — ${money(renewal.penalty_amount)}`
      : ", без штрафа";
    details.textContent = `Продлено ${formatDate(renewal.renewal_date)} · сотрудник: ${renewal.created_by}, сумма ${money(renewal.renewal_price)}${penalty}`;
    item.append(title, details);
    fragment.appendChild(item);
  }
  elements.renewalList.replaceChildren(fragment);
  elements.renewalEmpty.hidden = renewals.length > 0;
  elements.historyToggle.textContent = `Показать историю продлений (${renewals.length})`;
}

async function togglePrivateDetails() {
  if (state.privateVisible) {
    hidePrivateDetails();
    return;
  }
  const cell = state.activeOccupiedCell;
  if (!cell) {
    return;
  }
  const sequence = ++state.privateRequestSequence;
  elements.privateToggle.disabled = true;
  elements.privateToggle.textContent = "Получение данных…";
  elements.privateError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.privateUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
      body: JSON.stringify({
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось получить данные договора");
    }
    if (
      sequence !== state.privateRequestSequence
      || !elements.dialog.open
      || state.activeOccupiedCell?.contract_ref !== cell.contract_ref
    ) {
      return;
    }
    elements.privateIdCardNumber.textContent = payload.id_card_number;
    elements.privateIdCardIssuer.textContent = payload.id_card_issuer;
    elements.privateIdCardIssueDate.textContent = formatDate(payload.id_card_issue_date);
    elements.privateAccountNumber.textContent = payload.account_number;
    elements.privateCreatedAt.textContent = formatDateTime(payload.created_at);
    elements.privateCreatedBy.textContent = payload.created_by;
    renderRenewals(payload.renewals);
    state.privateVisible = true;
    elements.privateDetails.hidden = false;
    elements.historyControls.hidden = false;
    elements.privateToggle.textContent = "Скрыть данные";
  } catch (error) {
    if (sequence !== state.privateRequestSequence) {
      return;
    }
    clearPrivateValues();
    elements.privateError.textContent = errorMessage(
      error,
      "Не удалось получить данные договора",
    );
    elements.privateError.hidden = false;
    elements.privateToggle.textContent = "Повторить запрос";
  } finally {
    if (sequence === state.privateRequestSequence) {
      elements.privateToggle.disabled = false;
    }
  }
}

function toggleRenewalHistory() {
  const willShow = elements.renewalHistory.hidden;
  elements.renewalHistory.hidden = !willShow;
  const count = elements.renewalList.children.length;
  elements.historyToggle.textContent = willShow
    ? "Скрыть историю продлений"
    : `Показать историю продлений (${count})`;
}

function closeDocumentDialog() {
  elements.documentDialog.close();
  elements.documentError.hidden = true;
  elements.documentError.textContent = "";
}

async function openDocumentDialog() {
  const cell = state.activeOccupiedCell;
  if (!cell) return;
  elements.documentAction.disabled = true;
  elements.documentTemplate.replaceChildren();
  elements.documentError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.documentTemplatesUrl, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Safe-Cells-Token": elements.body.dataset.privateToken},
      body: JSON.stringify({cell_number: cell.number, contract_ref: cell.contract_ref}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось получить шаблоны");
    if (!payload.templates.length) throw new Error("Активные DOCX-шаблоны пока не настроены.");
    for (const template of payload.templates) {
      const option = document.createElement("option");
      option.value = template.template_id;
      option.textContent = template.display_name;
      elements.documentTemplate.appendChild(option);
    }
    elements.documentDialog.showModal();
  } catch (error) {
    showError(errorMessage(error, "Не удалось получить шаблоны документов"));
  } finally {
    elements.documentAction.disabled = false;
  }
}

async function submitDocument(event) {
  event.preventDefault();
  const cell = state.activeOccupiedCell;
  if (!cell || state.documentSubmitting) return;
  state.documentSubmitting = true;
  elements.documentSubmit.disabled = true;
  elements.documentError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.documentGenerateUrl, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Safe-Cells-Token": elements.body.dataset.privateToken},
      body: JSON.stringify({cell_number: cell.number, contract_ref: cell.contract_ref, template_id: elements.documentTemplate.value}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось сформировать документ");
    closeDocumentDialog();
    showOperationResult(
      `Документ по ячейке № ${cell.number} сформирован.`,
      payload,
    );
  } catch (error) {
    elements.documentError.textContent = errorMessage(error, "Не удалось сформировать документ");
    elements.documentError.hidden = false;
  } finally {
    state.documentSubmitting = false;
    elements.documentSubmit.disabled = false;
  }
}

function closeEditDialog() {
  if (elements.editDialog.open) elements.editDialog.close();
  elements.editForm.reset();
  elements.editError.hidden = true;
  elements.editError.textContent = "";
  state.editOperationId = null;
}

async function openEditDialog() {
  const cell = state.activeOccupiedCell;
  if (!cell) return;
  elements.editAction.disabled = true;
  try {
    const response = await fetch(elements.body.dataset.privateUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-Safe-Cells-Token": elements.body.dataset.privateToken},
      body: JSON.stringify({cell_number: cell.number, contract_ref: cell.contract_ref}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось получить данные договора");
    if (state.activeOccupiedCell?.contract_ref !== cell.contract_ref) return;
    elements.editDialogTitle.textContent = `Ячейка № ${cell.number}`;
    elements.editClientFullName.value = payload.client_full_name;
    elements.editAccountNumber.value = payload.account_number;
    elements.editIdCardNumber.value = payload.id_card_number;
    elements.editIdCardIssuer.value = payload.id_card_issuer;
    setDateInputIso(elements.editIdCardIssueDate, payload.id_card_issue_date);
    state.editOperationId = createOperationId();
    elements.editDialog.showModal();
  } catch (error) {
    elements.privateError.textContent = errorMessage(error, "Не удалось получить данные договора");
    elements.privateError.hidden = false;
  } finally { elements.editAction.disabled = false; }
}

async function submitEdit(event) {
  event.preventDefault();
  const cell = state.activeOccupiedCell;
  if (!cell || !state.editOperationId || state.editSubmitting) return;
  if (!elements.editForm.reportValidity()) return;
  state.editSubmitting = true; elements.editSubmit.disabled = true; elements.editError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.editUrl, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({operation_id: state.editOperationId, contract_ref: cell.contract_ref,
        cell_number: cell.number, client_full_name: elements.editClientFullName.value,
        account_number: elements.editAccountNumber.value, id_card_number: elements.editIdCardNumber.value,
        id_card_issuer: elements.editIdCardIssuer.value, id_card_issue_date: dateInputIso(elements.editIdCardIssueDate)}),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось сохранить изменения");
    closeEditDialog(); hidePrivateDetails(); await refreshCells();
    showSuccess(payload.warning || "Данные договора изменены.");
  } catch (error) {
    elements.editError.textContent = errorMessage(error, "Не удалось сохранить изменения");
    elements.editError.hidden = false;
  } finally { state.editSubmitting = false; elements.editSubmit.disabled = false; }
}

function closeCellDialog() {
  closeEditDialog();
  state.clientNameRequestSequence += 1;
  hidePrivateDetails();
  state.activeOccupiedCell = null;
  state.blockOperationId = null;
  elements.dialog.close();
}

async function releaseBlockedCell() {
  const cell = state.activeOccupiedCell;
  if (!cell?.block_kind || !state.blockOperationId || state.blockSubmitting) return;
  const confirmation = cell.block_kind === "lost_key"
    ? `Подтвердите, что ключ от ячейки № ${cell.number} восстановлен.`
    : `Освободить ячейку № ${cell.number}?`;
  if (!window.confirm(confirmation)) return;
  state.blockSubmitting = true;
  elements.blockReleaseAction.disabled = true;
  try {
    const url = elements.body.dataset.cellBlockReleaseUrl.replace(
      "__BLOCK_KIND__", cell.block_kind,
    );
    const response = await fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        operation_id: state.blockOperationId,
        cell_number: cell.number,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось освободить ячейку");
    }
    const message = cell.block_kind === "lost_key"
      ? `Ключ от ячейки № ${cell.number} восстановлен. Ячейка свободна.`
      : `Ячейка № ${cell.number} освобождена.`;
    state.blockSubmitting = false;
    closeCellDialog();
    await refreshCells();
    showSuccess(payload.warning ? `${message} ${payload.warning}` : message);
  } catch (error) {
    elements.blockedActionError.textContent = errorMessage(
      error, "Не удалось освободить ячейку",
    );
    elements.blockedActionError.hidden = false;
  } finally {
    state.blockSubmitting = false;
    elements.blockReleaseAction.disabled = false;
  }
}

const CLOSURE_KIND_LABELS = {
  early: "Досрочное",
  on_time: "В дату окончания",
  overdue: "После окончания срока",
};

function resetClosureQuote() {
  state.activeClosureQuote = null;
  elements.closureSubmit.disabled = true;
  elements.closureDate.textContent = "—";
  elements.closureKind.textContent = "—";
  elements.closureUnusedDays.textContent = "—";
  elements.closurePenaltyDays.textContent = "—";
  elements.closurePenaltyAmount.textContent = "—";
  elements.closureDepositRefund.textContent = "—";
}

function showClosureError(message) {
  elements.closureError.textContent = message;
  elements.closureError.hidden = false;
}

function clearClosureError() {
  elements.closureError.textContent = "";
  elements.closureError.hidden = true;
}

function setClosureSubmitting(submitting) {
  state.closureSubmitting = submitting;
  elements.closureSubmit.disabled = submitting || !state.activeClosureQuote;
  elements.closureBack.disabled = submitting;
  elements.closureDialogClose.disabled = submitting;
  elements.closureReason.disabled = submitting;
  elements.closureSubmit.textContent = submitting ? "Закрытие…" : "Подтвердить закрытие";
}

async function requestClosureQuote() {
  const cell = state.activeOccupiedCell;
  const sequence = ++state.closureQuoteSequence;
  if (!cell) {
    return;
  }
  resetClosureQuote();
  clearClosureError();
  elements.closureKind.textContent = "Расчёт…";
  try {
    const response = await fetch(elements.body.dataset.closureQuoteUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
        reason_code: elements.closureReason.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось рассчитать закрытие");
    }
    if (sequence !== state.closureQuoteSequence || !elements.closureDialog.open) {
      return;
    }
    state.activeClosureQuote = payload;
    elements.closureDate.textContent = formatDate(payload.close_date);
    elements.closureKind.textContent = CLOSURE_KIND_LABELS[payload.close_kind];
    elements.closureUnusedDays.textContent = `${payload.unused_days} дн.`;
    elements.closurePenaltyDays.textContent = `${payload.penalty_days} дн.`;
    elements.closurePenaltyAmount.textContent = money(payload.penalty_amount);
    for (const row of document.querySelectorAll(".closure-penalty-row")) {
      row.hidden = payload.penalty_days === 0;
    }
    elements.closureDepositRefund.textContent = money(payload.deposit_refund);
    if (elements.closureReason.value === "lost_key") {
      elements.closureDepositLabel.textContent = "Залог не возвращается";
      elements.closureDepositNote.textContent = "Причина: потеря ключа";
    } else {
      elements.closureDepositLabel.textContent = "Залог к возврату";
      elements.closureDepositNote.textContent = "При обычном закрытии";
    }
    elements.closureSubmit.disabled = false;
  } catch (error) {
    if (sequence !== state.closureQuoteSequence) {
      return;
    }
    resetClosureQuote();
    showClosureError(errorMessage(error, "Не удалось рассчитать закрытие"));
  }
}

function openClosureDialog() {
  const cell = state.activeOccupiedCell;
  if (!cell) {
    return;
  }
  hidePrivateDetails();
  elements.dialog.close();
  clearSuccess();
  state.closureOperationId = createOperationId();
  elements.closureDialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.closureCellSummary.textContent = `Текущий договор действует до ${formatDate(cell.end_date)}`;
  elements.closureReason.value = "standard";
  resetClosureQuote();
  clearClosureError();
  setClosureSubmitting(false);
  elements.closureDialog.showModal();
  requestClosureQuote();
}

function closeClosureDialog(returnToCard = true) {
  if (state.closureSubmitting) {
    return;
  }
  state.closureQuoteSequence += 1;
  state.activeClosureQuote = null;
  state.closureOperationId = null;
  elements.closureDialog.close();
  if (returnToCard && state.activeOccupiedCell) {
    hidePrivateDetails();
    renderOccupiedOperationalDetails(state.activeOccupiedCell);
    elements.dialog.showModal();
  } else if (!returnToCard) {
    state.activeOccupiedCell = null;
  }
}

async function submitClosure(event) {
  event.preventDefault();
  const cell = state.activeOccupiedCell;
  const quote = state.activeClosureQuote;
  if (!cell || !quote || !state.closureOperationId) {
    showClosureError("Расчёт устарел. Выполните его ещё раз.");
    return;
  }
  clearClosureError();
  setClosureSubmitting(true);
  try {
    const response = await fetch(elements.body.dataset.closureUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operation_id: state.closureOperationId,
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
        expected_end_date: cell.end_date,
        reason_code: elements.closureReason.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось закрыть договор");
    }
    const warning = payload.warning ? ` ${payload.warning}` : "";
    state.closureSubmitting = false;
    elements.closureDialog.close();
    state.activeClosureQuote = null;
    state.closureOperationId = null;
    state.activeOccupiedCell = null;
    await refreshCells();
    const cellState = payload.cell_blocked
      ? "Ячейка остаётся занятой: ключ утерян."
      : "Ячейка свободна.";
    showOperationResult(
      `Договор по ячейке № ${payload.cell_number} закрыт. ${cellState}${warning}`,
      payload,
    );
  } catch (error) {
    showClosureError(errorMessage(error, "Не удалось закрыть договор"));
  } finally {
    setClosureSubmitting(false);
  }
}

function resetRenewalQuote() {
  state.activeRenewalQuote = null;
  elements.renewalSubmit.disabled = true;
  elements.renewalNewStart.textContent = "—";
  elements.renewalPeriod.textContent = "—";
  elements.renewalTariff.textContent = "—";
  elements.renewalPrice.textContent = "—";
  elements.renewalPenaltyDays.textContent = "—";
  elements.renewalPenaltyAmount.textContent = "—";
  elements.renewalPenaltyPanel.hidden = true;
  elements.renewalTotal.textContent = "—";
}

function showRenewalError(message) {
  elements.renewalError.textContent = message;
  elements.renewalError.hidden = false;
}

function clearRenewalError() {
  elements.renewalError.textContent = "";
  elements.renewalError.hidden = true;
}

function setRenewalSubmitting(submitting) {
  state.renewalSubmitting = submitting;
  elements.renewalSubmit.disabled = submitting || !state.activeRenewalQuote;
  elements.renewalBack.disabled = submitting;
  elements.renewalDialogClose.disabled = submitting;
  elements.renewalSubmit.textContent = submitting ? "Сохранение…" : "Подтвердить продление";
}

async function requestRenewalQuote() {
  const cell = state.activeOccupiedCell;
  const daysValue = elements.renewalDays.value.trim();
  const days = Number(daysValue);
  const endDate = dateInputIso(elements.renewalEndDate) || null;
  const sequence = ++state.renewalQuoteSequence;
  if (!daysValue && !endDate) {
    resetRenewalQuote();
    clearRenewalError();
    return;
  }
  if (!cell || !Number.isInteger(days) || days < 1) {
    resetRenewalQuote();
    showRenewalError("Укажите корректный срок продления.");
    return;
  }
  clearRenewalError();
  elements.renewalPeriod.textContent = "Расчёт…";
  try {
    const response = await fetch(elements.body.dataset.renewalQuoteUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
        new_end_date: endDate,
        renewal_days: days,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось рассчитать продление");
    }
    if (sequence !== state.renewalQuoteSequence || !elements.renewalDialog.open) {
      return;
    }
    state.activeRenewalQuote = payload;
    elements.renewalDate.textContent = formatDate(payload.renewal_date);
    elements.renewalNewStart.textContent = formatDate(payload.new_start_date);
    setDateInputIso(elements.renewalEndDate, payload.new_end_date);
    elements.renewalDays.value = String(payload.renewal_days);
    elements.renewalPeriod.textContent = `${formatDate(payload.new_start_date)} — ${formatDate(payload.new_end_date)} · ${payload.renewal_days} дн.`;
    elements.renewalTariff.textContent = `${money(payload.price_per_day)} в день`;
    elements.renewalPrice.textContent = money(payload.renewal_price);
    elements.renewalPenaltyDays.textContent = `${payload.penalty_days} дн.`;
    elements.renewalPenaltyAmount.textContent = money(payload.penalty_amount);
    elements.renewalPenaltyPanel.hidden = payload.penalty_days === 0;
    elements.renewalTotal.textContent = money(payload.total_amount);
    elements.renewalSubmit.disabled = false;
    clearRenewalError();
  } catch (error) {
    if (sequence !== state.renewalQuoteSequence) {
      return;
    }
    resetRenewalQuote();
    showRenewalError(errorMessage(error, "Не удалось рассчитать продление"));
  }
}

let renewalQuoteTimer = null;
function scheduleRenewalQuote() {
  window.clearTimeout(renewalQuoteTimer);
  state.renewalQuoteSequence += 1;
  resetRenewalQuote();
  renewalQuoteTimer = window.setTimeout(requestRenewalQuote, 180);
}

function renewalStartDateValue() {
  const cell = state.activeOccupiedCell;
  const oldEnd = parseIsoDateUtc(cell?.end_date || "");
  const renewalDate = parseIsoDateUtc(state.asOfDate || "");
  if (!oldEnd || !renewalDate) {
    return null;
  }
  const dayAfterOldEnd = new Date(oldEnd.getTime());
  dayAfterOldEnd.setUTCDate(dayAfterOldEnd.getUTCDate() + 1);
  return isoFromUtcDate(dayAfterOldEnd > renewalDate ? dayAfterOldEnd : renewalDate);
}

function syncRenewalDaysFromEnd() {
  const start = parseIsoDateUtc(renewalStartDateValue() || "");
  const end = parseIsoDateUtc(dateInputIso(elements.renewalEndDate));
  if (!start || !end || end < start) {
    elements.renewalDays.value = "";
    return;
  }
  elements.renewalDays.value = String(Math.round((end - start) / 86_400_000) + 1);
}

function syncRenewalEndFromDays() {
  const start = parseIsoDateUtc(renewalStartDateValue() || "");
  const days = Number(elements.renewalDays.value);
  if (!start || !Number.isInteger(days) || days < 1) {
    setDateInputIso(elements.renewalEndDate, "");
    return;
  }
  const end = new Date(start.getTime());
  end.setUTCDate(end.getUTCDate() + days - 1);
  setDateInputIso(elements.renewalEndDate, isoFromUtcDate(end));
}

function openRenewalDialog() {
  const cell = state.activeOccupiedCell;
  if (!cell) {
    return;
  }
  hidePrivateDetails();
  elements.dialog.close();
  clearSuccess();
  state.activeRenewalQuote = null;
  state.renewalOperationId = createOperationId();
  elements.renewalDialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.renewalCellSummary.textContent = `Высота ${cell.height_mm} мм · договор действует до ${formatDate(cell.end_date)}`;
  elements.renewalOldEnd.textContent = formatDate(cell.end_date);
  elements.renewalDate.textContent = formatDate(state.asOfDate);
  setDateInputIso(elements.renewalEndDate, "");
  elements.renewalDays.value = "";
  clearRenewalError();
  resetRenewalQuote();
  setRenewalSubmitting(false);
  elements.renewalDialog.showModal();
}

function closeRenewalDialog(returnToCard = true) {
  if (state.renewalSubmitting) {
    return;
  }
  window.clearTimeout(renewalQuoteTimer);
  state.renewalQuoteSequence += 1;
  state.activeRenewalQuote = null;
  state.renewalOperationId = null;
  elements.renewalDialog.close();
  if (returnToCard && state.activeOccupiedCell) {
    hidePrivateDetails();
    renderOccupiedOperationalDetails(state.activeOccupiedCell);
    elements.dialog.showModal();
  } else if (!returnToCard) {
    state.activeOccupiedCell = null;
  }
}

async function submitRenewal(event) {
  event.preventDefault();
  const cell = state.activeOccupiedCell;
  const quote = state.activeRenewalQuote;
  if (!cell || !quote || !state.renewalOperationId) {
    showRenewalError("Расчёт устарел. Выполните его ещё раз.");
    return;
  }
  clearRenewalError();
  setRenewalSubmitting(true);
  try {
    const response = await fetch(elements.body.dataset.renewalUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operation_id: state.renewalOperationId,
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
        expected_end_date: cell.end_date,
        new_end_date: quote.new_end_date,
        renewal_days: quote.renewal_days,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось сохранить продление");
    }
    const cellNumber = payload.cell_number;
    const warning = payload.warning ? ` ${payload.warning}` : "";
    state.renewalSubmitting = false;
    elements.renewalDialog.close();
    state.activeRenewalQuote = null;
    state.renewalOperationId = null;
    state.activeOccupiedCell = null;
    await refreshCells();
    const updated = state.cells.find((item) => String(item.number) === String(cellNumber));
    if (updated && updated.status !== "free") {
      openCellDialog(updated);
    }
    showOperationResult(`Аренда ячейки № ${cellNumber} продлена до ${formatDate(payload.new_end_date)}.${warning}`, payload);
  } catch (error) {
    showRenewalError(errorMessage(error, "Не удалось сохранить продление"));
  } finally {
    setRenewalSubmitting(false);
  }
}

function parseIsoDateUtc(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const result = new Date(Date.UTC(year, month - 1, day));
  if (
    result.getUTCFullYear() !== year
    || result.getUTCMonth() !== month - 1
    || result.getUTCDate() !== day
  ) {
    return null;
  }
  return result;
}

function displayDateFromIso(value) {
  const parsed = parseIsoDateUtc(value);
  if (!parsed) {
    return "";
  }
  const [year, month, day] = value.split("-");
  return `${day}.${month}.${year}`;
}

function parseDisplayDate(value) {
  if (typeof value !== "string") {
    return null;
  }
  const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value.trim());
  if (!match) {
    return null;
  }
  const [, day, month, year] = match;
  const isoValue = `${year}-${month}-${day}`;
  return parseIsoDateUtc(isoValue) ? isoValue : null;
}

function formatDateDigits(value) {
  const digits = String(value || "").replace(/\D/g, "").slice(0, 8);
  if (digits.length < 2) {
    return digits;
  }
  if (digits.length === 2) {
    return `${digits}.`;
  }
  if (digits.length < 4) {
    return `${digits.slice(0, 2)}.${digits.slice(2)}`;
  }
  if (digits.length === 4) {
    return `${digits.slice(0, 2)}.${digits.slice(2)}.`;
  }
  return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`;
}

function updateDateInputValidity(input) {
  const digits = input.value.replace(/\D/g, "");
  const isoValue = parseDisplayDate(input.value);
  let message = "";
  if (digits.length > 0 && digits.length < 8) {
    message = "Введите дату полностью в формате ДД.ММ.ГГГГ.";
  } else if (digits.length === 8 && !isoValue) {
    message = "Укажите существующую дату в формате ДД.ММ.ГГГГ.";
  } else if (isoValue && input.dataset.maxIso && isoValue > input.dataset.maxIso) {
    message = "Дата начала не может быть позже текущей даты.";
  }
  input.setCustomValidity(message);
}

function dateInputIso(input) {
  return parseDisplayDate(input.value) || "";
}

function setDateInputIso(input, isoValue) {
  input.value = displayDateFromIso(isoValue);
  updateDateInputValidity(input);
}

function putDateDigits(input, digits) {
  input.value = formatDateDigits(digits);
  updateDateInputValidity(input);
  input.setSelectionRange(input.value.length, input.value.length);
}

function emitDateInput(input) {
  input.dispatchEvent(new Event("input", {bubbles: true}));
}

function handleDateKeydown(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) {
    return;
  }
  const input = event.currentTarget;
  let digits = input.value.replace(/\D/g, "");
  if (event.key === "Backspace") {
    event.preventDefault();
    putDateDigits(input, digits.slice(0, -1));
    emitDateInput(input);
    return;
  }
  if (!/^\d$/.test(event.key)) {
    return;
  }
  event.preventDefault();
  if (input.selectionStart === 0 && input.selectionEnd === input.value.length) {
    digits = "";
  }
  if (digits.length >= 8) {
    return;
  }
  putDateDigits(input, `${digits}${event.key}`);
  emitDateInput(input);
}

function handleDatePaste(event) {
  const pastedValue = event.clipboardData?.getData("text/plain")
    || event.clipboardData?.getData("text") || "";
  const isoValue = /^\d{4}-\d{2}-\d{2}$/.test(pastedValue.trim())
    ? pastedValue.trim()
    : null;
  const digits = pastedValue.replace(/\D/g, "");
  if (!isoValue && !digits) {
    return;
  }
  event.preventDefault();
  if (isoValue && parseIsoDateUtc(isoValue)) {
    setDateInputIso(event.currentTarget, isoValue);
  } else {
    putDateDigits(event.currentTarget, digits);
  }
  emitDateInput(event.currentTarget);
}

function normalizeDateInput(event) {
  const input = event.currentTarget;
  putDateDigits(input, input.value);
}

function isoFromUtcDate(value) {
  return value.toISOString().slice(0, 10);
}

function syncDaysFromDates() {
  const start = parseIsoDateUtc(dateInputIso(elements.rentalStartDate));
  const end = parseIsoDateUtc(dateInputIso(elements.rentalEndDate));
  if (!start || !end || end < start) {
    elements.rentalDays.value = "";
    return false;
  }
  elements.rentalDays.value = String(Math.round((end - start) / 86_400_000) + 1);
  return true;
}

function syncEndFromDays() {
  const start = parseIsoDateUtc(dateInputIso(elements.rentalStartDate));
  const days = Number(elements.rentalDays.value);
  if (!start || !Number.isInteger(days) || days < 1) {
    setDateInputIso(elements.rentalEndDate, "");
    return false;
  }
  const end = new Date(start.getTime());
  end.setUTCDate(end.getUTCDate() + days - 1);
  setDateInputIso(elements.rentalEndDate, isoFromUtcDate(end));
  return true;
}

function money(value) {
  return `${new Intl.NumberFormat("ru-RU").format(value)} сом`;
}

function resetQuote() {
  state.activeQuote = null;
  elements.rentalContinue.disabled = true;
  elements.quoteDays.textContent = "—";
  elements.quoteTariff.textContent = "—";
  elements.quoteRentPrice.textContent = "—";
  elements.quoteDeposit.textContent = "—";
}

function showRentalError(message) {
  elements.rentalError.textContent = message;
  elements.rentalError.hidden = false;
}

function clearRentalError() {
  elements.rentalError.textContent = "";
  elements.rentalError.hidden = true;
}

async function requestRentalQuote() {
  const cell = state.activeRentalCell;
  const startDate = dateInputIso(elements.rentalStartDate);
  const endDate = dateInputIso(elements.rentalEndDate);
  const rentDaysValue = elements.rentalDays.value.trim();
  const rentDays = Number(rentDaysValue);
  const sequence = ++state.quoteSequence;
  if (!startDate || !endDate || !rentDaysValue) {
    resetQuote();
    clearRentalError();
    return;
  }
  if (
    !cell
    || !parseIsoDateUtc(startDate)
    || !parseIsoDateUtc(endDate)
    || !Number.isInteger(rentDays)
    || rentDays < 1
  ) {
    resetQuote();
    showRentalError("Укажите корректный срок аренды.");
    return;
  }

  clearRentalError();
  elements.quoteDays.textContent = "Расчёт…";
  try {
    const response = await fetch(elements.body.dataset.rentalUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cell_number: cell.number,
        start_date: startDate,
        end_date: endDate,
        rent_days: rentDays,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось выполнить расчёт");
    }
    if (sequence !== state.quoteSequence || !elements.rentalDialog.open) {
      return;
    }
    state.activeQuote = payload;
    const period = payload.period_to_days === null
      ? `${payload.period_from_days}+ дней`
      : `${payload.period_from_days}–${payload.period_to_days} дней`;
    elements.quoteDays.textContent = `${payload.rent_days} дн.`;
    elements.quoteTariff.textContent = `${payload.price_per_day} сом/день · ${period}`;
    elements.quoteRentPrice.textContent = money(payload.rent_price);
    elements.quoteDeposit.textContent = money(payload.deposit_amount);
    elements.rentalContinue.disabled = false;
    clearRentalError();
  } catch (error) {
    if (sequence !== state.quoteSequence) {
      return;
    }
    resetQuote();
    showRentalError(errorMessage(error, "Не удалось выполнить расчёт"));
  }
}

let quoteTimer = null;
function scheduleRentalQuote() {
  window.clearTimeout(quoteTimer);
  state.quoteSequence += 1;
  resetQuote();
  quoteTimer = window.setTimeout(requestRentalQuote, 180);
}

function openRentalCalculator(cell) {
  state.activeRentalCell = cell;
  state.activeQuote = null;
  state.activeOperationId = null;
  state.manualOperationId = createOperationId();
  clearSuccess();
  elements.rentalDialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.rentalCellSummary.textContent = `Высота ${cell.height_mm} мм · ${cell.width_mm} × ${cell.depth_mm} мм`;
  const startDate = state.asOfDate || isoFromUtcDate(new Date());
  elements.rentalStartDate.dataset.maxIso = startDate;
  setDateInputIso(elements.rentalStartDate, startDate);
  setDateInputIso(elements.rentalEndDate, startDate);
  elements.rentalDays.value = "";
  resetQuote();
  clearRentalError();
  elements.rentalDialog.showModal();
}

function closeRentalCalculator() {
  window.clearTimeout(quoteTimer);
  state.quoteSequence += 1;
  state.activeRentalCell = null;
  state.activeQuote = null;
  state.activeOperationId = null;
  state.manualOperationId = null;
  if (elements.rentalDialog.open) elements.rentalDialog.close();
}

function openManualOccupationDialog() {
  const cell = state.activeRentalCell;
  if (!cell || !state.manualOperationId || state.blockSubmitting) return;
  elements.rentalDialog.close();
  elements.manualOccupationTitle.textContent = `Занять ячейку № ${cell.number}`;
  elements.manualOccupationCellSummary.textContent = `Высота ${cell.height_mm} мм · без договора и срока`;
  elements.manualOccupationLabel.value = "";
  elements.manualOccupationError.hidden = true;
  elements.manualOccupationError.textContent = "";
  elements.manualOccupationDialog.showModal();
  elements.manualOccupationLabel.focus();
}

function closeManualOccupationDialog() {
  if (elements.manualOccupationDialog.open) elements.manualOccupationDialog.close();
  closeRentalCalculator();
}

async function occupyManualCell(event) {
  event.preventDefault();
  const cell = state.activeRentalCell;
  const occupationLabel = elements.manualOccupationLabel.value.trim().replace(/\s+/g, " ");
  if (!cell || !state.manualOperationId || state.blockSubmitting) return;
  if (!occupationLabel) {
    elements.manualOccupationError.textContent = "Напишите, для чего занята ячейка.";
    elements.manualOccupationError.hidden = false;
    return;
  }
  state.blockSubmitting = true;
  elements.manualOccupationSubmit.disabled = true;
  elements.manualOccupationError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.cellBlockManualUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        operation_id: state.manualOperationId,
        cell_number: cell.number,
        occupation_label: occupationLabel,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось занять ячейку");
    }
    const cellNumber = cell.number;
    state.blockSubmitting = false;
    closeManualOccupationDialog();
    await refreshCells();
    const message = `Ячейка № ${cellNumber} занята без договора и срока.`;
    showSuccess(payload.warning ? `${message} ${payload.warning}` : message);
  } catch (error) {
    elements.manualOccupationError.textContent = errorMessage(error, "Не удалось занять ячейку");
    elements.manualOccupationError.hidden = false;
  } finally {
    state.blockSubmitting = false;
    elements.manualOccupationSubmit.disabled = false;
  }
}

function createOperationId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function clearContractError() {
  elements.contractError.textContent = "";
  elements.contractError.hidden = true;
}

function showContractError(message) {
  elements.contractError.textContent = message;
  elements.contractError.hidden = false;
}

function setContractSubmitting(submitting) {
  state.contractSubmitting = submitting;
  refreshContractControls();
  elements.contractSubmit.textContent = submitting ? "Сохранение…" : "Подтвердить и занять";
}

function refreshContractControls() {
  const busy = state.contractSubmitting || state.statementImporting;
  elements.contractSubmit.disabled = busy;
  elements.contractBack.disabled = busy;
  elements.contractDialogClose.disabled = busy;
  elements.statementFile.disabled = busy;
  elements.statementImport.disabled = busy;
}

function setStatementImportStatus(message = "", isError = false) {
  elements.statementImportStatus.textContent = message;
  elements.statementImportStatus.hidden = !message;
  elements.statementImportStatus.classList.toggle("is-error", isError);
}

function resetStatementImport() {
  state.statementImportSequence += 1;
  state.statementImporting = false;
  elements.statementFile.value = "";
  elements.statementFileState.textContent = "Файл не выбран";
  setStatementImportStatus();
  refreshContractControls();
}

async function importStatementData() {
  const file = elements.statementFile.files[0];
  if (!file) {
    setStatementImportStatus("Выберите заявление в формате DOCX.", true);
    return;
  }
  if (!file.name.toLocaleLowerCase("ru").endsWith(".docx")) {
    setStatementImportStatus("Заявление должно быть файлом DOCX.", true);
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    setStatementImportStatus("Размер заявления не должен превышать 2 МБ.", true);
    return;
  }

  const sequence = state.statementImportSequence + 1;
  state.statementImportSequence = sequence;
  state.statementImporting = true;
  setStatementImportStatus("Чтение заявления…");
  refreshContractControls();
  const formData = new FormData();
  formData.append("file", file);
  try {
    const response = await fetch(elements.body.dataset.statementImportUrl, {
      method: "POST",
      headers: {"X-Safe-Cells-Token": elements.body.dataset.privateToken},
      body: formData,
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось прочитать заявление.");
    }
    if (sequence !== state.statementImportSequence) {
      return;
    }
    elements.clientFullName.value = payload.client_full_name;
    elements.accountNumber.value = payload.account_number;
    elements.idCardNumber.value = payload.id_card_number;
    elements.idCardIssuer.value = payload.id_card_issuer;
    setDateInputIso(elements.idCardIssueDate, payload.id_card_issue_date);
    elements.statementFile.value = "";
    elements.statementFileState.textContent = "Файл не выбран";
    setStatementImportStatus("Данные перенесены. Обязательно проверьте их перед сохранением.");
  } catch (error) {
    if (sequence === state.statementImportSequence) {
      setStatementImportStatus(errorMessage(error, "Не удалось прочитать заявление."), true);
    }
  } finally {
    if (sequence === state.statementImportSequence) {
      state.statementImporting = false;
      refreshContractControls();
    }
  }
}

function openContractForm() {
  const cell = state.activeRentalCell;
  const quote = state.activeQuote;
  if (!cell || !quote) {
    showRentalError("Сначала дождитесь актуального расчёта.");
    return;
  }
  state.activeOperationId = createOperationId();
  elements.contractForm.reset();
  resetStatementImport();
  setDateInputIso(elements.idCardIssueDate, "");
  elements.contractDialogTitle.textContent = `Занять ячейку № ${cell.number}`;
  elements.contractPeriodSummary.textContent = `${formatDate(quote.start_date)} — ${formatDate(quote.end_date)} · ${quote.rent_days} дн.`;
  elements.contractRentSummary.textContent = `Аренда: ${money(quote.rent_price)}`;
  elements.contractDepositSummary.textContent = `Залог отдельно: ${money(quote.deposit_amount)}`;
  clearContractError();
  setContractSubmitting(false);
  elements.rentalDialog.close();
  elements.contractDialog.showModal();
}

function backToRentalCalculator() {
  if (state.statementImporting) {
    return;
  }
  elements.contractDialog.close();
  clearContractError();
  resetStatementImport();
  elements.rentalDialog.showModal();
}

function cancelContractWorkflow() {
  if (state.contractSubmitting || state.statementImporting) {
    return;
  }
  elements.contractDialog.close();
  elements.contractForm.reset();
  resetStatementImport();
  clearContractError();
  state.activeRentalCell = null;
  state.activeQuote = null;
  state.activeOperationId = null;
  state.manualOperationId = null;
}

async function submitContract(event) {
  event.preventDefault();
  if (!elements.contractForm.checkValidity()) {
    elements.contractForm.reportValidity();
    showContractError("Заполните все обязательные поля.");
    return;
  }
  const cell = state.activeRentalCell;
  const quote = state.activeQuote;
  if (!cell || !quote || !state.activeOperationId) {
    showContractError("Расчёт устарел. Вернитесь назад и выполните его снова.");
    return;
  }

  clearContractError();
  setContractSubmitting(true);
  try {
    const response = await fetch(elements.body.dataset.contractUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        operation_id: state.activeOperationId,
        cell_number: cell.number,
        client_full_name: elements.clientFullName.value,
        id_card_number: elements.idCardNumber.value,
        id_card_issuer: elements.idCardIssuer.value,
        id_card_issue_date: dateInputIso(elements.idCardIssueDate),
        account_number: elements.accountNumber.value,
        start_date: quote.start_date,
        end_date: quote.end_date,
        rent_days: quote.rent_days,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось сохранить договор");
    }
    const savedCellNumber = payload.cell_number;
    const warning = payload.warning ? ` ${payload.warning}` : "";
    elements.contractDialog.close();
    elements.contractForm.reset();
    resetStatementImport();
    state.activeRentalCell = null;
    state.activeQuote = null;
    state.activeOperationId = null;
    state.manualOperationId = null;
    await refreshCells();
    showOperationResult(`Ячейка № ${savedCellNumber} занята.${warning}`, payload);
  } catch (error) {
    showContractError(errorMessage(error, "Не удалось сохранить договор"));
  } finally {
    setContractSubmitting(false);
  }
}

function createCellButton(cell) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `cell ${cell.status}`;
  const accessibleStatus = cell.block_kind
    ? cell.client_display_name
    : STATUS_LABELS[cell.status];
  button.setAttribute(
    "aria-label",
    `Ячейка ${cell.number}, высота ${cell.height_mm} миллиметров, ${accessibleStatus}`,
  );

  const number = document.createElement("span");
  number.className = "cell-number";
  number.textContent = cell.number;

  const height = document.createElement("span");
  height.className = "cell-height";
  height.textContent = String(cell.height_mm);

  const client = document.createElement("span");
  client.className = `cell-client${
    cell.block_kind === "lost_key" ? " lost-key-label" : ""
  }`;
  client.textContent = cell.client_display_name || "";

  button.append(number, client, height);
  button.addEventListener("click", () => openCellDialog(cell));
  return button;
}

function renderGrid() {
  const cells = filteredCells();
  const fragment = document.createDocumentFragment();
  for (const cell of cells) {
    fragment.appendChild(createCellButton(cell));
  }
  elements.grid.replaceChildren(fragment);
  elements.grid.setAttribute("aria-busy", "false");
  elements.empty.hidden = cells.length > 0;
  elements.resultCount.textContent = `Показано ${cells.length} из ${state.cells.length}`;
}

async function runPrivateSearch() {
  const query = elements.search.value.trim();
  const sequence = ++state.searchSequence;
  if (!query) {
    state.privateMatches = null;
    renderGrid();
    return;
  }

  try {
    const response = await fetch(elements.body.dataset.searchUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось выполнить поиск");
    }
    if (sequence !== state.searchSequence) {
      return;
    }
    state.privateMatches = new Set(payload.matched_numbers.map(String));
    clearError();
    renderGrid();
  } catch (error) {
    if (sequence !== state.searchSequence) {
      return;
    }
    state.privateMatches = new Set();
    showError(errorMessage(error, "Не удалось выполнить поиск"));
    renderGrid();
  }
}

let searchTimer = null;
function scheduleSearch() {
  window.clearTimeout(searchTimer);
  state.searchSequence += 1;
  state.privateMatches = null;
  renderGrid();
  searchTimer = window.setTimeout(runPrivateSearch, 250);
}

async function refreshCells() {
  elements.grid.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(elements.body.dataset.cellsUrl, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось получить данные");
    }
    state.cells = payload.cells;
    state.counts = payload.counts;
    state.asOfDate = payload.as_of_date;
    if (state.activeOccupiedCell && elements.dialog.open) {
      const updatedCell = state.cells.find(
        (cell) => String(cell.number) === String(state.activeOccupiedCell.number),
      );
      const activeCell = state.activeOccupiedCell;
      const identityChanged = activeCell.block_kind
        ? updatedCell?.block_kind !== activeCell.block_kind
          || updatedCell?.source_contract_ref !== activeCell.source_contract_ref
        : updatedCell?.contract_ref !== activeCell.contract_ref;
      if (
        !updatedCell
        || updatedCell.status === "free"
        || identityChanged
      ) {
        closeCellDialog();
      } else {
        state.activeOccupiedCell = updatedCell;
        renderOccupiedOperationalDetails(updatedCell);
        if (updatedCell.block_kind === "lost_key") {
          loadBlockedClientName(updatedCell);
        } else if (!updatedCell.block_kind) {
          loadOpenedClientName(updatedCell);
        }
      }
    }
    populateHeightFilter(state.cells);
    renderStats();
    clearError();
    elements.updatedAt.textContent = `Обновлено: ${new Intl.DateTimeFormat("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date())}`;
    if (elements.search.value.trim()) {
      await runPrivateSearch();
    } else {
      renderGrid();
    }
  } catch (error) {
    showError(errorMessage(error, NETWORK_ERROR_MESSAGE));
    clearDisplayedData();
    elements.grid.setAttribute("aria-busy", "false");
  } finally {
    elements.grid.setAttribute("aria-busy", "false");
  }
}

elements.search.addEventListener("input", scheduleSearch);
elements.employeeForm.addEventListener("submit", saveEmployeeSelection);
elements.employeeDialog.addEventListener("cancel", (event) => event.preventDefault());
elements.employeeSelect.addEventListener("change", () => {
  if (elements.employeeSelect.value) selectEmployee(elements.employeeSelect.value);
  else if (!elements.employeeDialog.open) elements.employeeDialog.showModal();
});
elements.employeeOpenSettings.addEventListener("click", () => {
  elements.employeeDialog.close();
  document.getElementById("adminOpen")?.click();
});
elements.operationResultClose.addEventListener("click", () => elements.operationResultDialog.close());
elements.operationResultDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  elements.operationResultDialog.close();
});
elements.status.addEventListener("change", renderGrid);
elements.height.addEventListener("change", renderGrid);
elements.dialogClose.addEventListener("click", closeCellDialog);
elements.blockReleaseAction.addEventListener("click", releaseBlockedCell);
elements.privateToggle.addEventListener("click", togglePrivateDetails);
elements.historyToggle.addEventListener("click", toggleRenewalHistory);
elements.renewAction.addEventListener("click", openRenewalDialog);
elements.closeAction.addEventListener("click", openClosureDialog);
elements.editAction.addEventListener("click", openEditDialog);
elements.documentAction.addEventListener("click", openDocumentDialog);
elements.documentForm.addEventListener("submit", submitDocument);
elements.documentDialogClose.addEventListener("click", closeDocumentDialog);
elements.documentBack.addEventListener("click", closeDocumentDialog);
elements.documentDialog.addEventListener("cancel", (event) => event.preventDefault());
elements.editDialogClose.addEventListener("click", closeEditDialog);
elements.editBack.addEventListener("click", closeEditDialog);
elements.editForm.addEventListener("submit", submitEdit);
elements.editDialog.addEventListener("cancel", (event) => event.preventDefault());
elements.dialog.addEventListener("cancel", (event) => event.preventDefault());
elements.closureReason.addEventListener("change", requestClosureQuote);
elements.closureForm.addEventListener("submit", submitClosure);
elements.closureBack.addEventListener("click", () => closeClosureDialog(true));
elements.closureDialogClose.addEventListener("click", () => closeClosureDialog(true));
elements.closureDialog.addEventListener("cancel", (event) => event.preventDefault());
document.querySelectorAll("[data-date-input]").forEach((input) => {
  input.addEventListener("keydown", handleDateKeydown);
  input.addEventListener("paste", handleDatePaste);
  input.addEventListener("input", normalizeDateInput);
  updateDateInputValidity(input);
});

elements.renewalEndDate.addEventListener("input", () => {
  syncRenewalDaysFromEnd();
  scheduleRenewalQuote();
});
elements.renewalDays.addEventListener("input", () => {
  syncRenewalEndFromDays();
  scheduleRenewalQuote();
});
elements.renewalForm.addEventListener("submit", submitRenewal);
elements.renewalBack.addEventListener("click", () => closeRenewalDialog(true));
elements.renewalDialogClose.addEventListener("click", () => closeRenewalDialog(true));
elements.renewalDialog.addEventListener("cancel", (event) => event.preventDefault());
elements.rentalStartDate.addEventListener("input", () => {
  if (elements.rentalDays.value) {
    syncEndFromDays();
  } else {
    syncDaysFromDates();
  }
  scheduleRentalQuote();
});
elements.rentalEndDate.addEventListener("input", () => {
  syncDaysFromDates();
  scheduleRentalQuote();
});
elements.rentalDays.addEventListener("input", () => {
  syncEndFromDays();
  scheduleRentalQuote();
});
elements.rentalForm.addEventListener("submit", (event) => event.preventDefault());
elements.rentalDialogClose.addEventListener("click", closeRentalCalculator);
elements.rentalBack.addEventListener("click", closeRentalCalculator);
elements.rentalContinue.addEventListener("click", openContractForm);
elements.manualOccupy.addEventListener("click", openManualOccupationDialog);
elements.rentalDialog.addEventListener("cancel", (event) => event.preventDefault());
elements.manualOccupationForm.addEventListener("submit", occupyManualCell);
elements.manualOccupationClose.addEventListener("click", closeManualOccupationDialog);
elements.manualOccupationBack.addEventListener("click", closeManualOccupationDialog);
elements.manualOccupationDialog.addEventListener("cancel", (event) => event.preventDefault());
elements.contractForm.addEventListener("submit", submitContract);
elements.statementImport.addEventListener("click", importStatementData);
elements.statementFile.addEventListener("change", () => {
  elements.statementFileState.textContent = elements.statementFile.files.length
    ? "DOCX выбран"
    : "Файл не выбран";
  setStatementImportStatus();
});
elements.contractBack.addEventListener("click", backToRentalCalculator);
elements.contractDialogClose.addEventListener("click", cancelContractWorkflow);
elements.contractDialog.addEventListener("cancel", (event) => event.preventDefault());

window.addEventListener("safe-cells:employees-changed", loadEmployeeDirectory);
window.addEventListener("safe-cells:refresh", refreshCells);
loadEmployeeDirectory();
refreshCells();
window.setInterval(() => {
  refreshCells();
  loadEmployeeDirectory();
}, 15_000);
