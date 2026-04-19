'use strict';

// ─── Default Data ────────────────────────────────────────────────────────────

const DEFAULT_CATEGORIES = [
  { id: 'housing',       name: 'Housing',       icon: '🏠', type: 'expense' },
  { id: 'food',          name: 'Food & Dining',  icon: '🍔', type: 'expense' },
  { id: 'transport',     name: 'Transport',      icon: '🚗', type: 'expense' },
  { id: 'utilities',     name: 'Utilities',      icon: '💡', type: 'expense' },
  { id: 'health',        name: 'Health',         icon: '🏥', type: 'expense' },
  { id: 'entertainment', name: 'Entertainment',  icon: '🎮', type: 'expense' },
  { id: 'shopping',      name: 'Shopping',       icon: '🛍️', type: 'expense' },
  { id: 'education',     name: 'Education',      icon: '📚', type: 'expense' },
  { id: 'savings',       name: 'Savings',        icon: '🏦', type: 'expense' },
  { id: 'other_exp',     name: 'Other',          icon: '📦', type: 'expense' },
  { id: 'salary',        name: 'Salary',         icon: '💼', type: 'income'  },
  { id: 'freelance',     name: 'Freelance',      icon: '💻', type: 'income'  },
  { id: 'investment',    name: 'Investments',    icon: '📈', type: 'income'  },
  { id: 'gift',          name: 'Gift',           icon: '🎁', type: 'income'  },
  { id: 'other_inc',     name: 'Other Income',   icon: '💰', type: 'income'  },
];

// ─── State ───────────────────────────────────────────────────────────────────

const state = {
  transactions: [],
  budgets: [],
  categories: [],
  currentMonth: '',   // "YYYY-MM"
  charts: {},
  pendingDelete: null,
};

// ─── Persistence ─────────────────────────────────────────────────────────────

function save() {
  localStorage.setItem('bp_transactions', JSON.stringify(state.transactions));
  localStorage.setItem('bp_budgets', JSON.stringify(state.budgets));
  localStorage.setItem('bp_categories', JSON.stringify(state.categories));
}

function load() {
  state.transactions = JSON.parse(localStorage.getItem('bp_transactions') || '[]');
  state.budgets      = JSON.parse(localStorage.getItem('bp_budgets')      || '[]');
  state.categories   = JSON.parse(localStorage.getItem('bp_categories')   || 'null')
                       || JSON.parse(JSON.stringify(DEFAULT_CATEGORIES));
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
}

function fmt(n) {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n);
}

function getCategoryById(id) {
  return state.categories.find(c => c.id === id) || { name: id, icon: '📦' };
}

function monthTransactions(month) {
  return state.transactions.filter(t => t.date.startsWith(month));
}

function totals(txList) {
  return txList.reduce(
    (acc, t) => {
      if (t.type === 'income') acc.income += t.amount;
      else acc.expense += t.amount;
      return acc;
    },
    { income: 0, expense: 0 }
  );
}

function expenseByCategory(txList) {
  const map = {};
  txList.filter(t => t.type === 'expense').forEach(t => {
    map[t.category] = (map[t.category] || 0) + t.amount;
  });
  return map;
}

// ─── Navigation ──────────────────────────────────────────────────────────────

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const page = document.getElementById('page-' + name);
  if (page) page.classList.add('active');

  document.querySelectorAll('[data-page="' + name + '"]').forEach(n => n.classList.add('active'));

  if (name === 'dashboard') renderDashboard();
  if (name === 'transactions') renderTransactions();
  if (name === 'budgets') renderBudgets();
  if (name === 'reports') renderReports();
}

// ─── Dashboard ───────────────────────────────────────────────────────────────

function renderDashboard() {
  const txs = monthTransactions(state.currentMonth);
  const { income, expense } = totals(txs);
  const balance = income - expense;
  const savRate = income > 0 ? Math.round((balance / income) * 100) : 0;

  document.getElementById('totalIncome').textContent    = fmt(income);
  document.getElementById('totalExpenses').textContent  = fmt(expense);
  document.getElementById('balance').textContent        = fmt(balance);
  document.getElementById('incomeCount').textContent    = txs.filter(t => t.type === 'income').length + ' transactions';
  document.getElementById('expenseCount').textContent   = txs.filter(t => t.type === 'expense').length + ' transactions';
  document.getElementById('savingsRate').textContent    = 'Savings rate: ' + savRate + '%';

  const balCard = document.querySelector('.card--balance');
  balCard.classList.toggle('negative', balance < 0);

  renderCategoryChart(txs);
  renderBudgetProgress(txs);
  renderRecentTransactions(txs);
}

function renderCategoryChart(txs) {
  const catMap = expenseByCategory(txs);
  const labels = Object.keys(catMap).map(id => getCategoryById(id).name);
  const data   = Object.values(catMap);

  const COLORS = [
    '#6c63ff','#ff5c7c','#00c896','#ffa94d','#4fc3f7',
    '#ab47bc','#ef5350','#26a69a','#ff7043','#66bb6a',
  ];

  const ctx = document.getElementById('categoryChart').getContext('2d');
  if (state.charts.category) state.charts.category.destroy();

  if (data.length === 0) {
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.fillStyle = '#8892b0';
    ctx.textAlign = 'center';
    ctx.font = '13px sans-serif';
    ctx.fillText('No expense data for this month', ctx.canvas.width / 2, 110);
    return;
  }

  state.charts.category = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{ data, backgroundColor: COLORS, borderWidth: 0, hoverOffset: 6 }],
    },
    options: {
      plugins: {
        legend: { position: 'right', labels: { color: '#e8eaf6', font: { size: 11 }, padding: 12 } },
        tooltip: { callbacks: { label: ctx => ' ' + fmt(ctx.raw) } },
      },
      maintainAspectRatio: false,
    },
  });
}

function renderBudgetProgress(txs) {
  const catSpend = expenseByCategory(txs);
  const el = document.getElementById('budgetProgressList');

  if (state.budgets.length === 0) {
    el.innerHTML = '<p class="empty-state">No budgets set. Go to Budgets to add one.</p>';
    return;
  }

  el.innerHTML = state.budgets.map(b => {
    const cat   = getCategoryById(b.category);
    const spent = catSpend[b.category] || 0;
    const pct   = Math.min((spent / b.amount) * 100, 100);
    const cls   = pct >= 100 ? 'danger' : pct >= 80 ? 'warning' : '';

    return `
      <div class="budget-progress-item">
        <div class="bp-header">
          <span class="bp-category">${cat.icon} ${cat.name}</span>
          <span class="bp-amounts">${fmt(spent)} / ${fmt(b.amount)}</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill ${cls ? 'progress-fill--' + cls : ''}"
               style="width:${pct}%"></div>
        </div>
      </div>`;
  }).join('');
}

function renderRecentTransactions(txs) {
  const el = document.getElementById('recentTransactions');
  const recent = [...txs].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5);

  if (recent.length === 0) {
    el.innerHTML = '<p class="empty-state">No transactions yet. Add one to get started.</p>';
    return;
  }

  el.innerHTML = recent.map(t => txRow(t)).join('');
  bindTxActions(el);
}

// ─── Transactions Page ────────────────────────────────────────────────────────

function renderTransactions() {
  const txs = monthTransactions(state.currentMonth);
  const search   = document.getElementById('searchInput').value.toLowerCase();
  const typeF    = document.getElementById('filterType').value;
  const catF     = document.getElementById('filterCategory').value;

  let filtered = txs.filter(t => {
    const matchSearch = !search ||
      t.description.toLowerCase().includes(search) ||
      getCategoryById(t.category).name.toLowerCase().includes(search);
    const matchType = typeF === 'all' || t.type === typeF;
    const matchCat  = catF === 'all' || t.category === catF;
    return matchSearch && matchType && matchCat;
  }).sort((a, b) => b.date.localeCompare(a.date));

  const el = document.getElementById('allTransactions');

  if (filtered.length === 0) {
    el.innerHTML = '<p class="empty-state">No matching transactions.</p>';
    return;
  }

  el.innerHTML = filtered.map(t => txRow(t)).join('');
  bindTxActions(el);
}

function txRow(t) {
  const cat = getCategoryById(t.category);
  const isIncome = t.type === 'income';
  const date = new Date(t.date + 'T00:00:00').toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  });

  return `
    <div class="tx-item" data-id="${t.id}">
      <div class="tx-icon tx-icon--${t.type}">${cat.icon}</div>
      <div class="tx-info">
        <div class="tx-desc">${escHtml(t.description)}</div>
        <div class="tx-meta">
          <span class="category-badge">${cat.name}</span>
          &nbsp;${date}${t.notes ? ' · ' + escHtml(t.notes) : ''}
        </div>
      </div>
      <div class="tx-amount tx-amount--${t.type}">
        ${isIncome ? '+' : '-'}${fmt(t.amount)}
      </div>
      <div class="tx-actions">
        <button class="icon-btn edit-tx" data-id="${t.id}" title="Edit">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
        <button class="icon-btn delete delete-tx" data-id="${t.id}" title="Delete">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="3 6 5 6 21 6"/>
            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
            <path d="M10 11v6"/><path d="M14 11v6"/>
            <path d="M9 6V4h6v2"/>
          </svg>
        </button>
      </div>
    </div>`;
}

function bindTxActions(container) {
  container.querySelectorAll('.edit-tx').forEach(btn => {
    btn.addEventListener('click', () => openEditTransaction(btn.dataset.id));
  });
  container.querySelectorAll('.delete-tx').forEach(btn => {
    btn.addEventListener('click', () => confirmDelete('transaction', btn.dataset.id));
  });
}

// ─── Budgets Page ─────────────────────────────────────────────────────────────

function renderBudgets() {
  const txs    = monthTransactions(state.currentMonth);
  const catMap = expenseByCategory(txs);
  const el     = document.getElementById('budgetsList');

  if (state.budgets.length === 0) {
    el.innerHTML = '<p class="empty-state">No budgets set yet. Click "+ Add Budget" to create one.</p>';
    return;
  }

  el.innerHTML = state.budgets.map(b => {
    const cat   = getCategoryById(b.category);
    const spent = catMap[b.category] || 0;
    const pct   = Math.min((spent / b.amount) * 100, 100);
    const over  = spent > b.amount;
    const near  = !over && pct >= 80;
    const statusCls  = over ? 'over' : near ? 'warn' : 'ok';
    const statusText = over
      ? `Over budget by ${fmt(spent - b.amount)}`
      : near
      ? `${Math.round(100 - pct)}% remaining — getting close!`
      : `${fmt(b.amount - spent)} remaining`;
    const fillCls = over ? 'progress-fill--danger' : near ? 'progress-fill--warning' : '';

    return `
      <div class="budget-card">
        <div class="budget-card-header">
          <div class="budget-card-title">${cat.icon} ${cat.name}</div>
          <div class="budget-card-actions">
            <button class="icon-btn edit-budget" data-id="${b.id}" title="Edit">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
            </button>
            <button class="icon-btn delete delete-budget" data-id="${b.id}" title="Delete">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                <path d="M10 11v6"/><path d="M14 11v6"/>
                <path d="M9 6V4h6v2"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="budget-amount">
          Spent <span>${fmt(spent)}</span> of <span>${fmt(b.amount)}</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill ${fillCls}" style="width:${pct}%"></div>
        </div>
        <div class="budget-status budget-status--${statusCls}">${statusText}</div>
      </div>`;
  }).join('');

  el.querySelectorAll('.edit-budget').forEach(btn => {
    btn.addEventListener('click', () => openEditBudget(btn.dataset.id));
  });
  el.querySelectorAll('.delete-budget').forEach(btn => {
    btn.addEventListener('click', () => confirmDelete('budget', btn.dataset.id));
  });
}

// ─── Reports Page ─────────────────────────────────────────────────────────────

function renderReports() {
  renderCashFlowChart();
  renderExpenseBreakdownChart();
  renderTopCategories();
}

function last6Months() {
  const months = [];
  const d = new Date(state.currentMonth + '-01');
  for (let i = 5; i >= 0; i--) {
    const dt = new Date(d.getFullYear(), d.getMonth() - i, 1);
    months.push(dt.toISOString().slice(0, 7));
  }
  return months;
}

function renderCashFlowChart() {
  const months = last6Months();
  const incomeData  = months.map(m => totals(monthTransactions(m)).income);
  const expenseData = months.map(m => totals(monthTransactions(m)).expense);
  const labels = months.map(m => {
    const [y, mo] = m.split('-');
    return new Date(+y, +mo - 1).toLocaleString('default', { month: 'short', year: '2-digit' });
  });

  const ctx = document.getElementById('cashFlowChart').getContext('2d');
  if (state.charts.cashFlow) state.charts.cashFlow.destroy();

  state.charts.cashFlow = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        { label: 'Income',   data: incomeData,  backgroundColor: 'rgba(0,200,150,0.7)',   borderRadius: 4 },
        { label: 'Expenses', data: expenseData, backgroundColor: 'rgba(255,92,124,0.7)',  borderRadius: 4 },
      ],
    },
    options: {
      plugins: {
        legend: { labels: { color: '#e8eaf6', font: { size: 12 } } },
        tooltip: { callbacks: { label: ctx => ' ' + fmt(ctx.raw) } },
      },
      scales: {
        x: { ticks: { color: '#8892b0' }, grid: { color: 'rgba(46,51,80,0.5)' } },
        y: { ticks: { color: '#8892b0', callback: v => '$' + v }, grid: { color: 'rgba(46,51,80,0.5)' } },
      },
      maintainAspectRatio: false,
    },
  });
}

function renderExpenseBreakdownChart() {
  const txs    = monthTransactions(state.currentMonth);
  const catMap = expenseByCategory(txs);
  const COLORS = ['#6c63ff','#ff5c7c','#00c896','#ffa94d','#4fc3f7','#ab47bc','#ef5350','#26a69a'];

  const ctx = document.getElementById('expenseBreakdownChart').getContext('2d');
  if (state.charts.expBreakdown) state.charts.expBreakdown.destroy();

  const entries = Object.entries(catMap).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) { ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height); return; }

  state.charts.expBreakdown = new Chart(ctx, {
    type: 'pie',
    data: {
      labels: entries.map(([id]) => getCategoryById(id).name),
      datasets: [{ data: entries.map(([, v]) => v), backgroundColor: COLORS, borderWidth: 0 }],
    },
    options: {
      plugins: {
        legend: { position: 'bottom', labels: { color: '#e8eaf6', font: { size: 11 }, padding: 10 } },
        tooltip: { callbacks: { label: ctx => ' ' + fmt(ctx.raw) } },
      },
      maintainAspectRatio: false,
    },
  });
}

function renderTopCategories() {
  const txs    = monthTransactions(state.currentMonth);
  const catMap = expenseByCategory(txs);
  const el     = document.getElementById('topCategories');

  const sorted = Object.entries(catMap).sort((a, b) => b[1] - a[1]).slice(0, 6);
  if (sorted.length === 0) { el.innerHTML = '<p class="empty-state">No expense data.</p>'; return; }

  const max = sorted[0][1];
  el.innerHTML = sorted.map(([id, amt], i) => {
    const cat = getCategoryById(id);
    const pct = (amt / max) * 100;
    return `
      <div class="top-cat-item">
        <div class="top-cat-rank">${i + 1}</div>
        <div class="top-cat-info">
          <div class="top-cat-name">${cat.icon} ${cat.name}</div>
          <div class="top-cat-bar-wrap">
            <div class="top-cat-bar" style="width:${pct}%"></div>
          </div>
        </div>
        <div class="top-cat-amount">${fmt(amt)}</div>
      </div>`;
  }).join('');
}

// ─── Transaction Modal ────────────────────────────────────────────────────────

function openAddTransaction() {
  document.getElementById('transactionModalTitle').textContent = 'Add Transaction';
  document.getElementById('transactionId').value = '';
  document.getElementById('txAmount').value = '';
  document.getElementById('txDate').value = state.currentMonth + '-' + new Date().getDate().toString().padStart(2, '0');
  document.getElementById('txDescription').value = '';
  document.getElementById('txNotes').value = '';
  document.querySelector('input[name="type"][value="expense"]').checked = true;

  populateCategorySelect('txCategory', 'expense');
  openModal('transactionModal');
}

function openEditTransaction(id) {
  const t = state.transactions.find(x => x.id === id);
  if (!t) return;

  document.getElementById('transactionModalTitle').textContent = 'Edit Transaction';
  document.getElementById('transactionId').value = t.id;
  document.getElementById('txAmount').value = t.amount;
  document.getElementById('txDate').value = t.date;
  document.getElementById('txDescription').value = t.description;
  document.getElementById('txNotes').value = t.notes || '';
  document.querySelector(`input[name="type"][value="${t.type}"]`).checked = true;

  populateCategorySelect('txCategory', t.type, t.category);
  openModal('transactionModal');
}

function populateCategorySelect(selectId, type, selected) {
  const sel = document.getElementById(selectId);
  const cats = state.categories.filter(c => !type || c.type === type);
  sel.innerHTML = cats.map(c =>
    `<option value="${c.id}" ${c.id === selected ? 'selected' : ''}>${c.icon} ${c.name}</option>`
  ).join('');
}

function saveTransaction(e) {
  e.preventDefault();

  const id   = document.getElementById('transactionId').value;
  const type = document.querySelector('input[name="type"]:checked').value;
  const tx   = {
    id:          id || uid(),
    type,
    amount:      parseFloat(document.getElementById('txAmount').value),
    date:        document.getElementById('txDate').value,
    category:    document.getElementById('txCategory').value,
    description: document.getElementById('txDescription').value.trim(),
    notes:       document.getElementById('txNotes').value.trim(),
  };

  if (id) {
    const idx = state.transactions.findIndex(x => x.id === id);
    if (idx !== -1) state.transactions[idx] = tx;
  } else {
    state.transactions.push(tx);
  }

  save();
  closeModal('transactionModal');
  refreshCurrentPage();
}

// ─── Budget Modal ─────────────────────────────────────────────────────────────

function openAddBudget() {
  document.getElementById('budgetModalTitle').textContent = 'Add Budget';
  document.getElementById('budgetId').value = '';
  document.getElementById('budgetAmount').value = '';
  populateCategorySelect('budgetCategory', 'expense');
  openModal('budgetModal');
}

function openEditBudget(id) {
  const b = state.budgets.find(x => x.id === id);
  if (!b) return;

  document.getElementById('budgetModalTitle').textContent = 'Edit Budget';
  document.getElementById('budgetId').value = b.id;
  document.getElementById('budgetAmount').value = b.amount;
  populateCategorySelect('budgetCategory', 'expense', b.category);
  openModal('budgetModal');
}

function saveBudget(e) {
  e.preventDefault();

  const id       = document.getElementById('budgetId').value;
  const category = document.getElementById('budgetCategory').value;
  const amount   = parseFloat(document.getElementById('budgetAmount').value);

  if (id) {
    const idx = state.budgets.findIndex(x => x.id === id);
    if (idx !== -1) state.budgets[idx] = { id, category, amount };
  } else {
    const existing = state.budgets.find(b => b.category === category);
    if (existing) { existing.amount = amount; }
    else { state.budgets.push({ id: uid(), category, amount }); }
  }

  save();
  closeModal('budgetModal');
  renderBudgets();
}

// ─── Delete ───────────────────────────────────────────────────────────────────

function confirmDelete(type, id) {
  state.pendingDelete = { type, id };
  document.getElementById('deleteMessage').textContent =
    type === 'transaction'
      ? 'Are you sure you want to delete this transaction? This cannot be undone.'
      : 'Are you sure you want to delete this budget? Transactions will not be affected.';
  openModal('deleteModal');
}

function executeDelete() {
  if (!state.pendingDelete) return;
  const { type, id } = state.pendingDelete;

  if (type === 'transaction') {
    state.transactions = state.transactions.filter(t => t.id !== id);
  } else if (type === 'budget') {
    state.budgets = state.budgets.filter(b => b.id !== id);
  }

  save();
  closeModal('deleteModal');
  state.pendingDelete = null;
  refreshCurrentPage();
}

// ─── Modal helpers ────────────────────────────────────────────────────────────

function openModal(id) {
  document.getElementById(id).classList.add('open');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// ─── Category select for filter bar ──────────────────────────────────────────

function populateFilterCategories() {
  const sel = document.getElementById('filterCategory');
  const current = sel.value;
  sel.innerHTML = '<option value="all">All Categories</option>' +
    state.categories.map(c =>
      `<option value="${c.id}" ${c.id === current ? 'selected' : ''}>${c.icon} ${c.name}</option>`
    ).join('');
}

// ─── Current page refresh ─────────────────────────────────────────────────────

function refreshCurrentPage() {
  const active = document.querySelector('.page.active');
  if (!active) return;
  const name = active.id.replace('page-', '');
  if (name === 'dashboard')    renderDashboard();
  if (name === 'transactions') renderTransactions();
  if (name === 'budgets')      renderBudgets();
  if (name === 'reports')      renderReports();
}

// ─── XSS helper ───────────────────────────────────────────────────────────────

function escHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(str));
  return d.innerHTML;
}

// ─── Init ─────────────────────────────────────────────────────────────────────

function init() {
  load();

  // Set current month
  const today = new Date();
  state.currentMonth = today.toISOString().slice(0, 7);

  const picker = document.getElementById('monthPicker');
  picker.value = state.currentMonth;
  picker.addEventListener('change', () => {
    state.currentMonth = picker.value;
    populateFilterCategories();
    refreshCurrentPage();
  });

  // Navigation
  document.querySelectorAll('[data-page]').forEach(btn => {
    btn.addEventListener('click', () => showPage(btn.dataset.page));
  });

  // Transaction modal
  document.getElementById('openAddTransaction').addEventListener('click', openAddTransaction);
  document.getElementById('openAddTransaction2').addEventListener('click', openAddTransaction);
  document.getElementById('closeTransactionModal').addEventListener('click', () => closeModal('transactionModal'));
  document.getElementById('cancelTransaction').addEventListener('click', () => closeModal('transactionModal'));
  document.getElementById('transactionForm').addEventListener('submit', saveTransaction);

  // Re-populate categories when type changes
  document.querySelectorAll('input[name="type"]').forEach(radio => {
    radio.addEventListener('change', () => {
      populateCategorySelect('txCategory', radio.value);
    });
  });

  // Budget modal
  document.getElementById('openAddBudget').addEventListener('click', openAddBudget);
  document.getElementById('closeBudgetModal').addEventListener('click', () => closeModal('budgetModal'));
  document.getElementById('cancelBudget').addEventListener('click', () => closeModal('budgetModal'));
  document.getElementById('budgetForm').addEventListener('submit', saveBudget);

  // Delete modal
  document.getElementById('closeDeleteModal').addEventListener('click', () => closeModal('deleteModal'));
  document.getElementById('cancelDelete').addEventListener('click', () => closeModal('deleteModal'));
  document.getElementById('confirmDelete').addEventListener('click', executeDelete);

  // Close modals on overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });

  // Filters
  document.getElementById('searchInput').addEventListener('input', renderTransactions);
  document.getElementById('filterType').addEventListener('change', renderTransactions);
  document.getElementById('filterCategory').addEventListener('change', renderTransactions);

  populateFilterCategories();
  showPage('dashboard');
}

document.addEventListener('DOMContentLoaded', init);
