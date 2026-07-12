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
  quoteSequence: 0,
  activeOccupiedCell: null,
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
};

const elements = {
  body: document.body,
  grid: document.getElementById("vaultGrid"),
  empty: document.getElementById("emptyState"),
  search: document.getElementById("searchInput"),
  status: document.getElementById("statusFilter"),
  height: document.getElementById("heightFilter"),
  refresh: document.getElementById("refreshButton"),
  errorBanner: document.getElementById("errorBanner"),
  errorMessage: document.getElementById("errorMessage"),
  successBanner: document.getElementById("successBanner"),
  successMessage: document.getElementById("successMessage"),
  connection: document.getElementById("connectionState"),
  updatedAt: document.getElementById("updatedAt"),
  resultCount: document.getElementById("resultCount"),
  statFree: document.getElementById("statFree"),
  statNormal: document.getElementById("statNormal"),
  statExpiring: document.getElementById("statExpiring"),
  statOverdue: document.getElementById("statOverdue"),
  dialog: document.getElementById("cellDialog"),
  dialogClose: document.getElementById("dialogClose"),
  dialogTitle: document.getElementById("dialogTitle"),
  dialogStatus: document.getElementById("dialogStatus"),
  dialogSize: document.getElementById("dialogSize"),
  dialogClient: document.getElementById("dialogClient"),
  dialogStartDate: document.getElementById("dialogStartDate"),
  dialogEndDate: document.getElementById("dialogEndDate"),
  dialogRentDays: document.getElementById("dialogRentDays"),
  dialogDays: document.getElementById("dialogDays"),
  privateToggle: document.getElementById("privateToggle"),
  privateError: document.getElementById("privateError"),
  privateDetails: document.getElementById("privateDetails"),
  privateClientName: document.getElementById("privateClientName"),
  privateIdCardNumber: document.getElementById("privateIdCardNumber"),
  privateIdCardIssuer: document.getElementById("privateIdCardIssuer"),
  privateIdCardExpiryDate: document.getElementById("privateIdCardExpiryDate"),
  privateAccountNumber: document.getElementById("privateAccountNumber"),
  privateCreatedAt: document.getElementById("privateCreatedAt"),
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
  contractDialog: document.getElementById("contractDialog"),
  contractDialogClose: document.getElementById("contractDialogClose"),
  contractDialogTitle: document.getElementById("contractDialogTitle"),
  contractPeriodSummary: document.getElementById("contractPeriodSummary"),
  contractRentSummary: document.getElementById("contractRentSummary"),
  contractDepositSummary: document.getElementById("contractDepositSummary"),
  contractForm: document.getElementById("contractForm"),
  contractError: document.getElementById("contractError"),
  clientFullName: document.getElementById("clientFullName"),
  accountNumber: document.getElementById("accountNumber"),
  idCardNumber: document.getElementById("idCardNumber"),
  idCardIssuer: document.getElementById("idCardIssuer"),
  idCardExpiryDate: document.getElementById("idCardExpiryDate"),
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

function showError(message) {
  elements.errorMessage.textContent = message;
  elements.errorBanner.hidden = false;
  setConnection("offline", "Нет связи с базой");
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

function clearError() {
  elements.errorBanner.hidden = true;
  elements.errorMessage.textContent = "";
  setConnection("online", "Данные доступны");
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
  if (elements.dialog.open) {
    closeCellDialog();
  }
  state.cells = [];
  state.counts = { free: 0, normal: 0, expiring: 0, overdue: 0 };
  state.privateMatches = null;
  state.asOfDate = null;
  elements.statFree.textContent = "—";
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
  elements.dialogStatus.textContent = STATUS_LABELS[cell.status];
  elements.dialogStatus.className = `status-badge ${cell.status}`;
  elements.dialogSize.textContent = `${cell.height_mm}×${cell.width_mm}×${cell.depth_mm}`;
  elements.dialogClient.textContent = cell.client_display_name || "—";
  elements.dialogStartDate.textContent = formatDate(cell.start_date);
  elements.dialogEndDate.textContent = formatDate(cell.end_date);
  elements.dialogRentDays.textContent = `${cell.total_days} дн. (первоначально ${cell.rent_days})`;
  elements.dialogDays.textContent = daysLabel(cell);
}

function openCellDialog(cell) {
  if (cell.status === "free") {
    openRentalCalculator(cell);
    return;
  }
  state.activeOccupiedCell = cell;
  hidePrivateDetails();
  renderOccupiedOperationalDetails(cell);
  elements.dialog.showModal();
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
  elements.privateClientName.textContent = "";
  elements.privateIdCardNumber.textContent = "";
  elements.privateIdCardIssuer.textContent = "";
  elements.privateIdCardExpiryDate.textContent = "";
  elements.privateAccountNumber.textContent = "";
  elements.privateCreatedAt.textContent = "";
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
    details.textContent = `Продлено ${formatDate(renewal.renewal_date)}, сумма ${money(renewal.renewal_price)}${penalty}`;
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
    elements.privateClientName.textContent = payload.client_full_name;
    elements.privateIdCardNumber.textContent = payload.id_card_number;
    elements.privateIdCardIssuer.textContent = payload.id_card_issuer;
    elements.privateIdCardExpiryDate.textContent = formatDate(payload.id_card_expiry_date);
    elements.privateAccountNumber.textContent = payload.account_number;
    elements.privateCreatedAt.textContent = formatDateTime(payload.created_at);
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

function closeCellDialog() {
  hidePrivateDetails();
  state.activeOccupiedCell = null;
  elements.dialog.close();
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
    showSuccess(`Договор по ячейке № ${payload.cell_number} закрыт. Ячейка свободна.${warning}`);
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
  const days = Number(elements.renewalDays.value);
  const endDate = elements.renewalEndDate.value || null;
  const sequence = ++state.renewalQuoteSequence;
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
    elements.renewalEndDate.value = payload.new_end_date;
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

function syncRenewalDaysFromEnd() {
  const startValue = state.activeRenewalQuote?.new_start_date;
  const start = parseIsoDateUtc(startValue || "");
  const end = parseIsoDateUtc(elements.renewalEndDate.value);
  if (!start || !end || end < start) {
    elements.renewalDays.value = "";
    return;
  }
  elements.renewalDays.value = String(Math.round((end - start) / 86_400_000) + 1);
}

function syncRenewalEndFromDays() {
  const startValue = state.activeRenewalQuote?.new_start_date;
  const start = parseIsoDateUtc(startValue || "");
  const days = Number(elements.renewalDays.value);
  if (!start || !Number.isInteger(days) || days < 1) {
    elements.renewalEndDate.value = "";
    return;
  }
  const end = new Date(start.getTime());
  end.setUTCDate(end.getUTCDate() + days - 1);
  elements.renewalEndDate.value = isoFromUtcDate(end);
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
  elements.renewalEndDate.value = "";
  elements.renewalDays.value = "1";
  clearRenewalError();
  resetRenewalQuote();
  setRenewalSubmitting(false);
  elements.renewalDialog.showModal();
  scheduleRenewalQuote();
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
    showSuccess(`Аренда ячейки № ${cellNumber} продлена до ${formatDate(payload.new_end_date)}.${warning}`);
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

function isoFromUtcDate(value) {
  return value.toISOString().slice(0, 10);
}

function syncDaysFromDates() {
  const start = parseIsoDateUtc(elements.rentalStartDate.value);
  const end = parseIsoDateUtc(elements.rentalEndDate.value);
  if (!start || !end || end < start) {
    elements.rentalDays.value = "";
    return false;
  }
  elements.rentalDays.value = String(Math.round((end - start) / 86_400_000) + 1);
  return true;
}

function syncEndFromDays() {
  const start = parseIsoDateUtc(elements.rentalStartDate.value);
  const days = Number(elements.rentalDays.value);
  if (!start || !Number.isInteger(days) || days < 1) {
    elements.rentalEndDate.value = "";
    return false;
  }
  const end = new Date(start.getTime());
  end.setUTCDate(end.getUTCDate() + days - 1);
  elements.rentalEndDate.value = isoFromUtcDate(end);
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
  const startDate = elements.rentalStartDate.value;
  const endDate = elements.rentalEndDate.value;
  const rentDays = Number(elements.rentalDays.value);
  const sequence = ++state.quoteSequence;
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
  clearSuccess();
  elements.rentalDialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.rentalCellSummary.textContent = `Высота ${cell.height_mm} мм · ${cell.width_mm} × ${cell.depth_mm} мм`;
  const startDate = state.asOfDate || isoFromUtcDate(new Date());
  elements.rentalStartDate.max = startDate;
  elements.rentalStartDate.value = startDate;
  elements.rentalDays.value = "1";
  syncEndFromDays();
  resetQuote();
  clearRentalError();
  elements.rentalDialog.showModal();
  scheduleRentalQuote();
}

function closeRentalCalculator() {
  window.clearTimeout(quoteTimer);
  state.quoteSequence += 1;
  state.activeRentalCell = null;
  state.activeQuote = null;
  state.activeOperationId = null;
  elements.rentalDialog.close();
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
  elements.contractSubmit.disabled = submitting;
  elements.contractBack.disabled = submitting;
  elements.contractSubmit.textContent = submitting ? "Сохранение…" : "Подтвердить и занять";
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
  elements.contractDialog.close();
  clearContractError();
  elements.rentalDialog.showModal();
}

function cancelContractWorkflow() {
  if (state.contractSubmitting) {
    return;
  }
  elements.contractDialog.close();
  elements.contractForm.reset();
  clearContractError();
  state.activeRentalCell = null;
  state.activeQuote = null;
  state.activeOperationId = null;
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
        id_card_expiry_date: elements.idCardExpiryDate.value,
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
    state.activeRentalCell = null;
    state.activeQuote = null;
    state.activeOperationId = null;
    await refreshCells();
    showSuccess(`Ячейка № ${savedCellNumber} занята.${warning} Документы будут доступны после подключения шаблонов.`);
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
  button.setAttribute(
    "aria-label",
    `Ячейка ${cell.number}, высота ${cell.height_mm} миллиметров, ${STATUS_LABELS[cell.status]}`,
  );

  const number = document.createElement("span");
  number.className = "cell-number";
  number.textContent = cell.number;

  const height = document.createElement("span");
  height.className = "cell-height";
  height.textContent = String(cell.height_mm);

  const client = document.createElement("span");
  client.className = "cell-client";
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
  elements.refresh.classList.add("loading");
  elements.refresh.disabled = true;
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
      if (
        !updatedCell
        || updatedCell.status === "free"
        || updatedCell.contract_ref !== state.activeOccupiedCell.contract_ref
      ) {
        closeCellDialog();
      } else {
        state.activeOccupiedCell = updatedCell;
        renderOccupiedOperationalDetails(updatedCell);
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
    elements.refresh.classList.remove("loading");
    elements.refresh.disabled = false;
  }
}

elements.search.addEventListener("input", scheduleSearch);
elements.status.addEventListener("change", renderGrid);
elements.height.addEventListener("change", renderGrid);
elements.refresh.addEventListener("click", refreshCells);
elements.dialogClose.addEventListener("click", closeCellDialog);
elements.privateToggle.addEventListener("click", togglePrivateDetails);
elements.historyToggle.addEventListener("click", toggleRenewalHistory);
elements.renewAction.addEventListener("click", openRenewalDialog);
elements.closeAction.addEventListener("click", openClosureDialog);
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) {
    closeCellDialog();
  }
});
elements.dialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeCellDialog();
});
elements.closureReason.addEventListener("change", requestClosureQuote);
elements.closureForm.addEventListener("submit", submitClosure);
elements.closureBack.addEventListener("click", () => closeClosureDialog(true));
elements.closureDialogClose.addEventListener("click", () => closeClosureDialog(true));
elements.closureDialog.addEventListener("click", (event) => {
  if (event.target === elements.closureDialog) {
    closeClosureDialog(true);
  }
});
elements.closureDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeClosureDialog(true);
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
elements.renewalDialog.addEventListener("click", (event) => {
  if (event.target === elements.renewalDialog) {
    closeRenewalDialog(true);
  }
});
elements.renewalDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  closeRenewalDialog(true);
});
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
elements.rentalDialog.addEventListener("click", (event) => {
  if (event.target === elements.rentalDialog) {
    closeRentalCalculator();
  }
});
elements.contractForm.addEventListener("submit", submitContract);
elements.contractBack.addEventListener("click", backToRentalCalculator);
elements.contractDialogClose.addEventListener("click", cancelContractWorkflow);
elements.contractDialog.addEventListener("click", (event) => {
  if (event.target === elements.contractDialog) {
    cancelContractWorkflow();
  }
});
elements.contractDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  cancelContractWorkflow();
});

refreshCells();
window.setInterval(refreshCells, 15_000);
