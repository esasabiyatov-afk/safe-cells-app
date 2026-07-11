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
  quoteSequence: 0,
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
  dialogEndDate: document.getElementById("dialogEndDate"),
  dialogDays: document.getElementById("dialogDays"),
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
  quoteTotal: document.getElementById("quoteTotal"),
  rentalBack: document.getElementById("rentalBack"),
  rentalContinue: document.getElementById("rentalContinue"),
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

function openCellDialog(cell) {
  if (cell.status === "free") {
    openRentalCalculator(cell);
    return;
  }
  elements.dialogTitle.textContent = `№ ${cell.number}`;
  elements.dialogStatus.textContent = STATUS_LABELS[cell.status];
  elements.dialogStatus.className = `status-badge ${cell.status}`;
  elements.dialogSize.textContent = `${cell.width_mm} × ${cell.depth_mm} × ${cell.height_mm} мм`;
  elements.dialogEndDate.textContent = formatDate(cell.end_date);
  elements.dialogDays.textContent = daysLabel(cell);
  elements.dialog.showModal();
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
  elements.quoteDays.textContent = "—";
  elements.quoteTariff.textContent = "—";
  elements.quoteRentPrice.textContent = "—";
  elements.quoteDeposit.textContent = "—";
  elements.quoteTotal.textContent = "—";
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
    elements.quoteTotal.textContent = money(payload.total_amount);
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
  quoteTimer = window.setTimeout(requestRentalQuote, 180);
}

function openRentalCalculator(cell) {
  state.activeRentalCell = cell;
  state.activeQuote = null;
  elements.rentalDialogTitle.textContent = `Ячейка № ${cell.number}`;
  elements.rentalCellSummary.textContent = `Высота ${cell.height_mm} мм · ${cell.width_mm} × ${cell.depth_mm} мм`;
  const startDate = state.asOfDate || isoFromUtcDate(new Date());
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
  elements.rentalDialog.close();
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
  height.textContent = `${cell.height_mm} мм`;

  button.append(number, height);
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
elements.dialogClose.addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) {
    elements.dialog.close();
  }
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
elements.rentalDialog.addEventListener("click", (event) => {
  if (event.target === elements.rentalDialog) {
    closeRentalCalculator();
  }
});

refreshCells();
window.setInterval(refreshCells, 15_000);
