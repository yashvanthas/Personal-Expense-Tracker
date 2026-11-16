const PAGE_SIZE = 25;
const currencyNumber = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const elements = {
  categoryEmpty: document.querySelector("#category-empty"),
  categoryChart: document.querySelector("#category-chart"),
  categoryList: document.querySelector("#category-list"),
  categoryTotal: document.querySelector("#category-total"),
  budgetAmount: document.querySelector("#budget-amount"),
  budgetCategory: document.querySelector("#budget-category"),
  budgetEmpty: document.querySelector("#budget-empty"),
  budgetForm: document.querySelector("#budget-form"),
  budgetList: document.querySelector("#budget-list"),
  budgetMonth: document.querySelector("#budget-month"),
  chartEmpty: document.querySelector("#chart-empty"),
  chart: document.querySelector("#trend-chart"),
  dashboardSearch: document.querySelector("#dashboard-search"),
  dashboardSearchForm: document.querySelector("#dashboard-search-form"),
  clearFilters: document.querySelector("#clear-filters"),
  discardForm: document.querySelector("#discard-form"),
  emptyAdd: document.querySelector("#empty-add"),
  emptyState: document.querySelector("#empty-state"),
  entryAmount: document.querySelector("#entry-amount"),
  entryCategory: document.querySelector("#entry-category"),
  entryDate: document.querySelector("#entry-date"),
  entryDescription: document.querySelector("#entry-description"),
  entryType: document.querySelector("#entry-type"),
  exportCount: document.querySelector("#export-count"),
  exportDialog: document.querySelector("#export-dialog"),
  exportEmpty: document.querySelector("#export-preview-empty"),
  exportList: document.querySelector("#export-preview-list"),
  exportLoading: document.querySelector("#export-preview-loading"),
  exportNext: document.querySelector("#export-next"),
  exportPrevious: document.querySelector("#export-previous"),
  expenseTotal: document.querySelector("#expense-total"),
  downloadExport: document.querySelector("#download-export"),
  filterEnd: document.querySelector("#filter-end"),
  filterCategory: document.querySelector("#filter-category"),
  filterForm: document.querySelector("#filter-form"),
  filterSearch: document.querySelector("#filter-search"),
  filterStart: document.querySelector("#filter-start"),
  filterType: document.querySelector("#filter-type"),
  form: document.querySelector("#transaction-form"),
  formTitle: document.querySelector("#form-title"),
  importDialog: document.querySelector("#import-dialog"),
  importFile: document.querySelector("#import-file"),
  importPreviewButton: document.querySelector("#preview-import"),
  importConfirmButton: document.querySelector("#confirm-import"),
  importMapping: document.querySelector("#import-mapping"),
  importSummary: document.querySelector("#import-summary"),
  importPreviewWrap: document.querySelector("#import-preview-table-wrap"),
  importPreviewRows: document.querySelector("#import-preview-rows"),
  importPreviewTruncation: document.querySelector("#import-preview-truncation"),
  importIssuesWrap: document.querySelector("#import-issues-wrap"),
  importIssues: document.querySelector("#import-issues"),
  incomeTotal: document.querySelector("#income-total"),
  loading: document.querySelector("#loading-state"),
  netTotal: document.querySelector("#net-total"),
  newTransaction: document.querySelector("#new-transaction"),
  newTransactionSecondary: document.querySelector("#new-transaction-secondary"),
  nextPage: document.querySelector("#next-page"),
  notice: document.querySelector("#notice"),
  periodCount: document.querySelector("#period-count"),
  periodDailyExpenses: document.querySelector("#period-daily-expenses"),
  periodRange: document.querySelector("#period-range"),
  periodTopCategory: document.querySelector("#period-top-category"),
  pageStatus: document.querySelector("#page-status"),
  previousPage: document.querySelector("#previous-page"),
  restoreButton: document.querySelector("#restore-button"),
  restoreFile: document.querySelector("#restore-file"),
  restoreForm: document.querySelector("#restore-form"),
  transactionId: document.querySelector("#transaction-id"),
  transactionList: document.querySelector("#transaction-list"),
};

let offset = 0;
let exportOffset = 0;
let noticeTimeout;
const EXPORT_PREVIEW_SIZE = 50;
const IMPORT_FIELDS = [
  { field: "date", label: "Date", required: true },
  { field: "type", label: "Type", required: false },
  { field: "category", label: "Category", required: true },
  { field: "description", label: "Description", required: false },
  { field: "amount", label: "Amount", required: true },
];

function showNotice(message, isError = false) {
  window.clearTimeout(noticeTimeout);
  elements.notice.textContent = message;
  elements.notice.classList.toggle("error", isError);
  elements.notice.hidden = false;
  noticeTimeout = window.setTimeout(() => {
    elements.notice.hidden = true;
  }, 5000);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body.error) message = body.error;
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function filtersQuery() {
  const params = new URLSearchParams();
  if (elements.filterSearch.value.trim()) params.set("search", elements.filterSearch.value.trim());
  if (elements.filterCategory.value) params.set("category", elements.filterCategory.value);
  if (elements.filterType.value) params.set("type", elements.filterType.value);
  if (elements.filterStart.value) params.set("start_date", elements.filterStart.value);
  if (elements.filterEnd.value) params.set("end_date", elements.filterEnd.value);
  return params;
}

async function refreshCategoryOptions() {
  const selected = elements.filterCategory.value;
  const data = await requestJson("/api/categories");
  elements.filterCategory.replaceChildren(new Option("All categories", ""));
  for (const category of data.categories) {
    elements.filterCategory.add(new Option(category, category));
  }
  elements.filterCategory.value = data.categories.includes(selected) ? selected : "";
}

function dateLabel(value) {
  const [year, month, day] = value.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(new Date(year, month - 1, day));
}

function todayIsoDate() {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function createCell(className = "") {
  const cell = document.createElement("td");
  if (className) cell.className = className;
  return cell;
}

function renderTransactions(transactions) {
  elements.transactionList.replaceChildren();
  elements.emptyState.hidden = transactions.length > 0;

  for (const transaction of transactions) {
    const row = document.createElement("tr");
    const nameCell = createCell();
    const mark = document.createElement("span");
    mark.className = `type-mark ${transaction.type}`;
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = transaction.type === "income" ? "↓" : "↑";
    const name = document.createElement("span");
    name.className = "transaction-name";
    name.textContent = transaction.type === "income" ? "Income" : "Expense";
    nameCell.append(mark, name);
    if (transaction.description) {
      const description = document.createElement("span");
      description.className = "transaction-description";
      description.textContent = transaction.description;
      nameCell.append(description);
    }

    const categoryCell = createCell();
    const category = document.createElement("span");
    category.className = "category-pill";
    category.textContent = transaction.category;
    categoryCell.append(category);

    const dateCell = createCell();
    dateCell.textContent = dateLabel(transaction.date);

    const amountCell = createCell(`amount-cell ${transaction.type}`);
    const sign = transaction.type === "income" ? "+" : "−";
    amountCell.textContent = `${sign}${currencyNumber.format(transaction.amount)}`;

    const actionsCell = createCell();
    const actions = document.createElement("div");
    actions.className = "row-actions";
    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "row-action";
    editButton.textContent = "Edit";
    editButton.setAttribute("aria-label", `Edit ${transaction.type} transaction`);
    editButton.addEventListener("click", () => openEditForm(transaction));
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "row-action delete";
    deleteButton.textContent = "Delete";
    deleteButton.setAttribute("aria-label", `Delete ${transaction.type} transaction`);
    deleteButton.addEventListener("click", () => deleteTransaction(transaction.id));
    actions.append(editButton, deleteButton);
    actionsCell.append(actions);
    row.append(nameCell, categoryCell, dateCell, amountCell, actionsCell);
    elements.transactionList.append(row);
  }

  const first = transactions.length ? offset + 1 : 0;
  const last = offset + transactions.length;
  elements.pageStatus.textContent = transactions.length
    ? `Showing ${first}–${last} transactions`
    : "Showing 0 transactions";
  elements.previousPage.disabled = offset === 0;
  elements.nextPage.disabled = transactions.length < PAGE_SIZE;
}

function dateRangeQuery() {
  const params = new URLSearchParams();
  if (elements.filterStart.value) params.set("start_date", elements.filterStart.value);
  if (elements.filterEnd.value) params.set("end_date", elements.filterEnd.value);
  return params;
}

function renderPeriodSummary(summary) {
  elements.incomeTotal.textContent = currencyNumber.format(summary.income);
  elements.expenseTotal.textContent = currencyNumber.format(summary.expenses);
  elements.netTotal.textContent = currencyNumber.format(summary.net);
  elements.periodCount.textContent = String(summary.transaction_count);
  elements.periodDailyExpenses.textContent = currencyNumber.format(
    summary.average_daily_expenses,
  );
  elements.periodTopCategory.textContent = summary.top_expense_category
    ? `${summary.top_expense_category.category} · ${currencyNumber.format(summary.top_expense_category.amount)}`
    : "—";

  elements.periodRange.textContent =
    summary.start_date && summary.end_date
      ? `${dateLabel(summary.start_date)} – ${dateLabel(summary.end_date)} (${summary.days} days)`
      : "No transactions in this period";
}

function renderTrends(monthlyRows) {
  elements.chartEmpty.hidden = monthlyRows.length > 0;
  if (!monthlyRows.length) {
    elements.chart.replaceChildren();
    elements.chartEmpty.textContent = "Monthly trends will appear when you add transactions.";
    return;
  }
  if (!window.Plotly) {
    elements.chart.replaceChildren();
    elements.chartEmpty.textContent = "The chart is unavailable. Refresh the page to try again.";
    elements.chartEmpty.hidden = false;
    return;
  }
  const monthDates = monthlyRows.map((row) => `${row.month}-01`);
  const monthLabels = monthlyRows.map((row) => {
    const [year, month] = row.month.split("-").map(Number);
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      year: "2-digit",
    }).format(new Date(year, month - 1, 1));
  });
  window.Plotly.react(
    elements.chart,
    [
      {
        x: monthDates,
        y: monthlyRows.map((row) => row.income),
        type: "scatter",
        mode: "lines+markers",
        name: "Income",
        line: { color: "#138b65", width: 3, shape: "spline" },
        marker: { size: 7, color: "#138b65" },
        hovertemplate: "%{y:,.2f}<extra></extra>",
      },
      {
        x: monthDates,
        y: monthlyRows.map((row) => row.expenses),
        type: "scatter",
        mode: "lines+markers",
        name: "Expenses",
        line: { color: "#d05764", width: 3, shape: "spline" },
        marker: { size: 7, color: "#d05764" },
        hovertemplate: "%{y:,.2f}<extra></extra>",
      },
    ],
    {
      autosize: true,
      margin: { l: 52, r: 14, t: 18, b: 42 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "DM Sans, Segoe UI, sans-serif", size: 11, color: "#687187" },
      legend: { orientation: "h", y: 1.14, x: 0, font: { size: 11 } },
      xaxis: {
        type: "date",
        tickmode: "array",
        tickvals: monthDates,
        ticktext: monthLabels,
        gridcolor: "rgba(235, 237, 244, 0.65)",
        linecolor: "#e8eaf1",
        tickfont: { size: 10 },
        automargin: true,
        fixedrange: true,
      },
      yaxis: {
        gridcolor: "#eceef4",
        zerolinecolor: "#e0e3ec",
        rangemode: "tozero",
        tickformat: ",.0f",
        tickfont: { size: 10 },
        automargin: true,
        fixedrange: true,
      },
      hovermode: "x unified",
      hoverlabel: { bgcolor: "#20243a", font: { color: "#fff" }, bordercolor: "#20243a" },
    },
    { responsive: true, displayModeBar: false },
  );
}

function renderCategories(categories) {
  elements.categoryList.replaceChildren();
  elements.categoryEmpty.hidden = categories.length > 0;
  if (!categories.length) {
    elements.categoryChart.style.background = "#efeff5";
    elements.categoryChart.setAttribute("aria-label", "No expenses in this period");
    elements.categoryTotal.textContent = currencyNumber.format(0);
    return;
  }

  const colors = ["#6d55e8", "#a99be9", "#17142b", "#d0c8f7", "#7b72b5", "#c5bddf"];
  const total = categories.reduce((sum, item) => sum + item.amount, 0);
  let accumulated = 0;
  const segments = categories.map((item, index) => {
    const start = accumulated;
    accumulated += (item.amount / total) * 100;
    return `${colors[index % colors.length]} ${start}% ${accumulated}%`;
  });
  elements.categoryChart.style.background = `conic-gradient(${segments.join(", ")})`;
  elements.categoryTotal.textContent = currencyNumber.format(total);
  elements.categoryChart.setAttribute(
    "aria-label",
    `Expenses by category. Total ${currencyNumber.format(total)}. ${categories
      .map((item) => `${item.category}: ${currencyNumber.format(item.amount)}`)
      .join("; ")}`,
  );
  categories.forEach((item, index) => {
    const line = document.createElement("div");
    line.className = "category-line";
    const marker = document.createElement("span");
    marker.className = "category-marker";
    marker.style.backgroundColor = colors[index % colors.length];
    marker.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "category-label";
    label.textContent = item.category;
    const value = document.createElement("strong");
    value.textContent = currencyNumber.format(item.amount);
    line.append(marker, label, value);
    elements.categoryList.append(line);
  });
}

function currentMonthIso() {
  return todayIsoDate().slice(0, 7);
}

function renderBudgets(budgets) {
  elements.budgetList.replaceChildren();
  elements.budgetEmpty.hidden = budgets.length > 0;
  for (const budget of budgets) {
    const card = document.createElement("article");
    card.className = `budget-card ${budget.status}`;
    const top = document.createElement("div");
    top.className = "budget-card-top";
    const name = document.createElement("div");
    name.className = "budget-category";
    name.textContent = budget.category;
    const values = document.createElement("div");
    values.className = "budget-values";
    const spent = document.createElement("strong");
    spent.textContent = currencyNumber.format(budget.spent);
    const limit = document.createElement("span");
    limit.textContent = `of ${currencyNumber.format(budget.amount)}`;
    values.append(spent, limit);
    top.append(name, values);

    const track = document.createElement("div");
    track.className = "budget-track";
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", `${budget.category} budget used`);
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.min(100, Math.round(budget.percentage))));
    const fill = document.createElement("div");
    fill.className = "budget-fill";
    fill.style.width = `${Math.min(100, budget.percentage)}%`;
    track.append(fill);

    const bottom = document.createElement("div");
    bottom.className = "budget-card-bottom";
    const status = document.createElement("span");
    if (budget.status === "over") {
      status.className = "budget-alert";
      status.textContent = `Over budget by ${currencyNumber.format(Math.abs(budget.remaining))}`;
    } else if (budget.status === "warning") {
      status.className = "budget-warning";
      status.textContent = `${currencyNumber.format(budget.remaining)} remaining · ${Math.round(budget.percentage)}% used`;
    } else {
      status.className = "budget-on-track";
      status.textContent = `${currencyNumber.format(budget.remaining)} remaining · ${Math.round(budget.percentage)}% used`;
    }
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "row-action delete";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${budget.category} budget`);
    remove.addEventListener("click", () => deleteBudget(budget.id, budget.category));
    bottom.append(status, remove);
    card.append(top, track, bottom);
    elements.budgetList.append(card);
  }
}

async function refreshBudgets() {
  try {
    const params = new URLSearchParams({ month: elements.budgetMonth.value });
    const data = await requestJson(`/api/budgets?${params}`);
    renderBudgets(data.budgets);
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function saveBudget(event) {
  event.preventDefault();
  const payload = {
    month: elements.budgetMonth.value,
    category: elements.budgetCategory.value.trim(),
    amount: Number(elements.budgetAmount.value),
  };
  try {
    await requestJson("/api/budgets", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    elements.budgetForm.reset();
    showNotice(`Budget saved for ${payload.category}.`);
    await refreshBudgets();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function deleteBudget(id, category) {
  if (!window.confirm(`Remove the ${category} budget for ${elements.budgetMonth.value}?`)) return;
  try {
    await requestJson(`/api/budgets/${id}`, { method: "DELETE" });
    showNotice(`${category} budget removed.`);
    await refreshBudgets();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function restoreBackup(event) {
  event.preventDefault();
  const file = elements.restoreFile.files[0];
  if (!file) {
    showNotice("Choose a backup file first.", true);
    return;
  }
  const confirmed = window.confirm(
    "Restore this backup? It will replace your account's transactions and budgets. This cannot be undone.",
  );
  if (!confirmed) {
    return;
  }

  const formData = new FormData();
  formData.append("backup", file);
  elements.restoreButton.disabled = true;
  try {
    const response = await fetch("/api/backup/restore", {
      method: "POST",
      body: formData,
      headers: {
        "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
      },
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || `Restore failed (${response.status})`);
    }
    elements.restoreForm.reset();
    showNotice(
      `Backup restored: ${result.transactions} transactions and ${result.budgets} budgets.`,
    );
    offset = 0;
    await refreshPage();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    elements.restoreButton.disabled = !elements.restoreFile.files.length;
  }
}

function currentImportMapping() {
  const mapping = {};
  for (const select of elements.importMapping.querySelectorAll("select[data-import-field]")) {
    mapping[select.dataset.importField] = select.value;
  }
  return mapping;
}

async function postImportFile(endpoint) {
  const file = elements.importFile.files[0];
  if (!file) throw new Error("Choose a CSV or Excel file first.");

  const formData = new FormData();
  formData.append("file", file);
  if (elements.importMapping.querySelector("select[data-import-field]")) {
    formData.append("mapping", JSON.stringify(currentImportMapping()));
  }
  const response = await fetch(endpoint, {
    method: "POST",
    body: formData,
    headers: {
      "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
    },
  });
  let result;
  try {
    result = await response.json();
  } catch (error) {
    if (!(error instanceof SyntaxError)) throw error;
    throw new Error(`Import request failed (${response.status}).`);
  }
  if (!response.ok) {
    throw new Error(result.error || `Import request failed (${response.status}).`);
  }
  return result;
}

function renderImportMapping(data) {
  elements.importMapping.replaceChildren();
  for (const field of IMPORT_FIELDS) {
    const label = document.createElement("label");
    label.textContent = `${field.label}${field.required ? " (required)" : ""}`;
    const select = document.createElement("select");
    select.dataset.importField = field.field;
    const emptyOption = new Option("Not mapped", "");
    select.add(emptyOption);
    for (const column of data.columns) {
      select.add(new Option(column.label, column.index));
    }
    select.value = data.mapping[field.field] || "";
    select.addEventListener("change", () => {
      elements.importConfirmButton.disabled = true;
      elements.importPreviewButton.textContent = "Update preview";
      elements.importSummary.textContent =
        "Column mapping changed. Update the preview before importing.";
    });
    label.append(select);
    elements.importMapping.append(label);
  }
  elements.importMapping.hidden = data.columns.length === 0;
}

function renderImportIssues(issues) {
  elements.importIssues.replaceChildren();
  elements.importIssuesWrap.hidden = issues.length === 0;
  for (const issue of issues) {
    const item = document.createElement("li");
    const label = issue.status === "duplicate" ? "Duplicate" : "Invalid";
    item.textContent = `Row ${issue.row}: ${label} — ${issue.error}`;
    elements.importIssues.append(item);
  }
}

function renderImportPreview(data) {
  elements.importPreviewRows.replaceChildren();
  for (const item of data.rows) {
    const row = document.createElement("tr");
    const values = [
      item.row,
      item.date || "—",
      item.type ? (item.type === "income" ? "Income" : "Expense") : "—",
      item.category || "—",
      item.description || "—",
      item.amount || "—",
      item.status === "ready" ? "Ready" : item.status === "duplicate" ? "Duplicate" : "Invalid",
    ];
    for (let index = 0; index < values.length; index += 1) {
      const cell = document.createElement("td");
      cell.textContent = String(values[index]);
      if (index === values.length - 1) {
        cell.className = `import-status-${item.status}`;
      }
      row.append(cell);
    }
    elements.importPreviewRows.append(row);
  }
  elements.importPreviewWrap.hidden = data.rows.length === 0;
  elements.importPreviewTruncation.hidden = data.total <= data.rows.length;
  elements.importPreviewTruncation.textContent =
    `Showing the first ${data.rows.length} of ${data.total} rows. All invalid and duplicate row numbers are listed below.`;
  elements.importSummary.classList.remove("error", "success");
  const counts = `${data.ready} ready · ${data.duplicates} duplicates · ${data.invalid} invalid`;
  const missing = data.missing_fields.length
    ? ` Map required columns: ${data.missing_fields.join(", ")}.`
    : "";
  elements.importSummary.textContent = `${data.total} data rows · ${counts}.${missing}`;
  renderImportIssues(data.issues);
  renderImportMapping(data);
  elements.importPreviewButton.textContent = "Update preview";
  elements.importConfirmButton.disabled = !data.can_import;
}

async function previewImport() {
  elements.importPreviewButton.disabled = true;
  elements.importSummary.textContent = "Reading and validating file…";
  elements.importSummary.classList.remove("error", "success");
  try {
    const result = await postImportFile("/api/transactions/import/preview");
    renderImportPreview(result);
  } catch (error) {
    elements.importSummary.textContent = error.message;
    elements.importSummary.classList.add("error");
    elements.importConfirmButton.disabled = true;
    showNotice(error.message, true);
  } finally {
    elements.importPreviewButton.disabled = !elements.importFile.files.length;
  }
}

async function confirmImport() {
  elements.importConfirmButton.disabled = true;
  elements.importSummary.textContent = "Importing valid transactions…";
  elements.importSummary.classList.remove("error", "success");
  try {
    const result = await postImportFile("/api/transactions/import");
    elements.importSummary.textContent =
      `Import complete: ${result.imported} imported · ${result.duplicates} duplicates skipped · ${result.invalid} invalid rows.`;
    elements.importSummary.classList.add("success");
    renderImportIssues(result.issues);
    showNotice(`${result.imported} transactions imported; ${result.duplicates} duplicates skipped.`);
    offset = 0;
    await refreshPage();
  } catch (error) {
    elements.importSummary.textContent = `Import failed: ${error.message}`;
    elements.importSummary.classList.add("error");
    showNotice(error.message, true);
  } finally {
    elements.importConfirmButton.disabled = true;
  }
}

function openImportDialog() {
  elements.importFile.value = "";
  elements.importPreviewRows.replaceChildren();
  elements.importIssues.replaceChildren();
  elements.importMapping.replaceChildren();
  elements.importMapping.hidden = true;
  elements.importPreviewWrap.hidden = true;
  elements.importIssuesWrap.hidden = true;
  elements.importPreviewTruncation.hidden = true;
  elements.importSummary.textContent = "";
  elements.importSummary.classList.remove("error", "success");
  elements.importPreviewButton.disabled = true;
  elements.importPreviewButton.textContent = "Preview file";
  elements.importConfirmButton.disabled = true;
  elements.importDialog.showModal();
}

function renderExportPreview(data) {
  elements.exportList.replaceChildren();
  elements.exportEmpty.hidden = data.total > 0;
  if (data.total > 0) {
    elements.downloadExport.href = `/api/transactions/export.csv?${filtersQuery()}`;
    elements.downloadExport.removeAttribute("aria-disabled");
    elements.downloadExport.removeAttribute("tabindex");
  } else {
    elements.downloadExport.removeAttribute("href");
    elements.downloadExport.setAttribute("aria-disabled", "true");
    elements.downloadExport.tabIndex = -1;
  }
  for (const transaction of data.transactions) {
    const row = document.createElement("tr");
    const values = [
      dateLabel(transaction.date),
      transaction.type === "income" ? "Income" : "Expense",
      transaction.category,
      transaction.description || "—",
    ];
    for (const value of values) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    const amount = document.createElement("td");
    amount.className = `amount-cell ${transaction.type}`;
    amount.textContent = currencyNumber.format(Number(transaction.amount));
    row.append(amount);
    elements.exportList.append(row);
  }

  const first = data.total ? data.offset + 1 : 0;
  const last = data.offset + data.transactions.length;
  elements.exportCount.textContent = data.total
    ? `Showing ${first}–${last} of ${data.total} transactions. The download will include all ${data.total}.`
    : "No transactions to export with the current filters.";
  elements.exportPrevious.disabled = data.offset === 0;
  elements.exportNext.disabled = data.offset + data.transactions.length >= data.total;
}

async function loadExportPreview() {
  elements.exportLoading.hidden = false;
  elements.exportEmpty.hidden = true;
  elements.exportList.replaceChildren();
  elements.exportPrevious.disabled = true;
  elements.exportNext.disabled = true;
  elements.downloadExport.removeAttribute("href");
  elements.downloadExport.setAttribute("aria-disabled", "true");
  elements.downloadExport.tabIndex = -1;
  try {
    const params = filtersQuery();
    params.set("offset", String(exportOffset));
    const data = await requestJson(`/api/transactions/export-preview?${params}`);
    renderExportPreview(data);
  } catch (error) {
    elements.exportDialog.close();
    showNotice(error.message, true);
  } finally {
    elements.exportLoading.hidden = true;
  }
}

async function openExportPreview() {
  exportOffset = 0;
  elements.exportDialog.showModal();
  await loadExportPreview();
}

async function refreshPage() {
  elements.loading.hidden = false;
  try {
    await refreshCategoryOptions();
    const params = filtersQuery();
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    const analyticsParams = dateRangeQuery();
    const [transactionData, monthlyData, categoryData, periodData] = await Promise.all([
      requestJson(`/api/transactions?${params}`),
      requestJson(`/api/analytics/monthly?${analyticsParams}`),
      requestJson(`/api/analytics/categories?${analyticsParams}`),
      requestJson(`/api/analytics/period?${analyticsParams}`),
    ]);
    renderTransactions(transactionData.transactions);
    renderPeriodSummary(periodData.summary);
    renderTrends(monthlyData.monthly);
    renderCategories(categoryData.categories);
    await refreshBudgets();
  } catch (error) {
    showNotice(error.message, true);
  } finally {
    elements.loading.hidden = true;
  }
}

function resetForm() {
  elements.form.reset();
  elements.transactionId.value = "";
  elements.entryDate.value = todayIsoDate();
  elements.formTitle.textContent = "Add a transaction";
  elements.form.hidden = true;
}

function openCreateForm() {
  resetForm();
  elements.form.hidden = false;
  elements.entryCategory.focus();
}

function openEditForm(transaction) {
  elements.form.reset();
  elements.transactionId.value = transaction.id;
  elements.entryType.value = transaction.type;
  elements.entryAmount.value = transaction.amount.toFixed(2);
  elements.entryCategory.value = transaction.category;
  elements.entryDate.value = transaction.date;
  elements.entryDescription.value = transaction.description;
  elements.formTitle.textContent = "Edit transaction";
  elements.form.hidden = false;
  elements.form.scrollIntoView({ behavior: "smooth", block: "center" });
  elements.entryType.focus();
}

async function saveTransaction(event) {
  event.preventDefault();
  const id = elements.transactionId.value;
  const payload = {
    type: elements.entryType.value,
    amount: Number(elements.entryAmount.value),
    category: elements.entryCategory.value.trim(),
    date: elements.entryDate.value,
    description: elements.entryDescription.value.trim(),
  };
  try {
    await requestJson(id ? `/api/transactions/${id}` : "/api/transactions", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    });
    resetForm();
    offset = 0;
    showNotice(id ? "Transaction updated." : "Transaction added.");
    await refreshPage();
  } catch (error) {
    showNotice(error.message, true);
  }
}

async function deleteTransaction(id) {
  if (!window.confirm("Delete this transaction? This cannot be undone.")) return;
  try {
    await requestJson(`/api/transactions/${id}`, { method: "DELETE" });
    if (offset > 0 && elements.transactionList.children.length === 1) {
      offset = Math.max(0, offset - PAGE_SIZE);
    }
    showNotice("Transaction deleted.");
    await refreshPage();
  } catch (error) {
    showNotice(error.message, true);
  }
}

elements.form.addEventListener("submit", saveTransaction);
elements.budgetForm.addEventListener("submit", saveBudget);
elements.budgetMonth.addEventListener("change", refreshBudgets);
elements.restoreForm.addEventListener("submit", restoreBackup);
elements.restoreFile.addEventListener("change", () => {
  elements.restoreButton.disabled = !elements.restoreFile.files.length;
});
elements.importFile.addEventListener("change", () => {
  elements.importPreviewButton.disabled = !elements.importFile.files.length;
  elements.importConfirmButton.disabled = true;
  elements.importSummary.textContent = "";
  elements.importMapping.replaceChildren();
  elements.importMapping.hidden = true;
  elements.importPreviewWrap.hidden = true;
  elements.importIssuesWrap.hidden = true;
});
elements.importPreviewButton.addEventListener("click", previewImport);
elements.importConfirmButton.addEventListener("click", confirmImport);
document.querySelector("#import-transactions").addEventListener("click", openImportDialog);
document.querySelector("#close-import").addEventListener("click", () => elements.importDialog.close());
document.querySelector("#cancel-import").addEventListener("click", () => elements.importDialog.close());
elements.importDialog.addEventListener("click", (event) => {
  if (event.target === elements.importDialog) elements.importDialog.close();
});
elements.newTransaction.addEventListener("click", openCreateForm);
elements.newTransactionSecondary.addEventListener("click", openCreateForm);
elements.emptyAdd.addEventListener("click", openCreateForm);
elements.discardForm.addEventListener("click", resetForm);
document.querySelector("#preview-export").addEventListener("click", openExportPreview);
document.querySelector("#close-export").addEventListener("click", () => elements.exportDialog.close());
document.querySelector("#cancel-export").addEventListener("click", () => elements.exportDialog.close());
elements.exportDialog.addEventListener("click", (event) => {
  if (event.target === elements.exportDialog) elements.exportDialog.close();
});
elements.exportPrevious.addEventListener("click", () => {
  exportOffset = Math.max(0, exportOffset - EXPORT_PREVIEW_SIZE);
  loadExportPreview();
});
elements.exportNext.addEventListener("click", () => {
  exportOffset += EXPORT_PREVIEW_SIZE;
  loadExportPreview();
});
document.querySelector("#cancel-edit").addEventListener("click", resetForm);
elements.filterForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (
    elements.filterStart.value &&
    elements.filterEnd.value &&
    elements.filterStart.value > elements.filterEnd.value
  ) {
    showNotice("The start date must be on or before the end date.", true);
    return;
  }
  offset = 0;
  refreshPage();
});
elements.dashboardSearchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  elements.filterSearch.value = elements.dashboardSearch.value.trim();
  offset = 0;
  refreshPage();
});
elements.clearFilters.addEventListener("click", () => {
  elements.filterForm.reset();
  elements.dashboardSearch.value = "";
  offset = 0;
  refreshPage();
});
for (const link of document.querySelectorAll(".sidebar-nav a")) {
  link.addEventListener("click", () => {
    for (const navLink of document.querySelectorAll(".sidebar-nav a")) {
      navLink.classList.remove("active");
      navLink.removeAttribute("aria-current");
    }
    link.classList.add("active");
    link.setAttribute("aria-current", "page");
  });
}
elements.previousPage.addEventListener("click", () => {
  offset = Math.max(0, offset - PAGE_SIZE);
  refreshPage();
});
elements.nextPage.addEventListener("click", () => {
  offset += PAGE_SIZE;
  refreshPage();
});

resetForm();
elements.budgetMonth.value = currentMonthIso();
refreshPage();
