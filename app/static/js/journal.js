"use strict";

(() => {
  const elements = {
    body: document.body,
    open: document.getElementById("journalOpen"),
    dialog: document.getElementById("journalDialog"),
    close: document.getElementById("journalClose"),
    filters: document.getElementById("journalFilters"),
    cell: document.getElementById("journalCell"),
    action: document.getElementById("journalAction"),
    dateFrom: document.getElementById("journalDateFrom"),
    dateTo: document.getElementById("journalDateTo"),
    reset: document.getElementById("journalReset"),
    report: document.getElementById("journalReport"),
    message: document.getElementById("journalMessage"),
    list: document.getElementById("journalList"),
    empty: document.getElementById("journalEmpty"),
    previous: document.getElementById("journalPrevious"),
    next: document.getElementById("journalNext"),
    page: document.getElementById("journalPage"),
    employee: document.getElementById("employeeSelect"),
    employeeDialog: document.getElementById("employeeDialog"),
  };

  const state = { page: 1, busy: false, pageCount: 1 };

  function setBusy(busy) {
    state.busy = busy;
    elements.list.setAttribute("aria-busy", busy ? "true" : "false");
    elements.filters.querySelectorAll("button, input, select").forEach((control) => {
      control.disabled = busy;
    });
    elements.report.disabled = busy;
    if (busy) {
      elements.message.textContent = "Загрузка журнала…";
    }
  }

  function formatOccurredAt(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
      return "Время не указано";
    }
    return new Intl.DateTimeFormat("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(parsed);
  }

  function formatDateDigits(value) {
    const digits = value.replace(/\D/g, "").slice(0, 8);
    if (digits.length <= 2) return digits;
    if (digits.length <= 4) return `${digits.slice(0, 2)}.${digits.slice(2)}`;
    return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`;
  }

  function dateFilterValue(input) {
    const value = input.value.trim();
    if (!value) return "";
    const match = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(value);
    if (!match) throw new Error("Укажите даты фильтра в формате ДД.ММ.ГГГГ");
    const [, day, month, year] = match;
    const parsed = new Date(`${year}-${month}-${day}T00:00:00Z`);
    if (
      Number.isNaN(parsed.getTime())
      || parsed.getUTCFullYear() !== Number(year)
      || parsed.getUTCMonth() + 1 !== Number(month)
      || parsed.getUTCDate() !== Number(day)
    ) {
      throw new Error("Укажите корректные даты фильтра");
    }
    return `${year}-${month}-${day}`;
  }

  function createEntry(entry) {
    const article = document.createElement("article");
    article.className = "journal-entry";

    const heading = document.createElement("div");
    heading.className = "journal-entry-heading";

    const cell = document.createElement("strong");
    cell.className = "journal-cell-number";
    cell.textContent = `Ячейка № ${entry.cell_number}`;

    const action = document.createElement("span");
    action.className = `journal-action journal-action-${entry.action.split(".").pop()}`;
    action.textContent = entry.action_label;

    const time = document.createElement("time");
    time.dateTime = entry.occurred_at;
    time.textContent = formatOccurredAt(entry.occurred_at);
    heading.append(cell, action, time);

    const summary = document.createElement("p");
    summary.className = "journal-summary";
    summary.textContent = entry.summary;

    const client = document.createElement("p");
    client.className = "journal-client";
    client.textContent = `Клиент: ${entry.client_full_name}`;

    const employee = document.createElement("p");
    employee.className = "journal-employee";
    employee.textContent = `Сотрудник: ${entry.employee}`;

    article.append(heading, client, summary, employee);
    return article;
  }

  function render(payload) {
    const entries = Array.isArray(payload.entries) ? payload.entries : [];
    const pagination = payload.pagination || {};
    const fragment = document.createDocumentFragment();
    entries.forEach((entry) => fragment.append(createEntry(entry)));
    elements.list.replaceChildren(fragment);
    elements.empty.hidden = entries.length > 0;

    state.page = Number(pagination.page) || 1;
    state.pageCount = Number(pagination.page_count) || 1;
    const total = Number(pagination.total) || 0;
    elements.message.textContent = `Найдено операций: ${total}`;
    elements.page.textContent = `Страница ${state.page} из ${state.pageCount}`;
    elements.previous.disabled = !pagination.has_previous;
    elements.next.disabled = !pagination.has_next;
  }

  function queryUrl(baseUrl, includePage) {
    const parameters = new URLSearchParams();
    if (includePage) {
      parameters.set("page", String(state.page));
      parameters.set("page_size", "50");
    }
    const filters = {
      cell_number: elements.cell.value.trim(),
      action: elements.action.value,
      date_from: dateFilterValue(elements.dateFrom),
      date_to: dateFilterValue(elements.dateTo),
    };
    Object.entries(filters).forEach(([key, value]) => {
      if (value) parameters.set(key, value);
    });
    const query = parameters.toString();
    return query ? `${baseUrl}?${query}` : baseUrl;
  }

  async function loadJournal() {
    if (state.busy) return;
    setBusy(true);
    try {
      const response = await fetch(queryUrl(elements.body.dataset.journalUrl, true), { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.selection_required) {
          elements.dialog.close();
          if (!elements.employeeDialog.open) elements.employeeDialog.showModal();
        }
        throw new Error(payload.message || "Не удалось получить журнал");
      }
      render(payload);
    } catch (error) {
      elements.list.replaceChildren();
      elements.empty.hidden = true;
      elements.message.textContent = error instanceof Error
        ? error.message
        : "Не удалось получить журнал";
      elements.previous.disabled = true;
      elements.next.disabled = true;
    } finally {
      setBusy(false);
    }
  }

  async function downloadReport() {
    if (state.busy) return;
    setBusy(true);
    elements.message.textContent = "Формирование отчёта Excel…";
    try {
      const response = await fetch(
        queryUrl(elements.body.dataset.journalReportUrl, false),
        { cache: "no-store" },
      );
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.message || "Не удалось сформировать отчёт");
      }
      const report = await response.blob();
      const downloadUrl = URL.createObjectURL(report);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = "Выписка_по_ячейкам.xlsx";
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(downloadUrl), 1000);
      elements.message.textContent = "Отчёт Excel сформирован по выбранным условиям.";
    } catch (error) {
      elements.message.textContent = error instanceof Error
        ? error.message
        : "Не удалось сформировать отчёт";
    } finally {
      setBusy(false);
    }
  }

  elements.open.addEventListener("click", () => {
    if (!elements.employee.value) {
      if (!elements.employeeDialog.open) elements.employeeDialog.showModal();
      return;
    }
    state.page = 1;
    elements.dialog.showModal();
    loadJournal();
  });

  elements.close.addEventListener("click", () => elements.dialog.close());
  elements.report.addEventListener("click", downloadReport);
  elements.dialog.addEventListener("cancel", (event) => event.preventDefault());
  elements.filters.addEventListener("submit", (event) => {
    event.preventDefault();
    state.page = 1;
    loadJournal();
  });
  elements.reset.addEventListener("click", () => {
    elements.filters.reset();
    state.page = 1;
    loadJournal();
  });
  elements.previous.addEventListener("click", () => {
    if (state.page > 1) {
      state.page -= 1;
      loadJournal();
    }
  });
  elements.next.addEventListener("click", () => {
    if (state.page < state.pageCount) {
      state.page += 1;
      loadJournal();
    }
  });
  elements.dialog.querySelectorAll("[data-journal-date]").forEach((input) => {
    input.addEventListener("input", () => {
      input.value = formatDateDigits(input.value);
    });
    input.addEventListener("paste", (event) => {
      event.preventDefault();
      input.value = formatDateDigits(event.clipboardData.getData("text"));
    });
  });
})();
