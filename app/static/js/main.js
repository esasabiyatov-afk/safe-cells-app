"use strict";

const STATUS_LABELS = {
  free: "Свободна",
  normal: "В норме",
  expiring: "Истекает",
  overdue: "Просрочена",
};

const NETWORK_ERROR_MESSAGE = "Не удалось получить данные с сетевого диска. Проверьте подключение к сети";
const RUSSIAN_MONTHS = [
  "", "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

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
  absAuthenticated: false,
  absStartupChecked: false,
  absLoginSubmitting: false,
  absBulkRefreshing: false,
  absRefreshPending: false,
  absImporting: false,
  absSearchSequence: 0,
  absSelectedCustomerId: null,
  editStatementImporting: false,
  editStatementImportSequence: 0,
  editAbsImporting: false,
  editAbsSearchSequence: 0,
  editAbsCustomerId: null,
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
  reminderOperationIds: new Map(),
  reminderSubmittingContracts: new Set(),
  reminderPhoneSelecting: false,
  reminderPhoneResolver: null,
  employeeDirectory: [],
  adminIdentity: null,
  selectedKind: null,
  executorResolver: null,
  operationUndo: null,
  operationUndoSubmitting: false,
  cardUndo: null,
  cardUndoSource: null,
  cardUndoSubmitting: false,
  uiPreferences: { display_date_words: true, show_ui_hints: true },
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
  statExpiring: document.getElementById("statExpiring"),
  statOverdue: document.getElementById("statOverdue"),
  dialog: document.getElementById("cellDialog"),
  dialogClose: document.getElementById("dialogClose"),
  occupiedUndoAction: document.getElementById("occupiedUndoAction"),
  dialogTitle: document.getElementById("dialogTitle"),
  dialogStatus: document.getElementById("dialogStatus"),
  dialogSize: document.getElementById("dialogSize"),
  dialogClientLabel: document.getElementById("dialogClientLabel"),
  dialogClient: document.getElementById("dialogClient"),
  dialogStartDate: document.getElementById("dialogStartDate"),
  dialogEndDate: document.getElementById("dialogEndDate"),
  dialogRentDays: document.getElementById("dialogRentDays"),
  dialogDays: document.getElementById("dialogDays"),
  legacyContractNote: document.getElementById("legacyContractNote"),
  cellDialogKicker: document.getElementById("cellDialogKicker"),
  privateCardSection: document.getElementById("privateCardSection"),
  contractCardActions: document.getElementById("contractCardActions"),
  blockedCardActions: document.getElementById("blockedCardActions"),
  blockedActionError: document.getElementById("blockedActionError"),
  blockReleaseAction: document.getElementById("blockReleaseAction"),
  reminderPanel: document.getElementById("reminderPanel"),
  reminderStatus: document.getElementById("reminderStatus"),
  reminderAction: document.getElementById("reminderAction"),
  privateToggle: document.getElementById("privateToggle"),
  privateError: document.getElementById("privateError"),
  privateDetails: document.getElementById("privateDetails"),
  privateIdCardNumber: document.getElementById("privateIdCardNumber"),
  privateClientPhone: document.getElementById("privateClientPhone"),
  privateClientWhatsappPhone: document.getElementById("privateClientWhatsappPhone"),
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
  editClientPhone: document.getElementById("editClientPhone"),
  editClientWhatsappPhone: document.getElementById("editClientWhatsappPhone"),
  editAccountNumber: document.getElementById("editAccountNumber"),
  editIdCardNumber: document.getElementById("editIdCardNumber"),
  editIdCardIssuer: document.getElementById("editIdCardIssuer"),
  editIdCardIssueDate: document.getElementById("editIdCardIssueDate"),
  editLegacyNote: document.getElementById("editLegacyNote"),
  editStatementImportSection: document.getElementById("editStatementImportSection"),
  editStatementFile: document.getElementById("editStatementFile"),
  editStatementFileState: document.getElementById("editStatementFileState"),
  editStatementImportStatus: document.getElementById("editStatementImportStatus"),
  editAbsSearch: document.getElementById("editAbsSearch"),
  editAbsSearchButton: document.getElementById("editAbsSearchButton"),
  editAbsImportHint: document.getElementById("editAbsImportHint"),
  editAbsStatus: document.getElementById("editAbsStatus"),
  editAbsResults: document.getElementById("editAbsResults"),
  editAbsAccounts: document.getElementById("editAbsAccounts"),
  editDepositField: document.getElementById("editDepositField"),
  editDepositAmount: document.getElementById("editDepositAmount"),
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
  employeeAdminLogin: document.getElementById("employeeAdminLogin"),
  employeeAdminLoginTitle: document.getElementById("employeeAdminLoginTitle"),
  employeeAdminLoginNote: document.getElementById("employeeAdminLoginNote"),
  employeeAdminNameField: document.getElementById("employeeAdminNameField"),
  employeeAdminName: document.getElementById("employeeAdminName"),
  employeeAdminPassword: document.getElementById("employeeAdminPassword"),
  employeeAdminPasswordConfirmField: document.getElementById("employeeAdminPasswordConfirmField"),
  employeeAdminPasswordConfirm: document.getElementById("employeeAdminPasswordConfirm"),
  employeeAdminBack: document.getElementById("employeeAdminBack"),
  employeeAdminSubmit: document.getElementById("employeeAdminSubmit"),
  absLoginDialog: document.getElementById("absLoginDialog"),
  absLoginForm: document.getElementById("absLoginForm"),
  absLoginName: document.getElementById("absLoginName"),
  absLoginPassword: document.getElementById("absLoginPassword"),
  absLoginError: document.getElementById("absLoginError"),
  absLoginLater: document.getElementById("absLoginLater"),
  absLoginSubmit: document.getElementById("absLoginSubmit"),
  absRefreshClients: document.getElementById("absRefreshClients"),
  reminderPhoneDialog: document.getElementById("reminderPhoneDialog"),
  reminderPhoneOptions: document.getElementById("reminderPhoneOptions"),
  reminderPhoneError: document.getElementById("reminderPhoneError"),
  reminderPhoneCancel: document.getElementById("reminderPhoneCancel"),
  adminOpen: document.getElementById("adminOpen"),
  executorDialog: document.getElementById("executorDialog"),
  executorChoices: document.getElementById("executorChoices"),
  executorError: document.getElementById("executorError"),
  executorCancel: document.getElementById("executorCancel"),
  operationResultDialog: document.getElementById("operationResultDialog"),
  operationResultTitle: document.getElementById("operationResultTitle"),
  operationResultSummary: document.getElementById("operationResultSummary"),
  operationDocumentsSuccess: document.getElementById("operationDocumentsSuccess"),
  operationDocumentList: document.getElementById("operationDocumentList"),
  operationDocumentsWarning: document.getElementById("operationDocumentsWarning"),
  operationUndoOpen: document.getElementById("operationUndoOpen"),
  operationUndoPanel: document.getElementById("operationUndoPanel"),
  operationUndoReason: document.getElementById("operationUndoReason"),
  operationUndoError: document.getElementById("operationUndoError"),
  operationUndoBack: document.getElementById("operationUndoBack"),
  operationUndoConfirm: document.getElementById("operationUndoConfirm"),
  operationResultClose: document.getElementById("operationResultClose"),
  paymentCopyPanel: document.getElementById("paymentCopyPanel"),
  paymentCopyStatus: document.getElementById("paymentCopyStatus"),
  paymentRentPurpose: document.getElementById("paymentRentPurpose"),
  paymentRentAmountLabel: document.getElementById("paymentRentAmountLabel"),
  paymentRentAmount: document.getElementById("paymentRentAmount"),
  paymentPenaltyGroup: document.getElementById("paymentPenaltyGroup"),
  paymentPenaltyPurpose: document.getElementById("paymentPenaltyPurpose"),
  paymentPenaltyAmount: document.getElementById("paymentPenaltyAmount"),
  cardUndoDialog: document.getElementById("cardUndoDialog"),
  cardUndoTitle: document.getElementById("cardUndoTitle"),
  cardUndoNote: document.getElementById("cardUndoNote"),
  cardUndoReason: document.getElementById("cardUndoReason"),
  cardUndoError: document.getElementById("cardUndoError"),
  cardUndoBack: document.getElementById("cardUndoBack"),
  cardUndoConfirm: document.getElementById("cardUndoConfirm"),
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
  rentalUndoAction: document.getElementById("rentalUndoAction"),
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
  statementImportStatus: document.getElementById("statementImportStatus"),
  absCustomerSearch: document.getElementById("absCustomerSearch"),
  absCustomerSearchButton: document.getElementById("absCustomerSearchButton"),
  absCustomerSearchStatus: document.getElementById("absCustomerSearchStatus"),
  absCustomerResults: document.getElementById("absCustomerResults"),
  absAccountResults: document.getElementById("absAccountResults"),
  clientFullName: document.getElementById("clientFullName"),
  clientPhone: document.getElementById("clientPhone"),
  clientWhatsappPhone: document.getElementById("clientWhatsappPhone"),
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

function fillEmployeeSelect(select, employees, selectedId, selectedKind, admin) {
  select.replaceChildren(new Option("Выберите сотрудника", ""));
  const adminLabel = admin?.full_name
    ? `Администратор — ${admin.full_name}`
    : "Администратор";
  select.append(new Option(adminLabel, "__admin__"));
  for (const employee of employees) {
    select.append(new Option(employee.full_name, employee.employee_id));
  }
  select.value = selectedKind === "admin" ? "__admin__" : (selectedId || "");
}

function renderEmployeeChoices(employees, selectedId, selectedKind, admin) {
  const fragment = document.createDocumentFragment();
  const adminButton = document.createElement("button");
  adminButton.type = "button";
  adminButton.className = "employee-choice-card employee-choice-card--admin";
  adminButton.textContent = admin?.full_name
    ? `Администратор — ${admin.full_name}`
    : "Администратор";
  if (selectedKind === "admin") adminButton.classList.add("is-selected");
  adminButton.addEventListener("click", openAdminStartupLogin);
  fragment.append(adminButton);
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
  const adminLoginOpen = !elements.employeeAdminLogin.hidden;
  state.employeeDirectory = employees;
  state.adminIdentity = payload.admin || null;
  state.selectedKind = payload.selected_kind || null;
  fillEmployeeSelect(
    elements.employeeSelect,
    employees,
    payload.selected_employee_id,
    state.selectedKind,
    state.adminIdentity,
  );
  renderEmployeeChoices(
    employees,
    payload.selected_employee_id,
    state.selectedKind,
    state.adminIdentity,
  );
  elements.adminOpen.hidden = state.selectedKind !== "admin";
  if (!adminLoginOpen) {
    elements.employeeAdminLogin.hidden = true;
    elements.employeeChoices.hidden = false;
  }
  elements.employeeError.hidden = true;
  elements.employeeOpenSettings.hidden = true;
  elements.employeeDialogNote.textContent =
    "Выберите сотрудника или администратора. Выбор действует до закрытия приложения.";
  const adminDialog = document.getElementById("adminDialog");
  if (payload.selection_required && !adminDialog?.open && !elements.employeeDialog.open) {
    elements.employeeDialog.showModal();
  }
  if (!payload.selection_required && !state.absStartupChecked) {
    state.absStartupChecked = true;
    checkAbsSessionAtStartup();
  }
}

function openAdminStartupLogin() {
  if (state.employeeSubmitting) return;
  const configured = state.adminIdentity?.configured === true;
  const hasPassword = state.adminIdentity?.password_configured === true;
  elements.employeeChoices.hidden = true;
  elements.employeeAdminLogin.hidden = false;
  elements.employeeAdminNameField.hidden = configured;
  elements.employeeAdminPasswordConfirmField.hidden = configured || hasPassword;
  elements.employeeAdminName.required = !configured;
  elements.employeeAdminPassword.required = true;
  elements.employeeAdminPasswordConfirm.required = !configured && !hasPassword;
  elements.employeeAdminPassword.autocomplete = hasPassword ? "current-password" : "new-password";
  elements.employeeAdminLoginTitle.textContent = configured
    ? `Вход: ${state.adminIdentity.full_name}`
    : "Первоначальная настройка администратора";
  elements.employeeAdminLoginNote.textContent = configured
    ? "Введите пароль один раз. Повторно до закрытия приложения он не потребуется."
    : hasPassword
      ? "Введите ФИО начальника и действующий административный пароль."
      : "Введите ФИО начальника и создайте простой пароль. Эти данные сохранятся в общей базе.";
  elements.employeeAdminPassword.value = "";
  elements.employeeAdminPasswordConfirm.value = "";
  elements.employeeError.hidden = true;
  (configured ? elements.employeeAdminPassword : elements.employeeAdminName).focus();
}

function closeAdminStartupLogin() {
  elements.employeeAdminLogin.hidden = true;
  elements.employeeChoices.hidden = false;
  elements.employeeError.hidden = true;
}

function openAbsLoginDialog() {
  if (state.absLoginSubmitting || elements.absLoginDialog.open) return;
  elements.absLoginError.hidden = true;
  elements.absLoginPassword.value = "";
  elements.absLoginDialog.showModal();
  elements.absLoginName.focus();
}

function closeAbsLoginDialog() {
  if (state.absLoginSubmitting) return;
  state.absRefreshPending = false;
  if (elements.absLoginDialog.open) elements.absLoginDialog.close();
  elements.absLoginPassword.value = "";
  elements.absLoginError.hidden = true;
}

async function checkAbsSessionAtStartup() {
  try {
    const response = await fetch(elements.body.dataset.absStatusUrl, {
      cache: "no-store",
      headers: {
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
    });
    const payload = await response.json();
    state.absAuthenticated = response.ok && payload.authenticated === true;
  } catch (_error) {
    state.absAuthenticated = false;
  }
  if (!state.absAuthenticated) openAbsLoginDialog();
}

async function loginToAbs(event) {
  event.preventDefault();
  if (!elements.absLoginForm.checkValidity()) {
    elements.absLoginForm.reportValidity();
    return;
  }
  state.absLoginSubmitting = true;
  elements.absLoginSubmit.disabled = true;
  elements.absLoginLater.disabled = true;
  elements.absLoginSubmit.textContent = "Вход…";
  elements.absLoginError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.absLoginUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
      body: JSON.stringify({
        login: elements.absLoginName.value,
        password: elements.absLoginPassword.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось войти в АБС");
    state.absAuthenticated = true;
    elements.absLoginDialog.close();
    elements.absLoginForm.reset();
    if (state.absRefreshPending) {
      state.absRefreshPending = false;
      showSuccess(absRefreshMessage(payload.sync));
      if (payload.sync?.updated_count) await refreshCells();
    } else if (payload.sync?.updated_count) {
      showSuccess(absRefreshMessage(payload.sync));
      await refreshCells();
    }
  } catch (error) {
    state.absAuthenticated = false;
    elements.absLoginError.textContent = errorMessage(error, "Не удалось войти в АБС");
    elements.absLoginError.hidden = false;
  } finally {
    state.absLoginSubmitting = false;
    elements.absLoginSubmit.disabled = false;
    elements.absLoginLater.disabled = false;
    elements.absLoginSubmit.textContent = "Войти";
  }
}

function absRefreshMessage(sync) {
  const linked = Number(sync?.linked_count || 0);
  const updated = Number(sync?.updated_count || 0);
  const skipped = Number(sync?.skipped_count || 0);
  if (!linked) {
    return "Нет активных договоров с сохранённым ID клиента АБС.";
  }
  const parts = [
    updated
      ? `Обновлено клиентов: ${updated}.`
      : "Актуальные данные проверены, изменений нет.",
  ];
  if (skipped) parts.push(`Не удалось обновить: ${skipped}.`);
  if (sync?.warning) parts.push(sync.warning);
  return parts.join(" ");
}

async function refreshAbsClients() {
  if (state.absBulkRefreshing) return;
  state.absBulkRefreshing = true;
  state.absRefreshPending = true;
  elements.absRefreshClients.disabled = true;
  elements.absRefreshClients.textContent = "Обновление…";
  clearSuccess();
  try {
    const sync = await fetchAbsJson(elements.body.dataset.absRefreshUrl, {});
    state.absRefreshPending = false;
    showSuccess(absRefreshMessage(sync));
    if (sync.updated_count) await refreshCells();
  } catch (error) {
    if (!elements.absLoginDialog.open) {
      state.absRefreshPending = false;
      elements.errorMessage.textContent = errorMessage(
        error, "Не удалось обновить данные клиентов из АБС.",
      );
      elements.errorBanner.hidden = false;
    }
  } finally {
    state.absBulkRefreshing = false;
    elements.absRefreshClients.disabled = false;
    elements.absRefreshClients.textContent = "Обновить клиентов из АБС";
  }
}

async function selectAdmin() {
  if (state.employeeSubmitting) return;
  const configured = state.adminIdentity?.configured === true;
  const hasPassword = state.adminIdentity?.password_configured === true;
  const payload = configured
    ? {password: elements.employeeAdminPassword.value}
    : {
        operation_id: createOperationId(),
        full_name: elements.employeeAdminName.value,
        password: elements.employeeAdminPassword.value,
        password_confirmation: hasPassword
          ? elements.employeeAdminPassword.value
          : elements.employeeAdminPasswordConfirm.value,
      };
  state.employeeSubmitting = true;
  elements.employeeAdminSubmit.disabled = true;
  elements.employeeError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.adminSelectUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Не удалось войти как администратор");
    state.selectedKind = "admin";
    window.dispatchEvent(new CustomEvent(
      "safe-cells:admin-session",
      {detail: {token: result.admin_token}},
    ));
    closeAdminStartupLogin();
    state.absStartupChecked = true;
    await loadEmployeeDirectory();
    if (elements.employeeDialog.open) elements.employeeDialog.close();
    state.absAuthenticated = false;
    openAbsLoginDialog();
  } catch (error) {
    elements.employeeError.textContent = errorMessage(error, "Не удалось войти как администратор");
    elements.employeeError.hidden = false;
  } finally {
    state.employeeSubmitting = false;
    elements.employeeAdminSubmit.disabled = false;
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
    state.selectedKind = "employee";
    state.absStartupChecked = true;
    window.dispatchEvent(new CustomEvent("safe-cells:admin-session", {detail: {token: null}}));
    await loadEmployeeDirectory();
    if (elements.employeeDialog.open) elements.employeeDialog.close();
    state.absAuthenticated = false;
    openAbsLoginDialog();
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

function chooseDocumentExecutor() {
  if (state.selectedKind !== "admin") return Promise.resolve(null);
  if (!state.employeeDirectory.length) {
    return Promise.reject(new Error(
      "Нет активных сотрудников для документов. Добавьте сотрудника в настройках.",
    ));
  }
  elements.executorError.hidden = true;
  const fragment = document.createDocumentFragment();
  for (const employee of state.employeeDirectory) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "employee-choice-card";
    button.textContent = employee.full_name;
    button.addEventListener("click", () => {
      const resolver = state.executorResolver;
      state.executorResolver = null;
      elements.executorDialog.close();
      resolver?.(employee.employee_id);
    });
    fragment.append(button);
  }
  elements.executorChoices.replaceChildren(fragment);
  if (!elements.executorDialog.open) elements.executorDialog.showModal();
  return new Promise((resolve) => {
    state.executorResolver = resolve;
  });
}

function cancelExecutorSelection() {
  const resolver = state.executorResolver;
  state.executorResolver = null;
  if (elements.executorDialog.open) elements.executorDialog.close();
  resolver?.(null);
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

async function downloadGeneratedDocument(documentInfo, button) {
  button.disabled = true;
  const previousText = button.textContent;
  button.textContent = "Подготовка…";
  try {
    const response = await fetch(elements.body.dataset.documentDownloadUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": elements.body.dataset.privateToken,
      },
      body: JSON.stringify({download_id: documentInfo.download_id}),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.message || "Не удалось скачать документ");
    }
    const blob = await response.blob();
    const downloadUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = downloadUrl;
    anchor.download = documentInfo.file_name || "Документ.docx";
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
    button.textContent = "Скачано";
  } catch (error) {
    button.disabled = false;
    button.textContent = previousText;
    showError(errorMessage(error, "Не удалось скачать документ"));
  }
}

function clearPaymentCopy() {
  elements.paymentCopyPanel.hidden = true;
  elements.paymentCopyStatus.textContent = "";
  elements.paymentRentPurpose.value = "";
  elements.paymentRentAmount.value = "";
  elements.paymentPenaltyPurpose.value = "";
  elements.paymentPenaltyAmount.value = "";
  elements.paymentPenaltyGroup.hidden = true;
}

function showPaymentCopy(paymentCopy) {
  clearPaymentCopy();
  const rent = paymentCopy?.rent;
  if (
    !rent
    || typeof rent.purpose !== "string"
    || !Number.isInteger(rent.amount)
    || typeof rent.amount_label !== "string"
  ) {
    return;
  }
  elements.paymentRentPurpose.value = rent.purpose;
  elements.paymentRentAmount.value = String(rent.amount);
  elements.paymentRentAmountLabel.textContent = rent.amount_label;
  const penalty = paymentCopy?.penalty;
  if (
    penalty
    && typeof penalty.purpose === "string"
    && Number.isInteger(penalty.amount)
  ) {
    elements.paymentPenaltyPurpose.value = penalty.purpose;
    elements.paymentPenaltyAmount.value = String(penalty.amount);
    elements.paymentPenaltyGroup.hidden = false;
  }
  elements.paymentCopyPanel.hidden = false;
}

async function copyPaymentField(button) {
  const input = document.getElementById(button.dataset.copyTarget || "");
  if (!(input instanceof HTMLInputElement) || !input.value) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(input.value);
    } else {
      input.select();
      if (!document.execCommand("copy")) throw new Error("copy unavailable");
      input.setSelectionRange(0, 0);
    }
    elements.paymentCopyStatus.textContent = "Скопировано";
    window.setTimeout(() => {
      if (elements.paymentCopyStatus.textContent === "Скопировано") {
        elements.paymentCopyStatus.textContent = "";
      }
    }, 1600);
  } catch (_error) {
    input.focus();
    input.select();
    elements.paymentCopyStatus.textContent = "Выделено — нажмите Ctrl+C";
  }
}

function showOperationResult(summary, payload) {
  const documents = Array.isArray(payload.documents)
    ? payload.documents
    : payload.file_name ? [payload.file_name] : [];
  elements.operationResultTitle.textContent = "Операция выполнена";
  elements.operationResultSummary.textContent = summary;
  showPaymentCopy(payload.payment_copy);
  state.operationUndo = (
    payload.undo
    && typeof payload.undo.original_operation_id === "string"
    && typeof payload.undo.contract_ref === "string"
    && typeof payload.undo.cell_number === "string"
  ) ? {
      ...payload.undo,
      cancellation_operation_id: createOperationId(),
    }
    : null;
  state.operationUndoSubmitting = false;
  elements.operationUndoOpen.hidden = state.operationUndo === null;
  elements.operationUndoPanel.hidden = true;
  elements.operationUndoReason.value = "client_changed";
  elements.operationUndoReason.disabled = false;
  elements.operationUndoError.hidden = true;
  elements.operationUndoError.textContent = "";
  elements.operationUndoConfirm.disabled = false;
  elements.operationUndoBack.disabled = false;
  elements.operationResultClose.disabled = false;
  elements.operationDocumentList.replaceChildren();
  for (const generatedDocument of documents) {
    const item = document.createElement("li");
    const fileName = typeof generatedDocument === "string"
      ? generatedDocument
      : generatedDocument.file_name || generatedDocument.display_name || "Документ DOCX";
    const label = document.createElement("span");
    label.textContent = fileName;
    item.append(label);
    if (
      generatedDocument
      && typeof generatedDocument === "object"
      && typeof generatedDocument.download_id === "string"
    ) {
      const download = document.createElement("button");
      download.type = "button";
      download.className = "secondary-button document-download-button";
      download.textContent = "Скачать";
      download.addEventListener("click", () => {
        downloadGeneratedDocument(generatedDocument, download);
      });
      item.append(download);
    }
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
  elements.operationResultClose.focus();
}

function closeOperationResult() {
  if (state.operationUndoSubmitting) return;
  state.operationUndo = null;
  elements.operationUndoPanel.hidden = true;
  clearPaymentCopy();
  elements.operationResultDialog.close();
}

function openOperationUndo() {
  if (!state.operationUndo || state.operationUndoSubmitting) return;
  elements.operationUndoOpen.hidden = true;
  elements.operationUndoPanel.hidden = false;
  elements.operationUndoReason.focus();
}

function closeOperationUndo() {
  if (state.operationUndoSubmitting) return;
  elements.operationUndoPanel.hidden = true;
  elements.operationUndoOpen.hidden = state.operationUndo === null;
  elements.operationUndoError.hidden = true;
  elements.operationUndoError.textContent = "";
}

function setOperationUndoSubmitting(submitting) {
  state.operationUndoSubmitting = submitting;
  elements.operationUndoReason.disabled = submitting;
  elements.operationUndoConfirm.disabled = submitting;
  elements.operationUndoBack.disabled = submitting;
  elements.operationResultClose.disabled = submitting;
  elements.operationUndoConfirm.textContent = submitting
    ? "Возврат состояния…"
    : "Да, вернуть состояние назад";
}

async function submitOperationUndo() {
  const undo = state.operationUndo;
  if (!undo || state.operationUndoSubmitting) return;
  elements.operationUndoError.hidden = true;
  elements.operationUndoError.textContent = "";
  setOperationUndoSubmitting(true);
  try {
    const response = await fetch(elements.body.dataset.actionCancelUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        cancellation_operation_id: undo.cancellation_operation_id,
        original_operation_id: undo.original_operation_id,
        contract_ref: undo.contract_ref,
        cell_number: undo.cell_number,
        reason_code: elements.operationUndoReason.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось отменить действие");
    }
    const warning = payload.warning ? ` ${payload.warning}` : "";
    elements.operationResultTitle.textContent = "Действие отменено";
    elements.operationResultSummary.textContent = payload.action_kind === "renewal"
      ? `Продление ячейки № ${payload.cell_number} отменено. Дата окончания снова ${formatDate(payload.restored_end_date)}.${warning}`
      : payload.action_kind === "closure"
        ? `Закрытие договора по ячейке № ${payload.cell_number} отменено. Договор снова активен до ${formatDate(payload.restored_end_date)}.${warning}`
        : `Открытие ячейки № ${payload.cell_number} отменено. Ячейка снова свободна.${warning}`;
    clearPaymentCopy();
    elements.operationDocumentsSuccess.hidden = true;
    elements.operationDocumentsWarning.hidden = true;
    elements.operationUndoPanel.hidden = true;
    elements.operationUndoOpen.hidden = true;
    state.operationUndo = null;
    await refreshCells();
  } catch (error) {
    elements.operationUndoError.textContent = errorMessage(
      error,
      "Не удалось отменить действие",
    );
    elements.operationUndoError.hidden = false;
  } finally {
    setOperationUndoSubmitting(false);
  }
}

function setQuietUndoButton(button, candidate) {
  button.hidden = !candidate;
  button.disabled = false;
  button.title = candidate
    ? "Вернуть состояние до последнего открытия, продления или закрытия"
    : "";
}

function openCardUndo(source) {
  if (state.cardUndoSubmitting) return;
  const cell = source === "rental"
    ? state.activeRentalCell
    : state.activeOccupiedCell;
  const candidate = cell?.cancellable_action;
  if (!candidate) return;
  state.cardUndo = {
    ...candidate,
    cancellation_operation_id: createOperationId(),
  };
  state.cardUndoSource = source;
  const labels = {
    opening: {
      title: "Отменить открытие ячейки?",
      note: "Договор будет помещён в архив как отменённый, а ячейка снова станет свободной.",
    },
    renewal: {
      title: "Отменить последнее продление?",
      note: "Дата окончания вернётся к прежней. Продление останется в истории с пометкой об отмене.",
    },
    closure: {
      title: "Отменить закрытие договора?",
      note: "Закрытый договор снова станет активным. Возврат возможен, только если состояние ячейки после закрытия не менялось.",
    },
  };
  const copy = labels[candidate.action_kind] || labels.opening;
  elements.cardUndoTitle.textContent = copy.title;
  elements.cardUndoNote.textContent = copy.note;
  elements.cardUndoReason.value = "client_changed";
  elements.cardUndoError.hidden = true;
  elements.cardUndoError.textContent = "";
  elements.cardUndoReason.disabled = false;
  elements.cardUndoBack.disabled = false;
  elements.cardUndoConfirm.disabled = false;
  if (source === "rental" && elements.rentalDialog.open) {
    elements.rentalDialog.close();
  } else if (source === "occupied" && elements.dialog.open) {
    elements.dialog.close();
  }
  elements.cardUndoDialog.showModal();
  elements.cardUndoReason.focus();
}

function closeCardUndo(returnToSource = true) {
  if (state.cardUndoSubmitting) return;
  const source = state.cardUndoSource;
  if (elements.cardUndoDialog.open) elements.cardUndoDialog.close();
  state.cardUndo = null;
  state.cardUndoSource = null;
  if (!returnToSource) return;
  if (source === "rental" && state.activeRentalCell) {
    elements.rentalDialog.showModal();
  } else if (source === "occupied" && state.activeOccupiedCell) {
    elements.dialog.showModal();
  }
}

function setCardUndoSubmitting(submitting) {
  state.cardUndoSubmitting = submitting;
  elements.cardUndoReason.disabled = submitting;
  elements.cardUndoBack.disabled = submitting;
  elements.cardUndoConfirm.disabled = submitting;
  elements.cardUndoConfirm.textContent = submitting
    ? "Возврат состояния…"
    : "Да, вернуть состояние назад";
}

async function submitCardUndo() {
  const undo = state.cardUndo;
  if (!undo || state.cardUndoSubmitting) return;
  elements.cardUndoError.hidden = true;
  elements.cardUndoError.textContent = "";
  setCardUndoSubmitting(true);
  try {
    const response = await fetch(elements.body.dataset.actionCancelUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        cancellation_operation_id: undo.cancellation_operation_id,
        original_operation_id: undo.original_operation_id,
        contract_ref: undo.contract_ref,
        cell_number: undo.cell_number,
        reason_code: elements.cardUndoReason.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось отменить действие");
    }
    if (elements.cardUndoDialog.open) elements.cardUndoDialog.close();
    state.cardUndo = null;
    state.cardUndoSource = null;
    state.activeOccupiedCell = null;
    state.activeRentalCell = null;
    state.activeQuote = null;
    state.activeOperationId = null;
    state.manualOperationId = null;
    await refreshCells();
    let successMessage = payload.message || "Действие отменено. Данные ячейки восстановлены.";
    if (payload.action_kind === "renewal" && payload.restored_end_date) {
      successMessage = `Продление ячейки № ${payload.cell_number} отменено. Дата окончания снова ${formatDate(payload.restored_end_date)}.`;
    } else if (payload.action_kind === "closure" && payload.restored_end_date) {
      successMessage = `Закрытие договора по ячейке № ${payload.cell_number} отменено. Договор снова активен до ${formatDate(payload.restored_end_date)}.`;
    }
    showSuccess(payload.warning ? `${successMessage} ${payload.warning}` : successMessage);
  } catch (error) {
    elements.cardUndoError.textContent = errorMessage(
      error,
      "Не удалось отменить действие",
    );
    elements.cardUndoError.hidden = false;
  } finally {
    setCardUndoSubmitting(false);
  }
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
  elements.statExpiring.textContent = state.counts.expiring;
  elements.statOverdue.textContent = state.counts.overdue;
}

function clearDisplayedData() {
  if (elements.cardUndoDialog.open && !state.cardUndoSubmitting) {
    closeCardUndo(false);
  }
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
  if (state.uiPreferences.display_date_words) {
    return `${day} ${RUSSIAN_MONTHS[month]} ${year} года`;
  }
  return new Intl.DateTimeFormat("ru-RU").format(new Date(year, month - 1, day));
}

function applyUiPreferences(preferences) {
  state.uiPreferences = {
    display_date_words: preferences?.display_date_words !== false,
    show_ui_hints: preferences?.show_ui_hints !== false,
  };
  elements.body.classList.toggle(
    "ui-hints-hidden",
    !state.uiPreferences.show_ui_hints,
  );
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
  setQuietUndoButton(elements.occupiedUndoAction, cell.cancellable_action);
  elements.dialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.dialogStatus.textContent = cell.block_kind === "lost_key"
    ? "Ключ утерян"
    : (cell.occupation_label || STATUS_LABELS[cell.status]);
  elements.dialogStatus.className = `status-badge ${cell.status}${
    cell.block_kind === "lost_key" ? " lost-key-label" : ""
  }`;
  elements.dialogSize.textContent = `${cell.height_mm}×${cell.width_mm}×${cell.depth_mm} мм`;
  if (cell.block_kind) {
    elements.legacyContractNote.hidden = true;
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
    elements.reminderPanel.hidden = true;
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
  const reminderEligible = cell.status === "expiring" || cell.status === "overdue";
  elements.reminderPanel.hidden = !reminderEligible;
  elements.reminderStatus.textContent = cell.reminder_status || "Не оповещён";
  elements.reminderAction.textContent = cell.reminder_count > 0
    ? "Напомнить повторно"
    : "Напомнить";
  elements.reminderAction.disabled = state.reminderSubmittingContracts.has(
    cell.contract_ref,
  );
  elements.privateCardSection.hidden = false;
  elements.contractCardActions.hidden = false;
  elements.blockedCardActions.hidden = true;
  elements.legacyContractNote.hidden = !cell.legacy_imported;
  if (cell.legacy_imported) {
    elements.legacyContractNote.textContent = cell.legacy_identity_complete && cell.legacy_deposit_known
      ? "Договор перенесён из старого отчёта. Исходная сумма оплаты и применённый тариф неизвестны, поэтому первичные документы повторно не формируются."
      : "Договор перенесён из старого отчёта. Сумма оплаты и применённый тариф неизвестны. Перед продлением или закрытием заполните недостающие реквизиты через «Редактировать данные».";
  }
  elements.renewAction.disabled = cell.legacy_imported && !cell.legacy_identity_complete;
  elements.closeAction.disabled = cell.legacy_imported && (!cell.legacy_identity_complete || !cell.legacy_deposit_known);
  elements.documentAction.disabled = Boolean(cell.legacy_imported);
  elements.renewAction.title = elements.renewAction.disabled ? "Сначала заполните реквизиты старого договора" : "";
  elements.closeAction.title = elements.closeAction.disabled ? "Сначала заполните реквизиты и фактический залог старого договора" : "";
  elements.documentAction.title = cell.legacy_imported ? "Исходная сумма и тариф старого договора неизвестны" : "";
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
  if (state.uiPreferences.display_date_words) {
    const isoDate = [
      parsed.getFullYear(),
      String(parsed.getMonth() + 1).padStart(2, "0"),
      String(parsed.getDate()).padStart(2, "0"),
    ].join("-");
    const time = new Intl.DateTimeFormat("ru-RU", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(parsed);
    return `${formatDate(isoDate)}, ${time}`;
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
  elements.privateClientPhone.textContent = "";
  elements.privateClientWhatsappPhone.textContent = "";
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
    if (renewal.cancelled) item.classList.add("is-cancelled");
    const title = document.createElement("strong");
    title.textContent = `${renewal.cancelled ? "Отменено · " : ""}${formatDate(renewal.new_start_date)} — ${formatDate(renewal.new_end_date)} · ${renewal.renewal_days} дн.`;
    const details = document.createElement("span");
    const penalty = renewal.penalty_days > 0
      ? `, штраф ${renewal.penalty_days} дн. — ${money(renewal.penalty_amount)}`
      : ", без штрафа";
    details.textContent = renewal.cancelled
      ? `Было продлено ${formatDate(renewal.renewal_date)} сотрудником ${renewal.created_by}; отменено сотрудником ${renewal.cancelled_by}. Причина: ${renewal.cancellation_reason || "не указана"}.`
      : `Продлено ${formatDate(renewal.renewal_date)} · сотрудник: ${renewal.created_by}, сумма ${money(renewal.renewal_price)}${penalty}`;
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
    elements.privateIdCardNumber.textContent = payload.id_card_number || "Не указано";
    elements.privateClientPhone.textContent = payload.client_phone || "Не указано";
    elements.privateClientWhatsappPhone.textContent = payload.client_whatsapp_phone || "Не указано";
    elements.privateIdCardIssuer.textContent = payload.id_card_issuer || "Не указано";
    elements.privateIdCardIssueDate.textContent = payload.id_card_issue_date ? formatDate(payload.id_card_issue_date) : "Не указано";
    elements.privateAccountNumber.textContent = payload.account_number || "Не указано";
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
  let documentEmployeeId;
  try {
    documentEmployeeId = await chooseDocumentExecutor();
  } catch (error) {
    elements.documentError.textContent = errorMessage(
      error, "Не удалось выбрать исполнителя",
    );
    elements.documentError.hidden = false;
    return;
  }
  if (state.selectedKind === "admin" && !documentEmployeeId) return;
  state.documentSubmitting = true;
  elements.documentSubmit.disabled = true;
  elements.documentError.hidden = true;
  try {
    const response = await fetch(elements.body.dataset.documentGenerateUrl, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Safe-Cells-Token": elements.body.dataset.privateToken},
      body: JSON.stringify({
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
        template_id: elements.documentTemplate.value,
        document_employee_id: documentEmployeeId,
      }),
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

function setEditStatementImportStatus(message = "", isError = false) {
  elements.editStatementImportStatus.textContent = message;
  elements.editStatementImportStatus.hidden = !message;
  elements.editStatementImportStatus.classList.toggle("is-error", isError);
}

function refreshEditControls() {
  const busy = state.editSubmitting || state.editStatementImporting || state.editAbsImporting;
  elements.editSubmit.disabled = busy;
  elements.editBack.disabled = busy;
  elements.editDialogClose.disabled = busy;
  elements.editStatementFile.disabled = busy;
  elements.editAbsSearch.disabled = busy || Boolean(state.editAbsCustomerId);
  elements.editAbsSearchButton.disabled = busy;
}

function setEditAbsStatus(message = "", isError = false) {
  elements.editAbsStatus.textContent = message;
  elements.editAbsStatus.hidden = !message;
  elements.editAbsStatus.classList.toggle("is-error", isError);
}

function renderAbsAccounts(container, accounts, targetInput) {
  const fragment = document.createDocumentFragment();
  if (accounts.length) {
    const heading = document.createElement("p");
    heading.className = "abs-account-heading";
    heading.textContent = "Выберите счёт для договора:";
    fragment.append(heading);
  }
  for (const account of accounts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "abs-account-button";
    button.textContent = account.account_no + " · " + account.currency + " · "
      + account.product + " · " + account.status + " · баланс " + account.balance;
    if (targetInput.value.trim() === account.account_no) {
      button.classList.add("is-selected");
    }
    button.addEventListener("click", () => {
      targetInput.value = account.account_no;
      container.querySelectorAll(".abs-account-button").forEach((item) => {
        item.classList.toggle("is-selected", item === button);
      });
    });
    fragment.append(button);
  }
  container.replaceChildren(fragment);
}

function prepareEditAbsImport(absCustomerId) {
  state.editAbsSearchSequence += 1;
  state.editAbsImporting = false;
  state.editAbsCustomerId = absCustomerId || null;
  elements.editAbsSearch.value = absCustomerId || "";
  elements.editAbsResults.replaceChildren();
  elements.editAbsAccounts.replaceChildren();
  elements.editAbsImportHint.textContent = absCustomerId
    ? "ID клиента сохранён в договоре"
    : "Для этого договора ID клиента АБС ещё не сохранён";
  elements.editAbsSearchButton.textContent = absCustomerId
    ? "Обновить по ID"
    : "Найти клиента";
  setEditAbsStatus();
  refreshEditControls();
}

async function searchEditAbsCustomers() {
  if (state.editAbsCustomerId) {
    await importEditAbsCustomer(state.editAbsCustomerId);
    return;
  }
  const query = elements.editAbsSearch.value.trim();
  if (!query) {
    setEditAbsStatus("Введите ID клиента или ФИО.", true);
    return;
  }
  const sequence = ++state.editAbsSearchSequence;
  state.editAbsImporting = true;
  elements.editAbsResults.replaceChildren();
  elements.editAbsAccounts.replaceChildren();
  setEditAbsStatus("Поиск клиента в АБС…");
  refreshEditControls();
  try {
    const payload = await fetchAbsJson(elements.body.dataset.absSearchUrl, {query});
    if (sequence !== state.editAbsSearchSequence) return;
    const results = Array.isArray(payload.results) ? payload.results : [];
    const fragment = document.createDocumentFragment();
    for (const result of results) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "abs-customer-result";
      button.textContent = "ID " + result.customer_id + " — " + result.summary;
      button.addEventListener("click", () => importEditAbsCustomer(result.customer_id));
      fragment.append(button);
    }
    elements.editAbsResults.replaceChildren(fragment);
    setEditAbsStatus(
      results.length ? "Найдено: " + results.length + ". Выберите клиента." : "Клиент не найден.",
      results.length === 0,
    );
  } catch (error) {
    if (sequence === state.editAbsSearchSequence) {
      setEditAbsStatus(errorMessage(error, "Не удалось выполнить поиск в АБС."), true);
    }
  } finally {
    if (sequence === state.editAbsSearchSequence) {
      state.editAbsImporting = false;
      refreshEditControls();
    }
  }
}

async function importEditAbsCustomer(customerId) {
  const sequence = ++state.editAbsSearchSequence;
  state.editAbsImporting = true;
  setEditAbsStatus("Получение актуальной анкеты и счетов…");
  refreshEditControls();
  try {
    const payload = await fetchAbsJson(
      elements.body.dataset.absCustomerUrl,
      {customer_id: customerId},
    );
    if (sequence !== state.editAbsSearchSequence) return;
    const required = [
      payload.client_full_name,
      payload.client_phone,
      payload.id_card_number,
      payload.id_card_issuer,
      payload.id_card_issue_date,
    ];
    if (required.some((value) => !value)) {
      throw new Error("АБС вернула неполную анкету. Текущие данные не изменены.");
    }
    elements.editClientFullName.value = payload.client_full_name;
    elements.editClientPhone.value = payload.client_phone;
    elements.editClientWhatsappPhone.value = payload.client_whatsapp_phone || "";
    elements.editIdCardNumber.value = payload.id_card_number;
    elements.editIdCardIssuer.value = payload.id_card_issuer;
    setDateInputIso(elements.editIdCardIssueDate, payload.id_card_issue_date);
    state.editAbsCustomerId = payload.abs_customer_id;
    elements.editAbsSearch.value = payload.abs_customer_id;
    elements.editAbsSearch.disabled = true;
    elements.editAbsSearchButton.textContent = "Обновить по ID";
    elements.editAbsImportHint.textContent = "ID клиента будет сохранён с договором";
    elements.editAbsResults.replaceChildren();
    const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
    renderAbsAccounts(elements.editAbsAccounts, accounts, elements.editAccountNumber);
    setEditAbsStatus(
      accounts.length
        ? "Анкета обновлена в форме. Выберите нужный счёт и сохраните изменения."
        : "Анкета обновлена в форме. Счета не найдены; текущий номер счёта сохранён.",
    );
  } catch (error) {
    if (sequence === state.editAbsSearchSequence) {
      setEditAbsStatus(errorMessage(error, "Не удалось получить данные из АБС."), true);
    }
  } finally {
    if (sequence === state.editAbsSearchSequence) {
      state.editAbsImporting = false;
      refreshEditControls();
    }
  }
}

function resetEditStatementImport() {
  state.editStatementImportSequence += 1;
  state.editStatementImporting = false;
  elements.editStatementFile.value = "";
  elements.editStatementFileState.textContent = "Файл не выбран";
  setEditStatementImportStatus();
  refreshEditControls();
}

async function importEditStatementData() {
  const cell = state.activeOccupiedCell;
  const file = elements.editStatementFile.files[0];
  if (!cell?.legacy_imported || !elements.editDialog.open) return;
  const validationError = statementFileValidationError(file);
  if (validationError) {
    setEditStatementImportStatus(validationError, true);
    return;
  }
  const contractRef = cell.contract_ref;
  const sequence = state.editStatementImportSequence + 1;
  state.editStatementImportSequence = sequence;
  state.editStatementImporting = true;
  setEditStatementImportStatus("Чтение заявления…");
  refreshEditControls();
  try {
    const payload = await extractStatementFile(file);
    if (
      sequence !== state.editStatementImportSequence
      || state.activeOccupiedCell?.contract_ref !== contractRef
      || !elements.editDialog.open
    ) return;
    elements.editClientFullName.value = payload.client_full_name;
    elements.editClientPhone.value = payload.client_phone;
    elements.editAccountNumber.value = payload.account_number;
    elements.editIdCardNumber.value = payload.id_card_number;
    elements.editIdCardIssuer.value = payload.id_card_issuer;
    setDateInputIso(elements.editIdCardIssueDate, payload.id_card_issue_date);
    elements.editStatementFile.value = "";
    elements.editStatementFileState.textContent = "Файл не выбран";
    setEditStatementImportStatus("Данные перенесены в форму. Сверьте их и укажите залог перед сохранением.");
  } catch (error) {
    if (sequence === state.editStatementImportSequence) {
      setEditStatementImportStatus(errorMessage(error, "Не удалось прочитать заявление."), true);
    }
  } finally {
    if (sequence === state.editStatementImportSequence) {
      state.editStatementImporting = false;
      refreshEditControls();
    }
  }
}

function closeEditDialog() {
  if (elements.editDialog.open) elements.editDialog.close();
  resetEditStatementImport();
  elements.editForm.reset();
  elements.editError.hidden = true;
  elements.editError.textContent = "";
  elements.editLegacyNote.hidden = true;
  elements.editStatementImportSection.hidden = true;
  elements.editDepositField.hidden = true;
  elements.editDepositAmount.required = false;
  elements.editDepositAmount.value = "";
  state.editOperationId = null;
  state.editAbsCustomerId = null;
  elements.editAbsResults.replaceChildren();
  elements.editAbsAccounts.replaceChildren();
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
    elements.editClientPhone.value = payload.client_phone || "";
    elements.editClientWhatsappPhone.value = payload.client_whatsapp_phone || "";
    elements.editAccountNumber.value = payload.account_number;
    elements.editIdCardNumber.value = payload.id_card_number;
    elements.editIdCardIssuer.value = payload.id_card_issuer;
    setDateInputIso(elements.editIdCardIssueDate, payload.id_card_issue_date);
    elements.editLegacyNote.hidden = !payload.legacy_imported;
    resetEditStatementImport();
    elements.editStatementImportSection.hidden = !payload.legacy_imported;
    elements.editDepositField.hidden = !payload.legacy_imported;
    elements.editDepositAmount.required = Boolean(payload.legacy_imported);
    elements.editDepositAmount.value = payload.deposit_amount === null ? "" : String(payload.deposit_amount);
    prepareEditAbsImport(payload.abs_customer_id);
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
  if (!cell || !state.editOperationId || state.editSubmitting || state.editStatementImporting || state.editAbsImporting) return;
  if (!elements.editForm.reportValidity()) return;
  state.editSubmitting = true; refreshEditControls(); elements.editError.hidden = true;
  try {
    const editPayload = {operation_id: state.editOperationId, contract_ref: cell.contract_ref,
      cell_number: cell.number, client_full_name: elements.editClientFullName.value,
      client_phone: elements.editClientPhone.value,
      client_whatsapp_phone: elements.editClientWhatsappPhone.value,
      account_number: elements.editAccountNumber.value, id_card_number: elements.editIdCardNumber.value,
      id_card_issuer: elements.editIdCardIssuer.value, id_card_issue_date: dateInputIso(elements.editIdCardIssueDate),
      abs_customer_id: state.editAbsCustomerId};
    if (cell.legacy_imported) editPayload.deposit_amount = Number(elements.editDepositAmount.value);
    const response = await fetch(elements.body.dataset.editUrl, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(editPayload),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.message || "Не удалось сохранить изменения");
    closeEditDialog(); hidePrivateDetails(); await refreshCells();
    showSuccess(payload.warning || "Данные договора изменены.");
  } catch (error) {
    elements.editError.textContent = errorMessage(error, "Не удалось сохранить изменения");
    elements.editError.hidden = false;
  } finally { state.editSubmitting = false; refreshEditControls(); }
}

function closeCellDialog() {
  closeEditDialog();
  state.clientNameRequestSequence += 1;
  hidePrivateDetails();
  state.activeOccupiedCell = null;
  state.blockOperationId = null;
  elements.occupiedUndoAction.hidden = true;
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
  let documentEmployeeId;
  try {
    documentEmployeeId = await chooseDocumentExecutor();
  } catch (error) {
    showClosureError(errorMessage(error, "Не удалось выбрать исполнителя"));
    return;
  }
  if (state.selectedKind === "admin" && !documentEmployeeId) return;
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
        document_employee_id: documentEmployeeId,
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
  elements.renewalCellSummary.textContent = `${cell.height_mm}×${cell.width_mm}×${cell.depth_mm} мм · договор действует до ${formatDate(cell.end_date)}`;
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
  let documentEmployeeId;
  try {
    documentEmployeeId = await chooseDocumentExecutor();
  } catch (error) {
    showRenewalError(errorMessage(error, "Не удалось выбрать исполнителя"));
    return;
  }
  if (state.selectedKind === "admin" && !documentEmployeeId) return;
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
        document_employee_id: documentEmployeeId,
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
  elements.rentalCellSummary.textContent = `${cell.height_mm}×${cell.width_mm}×${cell.depth_mm} мм`;
  setQuietUndoButton(elements.rentalUndoAction, cell.cancellable_action);
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
  elements.rentalUndoAction.hidden = true;
  if (elements.rentalDialog.open) elements.rentalDialog.close();
}

function openManualOccupationDialog() {
  const cell = state.activeRentalCell;
  if (!cell || !state.manualOperationId || state.blockSubmitting) return;
  elements.rentalDialog.close();
  elements.manualOccupationTitle.textContent = `Занять ячейку № ${cell.number}`;
  elements.manualOccupationCellSummary.textContent = `${cell.height_mm}×${cell.width_mm}×${cell.depth_mm} мм · без договора и срока`;
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
  const busy = state.contractSubmitting || state.statementImporting || state.absImporting;
  elements.contractSubmit.disabled = busy;
  elements.contractBack.disabled = busy;
  elements.contractDialogClose.disabled = busy;
  elements.statementFile.disabled = busy;
  elements.absCustomerSearch.disabled = busy;
  elements.absCustomerSearchButton.disabled = busy;
}

function setAbsImportStatus(message = "", isError = false) {
  elements.absCustomerSearchStatus.textContent = message;
  elements.absCustomerSearchStatus.hidden = !message;
  elements.absCustomerSearchStatus.classList.toggle("is-error", isError);
}

function resetAbsCustomerImport() {
  state.absSearchSequence += 1;
  state.absImporting = false;
  elements.absCustomerSearch.value = "";
  elements.absCustomerResults.replaceChildren();
  elements.absAccountResults.replaceChildren();
  state.absSelectedCustomerId = null;
  setAbsImportStatus();
  refreshContractControls();
}

function showAbsLoginIfRequired(payload) {
  if (payload?.login_required) {
    state.absAuthenticated = false;
    openAbsLoginDialog();
  }
}

async function fetchAbsJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Safe-Cells-Token": elements.body.dataset.privateToken,
    },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok) {
    showAbsLoginIfRequired(payload);
    throw new Error(payload.message || "АБС не вернула данные.");
  }
  return payload;
}

function renderAbsCustomerResults(results) {
  const fragment = document.createDocumentFragment();
  for (const result of results) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "abs-customer-result";
    button.setAttribute("role", "listitem");
    button.textContent = `ID ${result.customer_id} — ${result.summary}`;
    button.addEventListener("click", () => importAbsCustomer(result.customer_id));
    fragment.append(button);
  }
  elements.absCustomerResults.replaceChildren(fragment);
}

async function searchAbsCustomers() {
  const query = elements.absCustomerSearch.value.trim();
  if (!query) {
    setAbsImportStatus("Введите ID клиента или ФИО.", true);
    elements.absCustomerSearch.focus();
    return;
  }
  const sequence = state.absSearchSequence + 1;
  state.absSearchSequence = sequence;
  state.absImporting = true;
  elements.absCustomerResults.replaceChildren();
  setAbsImportStatus("Поиск клиента в АБС…");
  refreshContractControls();
  try {
    const payload = await fetchAbsJson(
      elements.body.dataset.absSearchUrl,
      {query},
    );
    if (sequence !== state.absSearchSequence) return;
    const results = Array.isArray(payload.results) ? payload.results : [];
    renderAbsCustomerResults(results);
    setAbsImportStatus(
      results.length
        ? `Найдено: ${results.length}. Выберите нужного клиента.`
        : "Клиенты по этому запросу не найдены.",
      results.length === 0,
    );
  } catch (error) {
    if (sequence === state.absSearchSequence) {
      setAbsImportStatus(errorMessage(error, "Не удалось выполнить поиск в АБС."), true);
    }
  } finally {
    if (sequence === state.absSearchSequence) {
      state.absImporting = false;
      refreshContractControls();
    }
  }
}

async function importAbsCustomer(customerId) {
  const sequence = state.absSearchSequence + 1;
  state.absSearchSequence = sequence;
  state.absImporting = true;
  setAbsImportStatus("Получение анкеты клиента…");
  refreshContractControls();
  try {
    const payload = await fetchAbsJson(
      elements.body.dataset.absCustomerUrl,
      {customer_id: customerId},
    );
    if (sequence !== state.absSearchSequence) return;
    elements.clientFullName.value = payload.client_full_name || "";
    elements.clientPhone.value = payload.client_phone || "";
    elements.clientWhatsappPhone.value = payload.client_whatsapp_phone || "";
    elements.accountNumber.value = payload.account_number || "";
    elements.idCardNumber.value = payload.id_card_number || "";
    elements.idCardIssuer.value = payload.id_card_issuer || "";
    setDateInputIso(elements.idCardIssueDate, payload.id_card_issue_date || "");
    state.absSelectedCustomerId = payload.abs_customer_id;
    elements.absCustomerResults.replaceChildren();
    const accounts = Array.isArray(payload.accounts) ? payload.accounts : [];
    renderAbsAccounts(elements.absAccountResults, accounts, elements.accountNumber);
    const missing = [];
    if (!payload.client_full_name) missing.push("ФИО");
    if (!payload.client_phone) missing.push("телефон");
    if (!payload.account_number && !accounts.length) missing.push("номер счёта");
    if (!payload.id_card_number) missing.push("ID-карта");
    if (!payload.id_card_issuer) missing.push("орган выдачи");
    if (!payload.id_card_issue_date) missing.push("дата выдачи");
    setAbsImportStatus(
      missing.length
        ? `Данные подставлены. Заполните вручную: ${missing.join(", ")}. Затем всё сверьте.`
        : "Данные подставлены. Обязательно сверьте их перед сохранением.",
      false,
    );
  } catch (error) {
    if (sequence === state.absSearchSequence) {
      setAbsImportStatus(errorMessage(error, "Не удалось получить анкету клиента."), true);
    }
  } finally {
    if (sequence === state.absSearchSequence) {
      state.absImporting = false;
      refreshContractControls();
    }
  }
}

function setStatementImportStatus(message = "", isError = false) {
  elements.statementImportStatus.textContent = message;
  elements.statementImportStatus.hidden = !message;
  elements.statementImportStatus.classList.toggle("is-error", isError);
}

function statementFileValidationError(file) {
  if (!file) return "Выберите заявление в формате DOCX.";
  if (!file.name.toLocaleLowerCase("ru").endsWith(".docx")) return "Заявление должно быть файлом DOCX.";
  if (file.size > 2 * 1024 * 1024) return "Размер заявления не должен превышать 2 МБ.";
  return "";
}

async function extractStatementFile(file) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(elements.body.dataset.statementImportUrl, {
    method: "POST",
    headers: {"X-Safe-Cells-Token": elements.body.dataset.privateToken},
    body: formData,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message || "Не удалось прочитать заявление.");
  return payload;
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
  const validationError = statementFileValidationError(file);
  if (validationError) {
    setStatementImportStatus(validationError, true);
    return;
  }

  const sequence = state.statementImportSequence + 1;
  state.statementImportSequence = sequence;
  state.statementImporting = true;
  setStatementImportStatus("Чтение заявления…");
  refreshContractControls();
  try {
    const payload = await extractStatementFile(file);
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
  resetAbsCustomerImport();
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
  if (state.statementImporting || state.absImporting) {
    return;
  }
  elements.contractDialog.close();
  clearContractError();
  resetStatementImport();
  resetAbsCustomerImport();
  elements.rentalDialog.showModal();
}

function cancelContractWorkflow() {
  if (state.contractSubmitting || state.statementImporting || state.absImporting) {
    return;
  }
  elements.contractDialog.close();
  elements.contractForm.reset();
  resetStatementImport();
  resetAbsCustomerImport();
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
  let documentEmployeeId;
  try {
    documentEmployeeId = await chooseDocumentExecutor();
  } catch (error) {
    showContractError(errorMessage(error, "Не удалось выбрать исполнителя"));
    return;
  }
  if (state.selectedKind === "admin" && !documentEmployeeId) return;

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
        client_phone: elements.clientPhone.value,
        client_whatsapp_phone: elements.clientWhatsappPhone.value,
        id_card_number: elements.idCardNumber.value,
        id_card_issuer: elements.idCardIssuer.value,
        id_card_issue_date: dateInputIso(elements.idCardIssueDate),
        account_number: elements.accountNumber.value,
        abs_customer_id: state.absSelectedCustomerId,
        start_date: quote.start_date,
        end_date: quote.end_date,
        rent_days: quote.rent_days,
        document_employee_id: documentEmployeeId,
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
    resetAbsCustomerImport();
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
    cell.block_kind === "lost_key"
      ? " lost-key-label"
      : (cell.block_kind === "manual" ? " manual-block-label" : "")
  }`;
  client.textContent = cell.client_display_name || "";

  button.append(number, client, height);
  button.addEventListener("click", () => openCellDialog(cell));
  return button;
}

function reminderButtonText(cell) {
  return cell.reminder_count > 0 ? "Напомнить повторно" : "Напомнить";
}

function showReminderError(message) {
  if (
    elements.dialog.open
    && state.activeOccupiedCell
    && (state.activeOccupiedCell.status === "expiring"
      || state.activeOccupiedCell.status === "overdue")
  ) {
    elements.privateError.textContent = message;
    elements.privateError.hidden = false;
    return;
  }
  elements.errorMessage.textContent = message;
  elements.errorBanner.hidden = false;
}

async function chooseReminderPhone(cell) {
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
    throw new Error(payload.message || "Не удалось получить номера клиента");
  }
  const choices = [];
  if (payload.client_whatsapp_phone) {
    choices.push({kind: "whatsapp", label: "Номер WhatsApp", value: payload.client_whatsapp_phone});
  }
  if (payload.client_phone) {
    choices.push({kind: "mobile", label: "Мобильный номер", value: payload.client_phone});
  }
  const unique = choices.filter((choice, index) => {
    const digits = choice.value.replace(/\D/g, "");
    return choices.findIndex((item) => item.value.replace(/\D/g, "") === digits) === index;
  });
  if (!unique.length) throw new Error("У клиента не указан номер для WhatsApp.");
  elements.reminderPhoneOptions.replaceChildren();
  elements.reminderPhoneError.hidden = true;
  return new Promise((resolve) => {
    state.reminderPhoneResolver = resolve;
    for (const choice of unique) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "reminder-phone-option";
      const icon = document.createElement("span");
      icon.className = "reminder-phone-option__icon";
      icon.textContent = "W";
      const text = document.createElement("span");
      text.className = "reminder-phone-option__text";
      const label = document.createElement("small");
      label.textContent = choice.label;
      const number = document.createElement("strong");
      number.textContent = choice.value;
      text.append(label, number);
      const action = document.createElement("span");
      action.className = "reminder-phone-option__action";
      action.textContent = "Открыть →";
      button.append(icon, text, action);
      button.addEventListener("click", () => {
        const whatsappWindow = window.open("about:blank", "_blank");
        if (!whatsappWindow) {
          elements.reminderPhoneError.textContent =
            "Браузер заблокировал новую вкладку. Разрешите всплывающие окна и повторите.";
          elements.reminderPhoneError.hidden = false;
          return;
        }
        finishReminderPhoneSelection({kind: choice.kind, whatsappWindow});
      });
      elements.reminderPhoneOptions.append(button);
    }
    elements.reminderPhoneDialog.showModal();
    elements.reminderPhoneOptions.querySelector("button")?.focus();
  });
}

function finishReminderPhoneSelection(selection = null) {
  const resolver = state.reminderPhoneResolver;
  state.reminderPhoneResolver = null;
  if (elements.reminderPhoneDialog.open) elements.reminderPhoneDialog.close();
  elements.reminderPhoneOptions.replaceChildren();
  elements.reminderPhoneError.hidden = true;
  elements.reminderPhoneError.textContent = "";
  resolver?.(selection);
}

async function sendWhatsAppReminder(cell) {
  if (
    !cell?.contract_ref
    || state.reminderSubmittingContracts.has(cell.contract_ref)
    || state.reminderPhoneSelecting
  ) {
    return;
  }
  state.reminderPhoneSelecting = true;
  let selection;
  try {
    selection = await chooseReminderPhone(cell);
  } catch (error) {
    showReminderError(errorMessage(error, "Не удалось выбрать номер клиента"));
    return;
  } finally {
    state.reminderPhoneSelecting = false;
  }
  if (!selection) return;
  const {kind: phoneKind, whatsappWindow} = selection;
  const operationId = state.reminderOperationIds.get(cell.contract_ref)
    || createOperationId();
  state.reminderOperationIds.set(cell.contract_ref, operationId);
  state.reminderSubmittingContracts.add(cell.contract_ref);
  renderGrid();
  if (state.activeOccupiedCell?.contract_ref === cell.contract_ref) {
    renderOccupiedOperationalDetails(state.activeOccupiedCell);
  }
  try {
    const response = await fetch(elements.body.dataset.reminderUrl, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        operation_id: operationId,
        cell_number: cell.number,
        contract_ref: cell.contract_ref,
        phone_kind: phoneKind,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.message || "Не удалось сохранить оповещение");
    }
    state.reminderOperationIds.delete(cell.contract_ref);
    whatsappWindow.location.replace(payload.whatsapp_url);
    await refreshCells();
    showSuccess(
      payload.warning
        ? `${payload.reminder_status}. ${payload.warning}`
        : payload.reminder_status,
    );
  } catch (error) {
    whatsappWindow.close();
    showReminderError(errorMessage(error, "Не удалось подготовить напоминание"));
  } finally {
    state.reminderSubmittingContracts.delete(cell.contract_ref);
    renderGrid();
    if (state.activeOccupiedCell?.contract_ref === cell.contract_ref) {
      renderOccupiedOperationalDetails(state.activeOccupiedCell);
    }
  }
}

function createCellItem(cell) {
  const cellButton = createCellButton(cell);
  const reminderSection = elements.status.value;
  if (
    !["expiring", "overdue"].includes(reminderSection)
    || cell.status !== reminderSection
    || cell.block_kind
  ) {
    return cellButton;
  }
  const item = document.createElement("div");
  item.className = `cell-reminder-item ${cell.status}`;
  const status = document.createElement("span");
  status.className = "cell-reminder-status";
  status.textContent = cell.reminder_status || "Не оповещён";
  const action = document.createElement("button");
  action.type = "button";
  action.className = "cell-reminder-button";
  action.textContent = reminderButtonText(cell);
  action.disabled = state.reminderSubmittingContracts.has(cell.contract_ref);
  action.addEventListener("click", () => sendWhatsAppReminder(cell));
  item.append(cellButton, status, action);
  return item;
}

function renderGrid() {
  const cells = filteredCells();
  const fragment = document.createDocumentFragment();
  for (const cell of cells) {
    fragment.appendChild(createCellItem(cell));
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
    applyUiPreferences(payload.ui_preferences);
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
  if (elements.employeeSelect.value === "__admin__") {
    if (!elements.employeeDialog.open) elements.employeeDialog.showModal();
    openAdminStartupLogin();
  } else if (elements.employeeSelect.value) {
    selectEmployee(elements.employeeSelect.value);
  }
  else if (!elements.employeeDialog.open) elements.employeeDialog.showModal();
});
elements.employeeAdminBack.addEventListener("click", closeAdminStartupLogin);
elements.employeeAdminSubmit.addEventListener("click", selectAdmin);
elements.employeeAdminPassword.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    selectAdmin();
  }
});
elements.employeeAdminPasswordConfirm.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    selectAdmin();
  }
});
elements.absLoginForm.addEventListener("submit", loginToAbs);
elements.absLoginLater.addEventListener("click", closeAbsLoginDialog);
elements.absRefreshClients.addEventListener("click", refreshAbsClients);
elements.absLoginDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeAbsLoginDialog();
});
elements.reminderPhoneCancel.addEventListener(
  "click", () => finishReminderPhoneSelection(null),
);
elements.reminderPhoneDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  finishReminderPhoneSelection(null);
});
elements.executorCancel.addEventListener("click", cancelExecutorSelection);
elements.executorDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  cancelExecutorSelection();
});
elements.employeeOpenSettings.addEventListener("click", () => {
  elements.employeeDialog.close();
  document.getElementById("adminOpen")?.click();
});
elements.operationResultClose.addEventListener("click", closeOperationResult);
elements.operationUndoOpen.addEventListener("click", openOperationUndo);
elements.operationUndoBack.addEventListener("click", closeOperationUndo);
elements.operationUndoConfirm.addEventListener("click", submitOperationUndo);
document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", () => copyPaymentField(button));
});
elements.operationResultDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeOperationResult();
});
elements.status.addEventListener("change", renderGrid);
elements.height.addEventListener("change", renderGrid);
elements.dialogClose.addEventListener("click", closeCellDialog);
elements.occupiedUndoAction.addEventListener(
  "click",
  () => openCardUndo("occupied"),
);
elements.rentalUndoAction.addEventListener(
  "click",
  () => openCardUndo("rental"),
);
elements.cardUndoBack.addEventListener("click", () => closeCardUndo(true));
elements.cardUndoConfirm.addEventListener("click", submitCardUndo);
elements.cardUndoDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeCardUndo(true);
});
elements.blockReleaseAction.addEventListener("click", releaseBlockedCell);
elements.privateToggle.addEventListener("click", togglePrivateDetails);
elements.historyToggle.addEventListener("click", toggleRenewalHistory);
elements.renewAction.addEventListener("click", openRenewalDialog);
elements.reminderAction.addEventListener("click", () => {
  if (state.activeOccupiedCell) {
    sendWhatsAppReminder(state.activeOccupiedCell);
  }
});
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
elements.editStatementFile.addEventListener("change", () => {
  elements.editStatementFileState.textContent = elements.editStatementFile.files.length
    ? "DOCX выбран"
    : "Файл не выбран";
  setEditStatementImportStatus();
  if (elements.editStatementFile.files.length) importEditStatementData();
});
elements.editAbsSearchButton.addEventListener("click", searchEditAbsCustomers);
elements.editAbsSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchEditAbsCustomers();
  }
});
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
elements.absCustomerSearchButton.addEventListener("click", searchAbsCustomers);
elements.absCustomerSearch.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    searchAbsCustomers();
  }
});
elements.statementFile.addEventListener("change", () => {
  elements.statementFileState.textContent = elements.statementFile.files.length
    ? "DOCX выбран"
    : "Файл не выбран";
  setStatementImportStatus();
  if (elements.statementFile.files.length) importStatementData();
});
elements.contractBack.addEventListener("click", backToRentalCalculator);
elements.contractDialogClose.addEventListener("click", cancelContractWorkflow);
elements.contractDialog.addEventListener("cancel", (event) => event.preventDefault());

window.addEventListener("safe-cells:employees-changed", loadEmployeeDirectory);
window.addEventListener("safe-cells:refresh", refreshCells);
window.addEventListener("safe-cells:abs-login-required", openAbsLoginDialog);
loadEmployeeDirectory();
refreshCells();
window.setInterval(() => {
  refreshCells();
  loadEmployeeDirectory();
}, 15_000);
