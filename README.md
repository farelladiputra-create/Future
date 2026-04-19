# Future — Budget Planner

A personal budget planner that runs entirely in the browser. No server required — all data is stored in `localStorage`.

## Features

- **Dashboard** — monthly income/expense summary, balance, savings rate
- **Transactions** — add, edit, delete income and expense entries with categories
- **Budgets** — set monthly spending limits per category with progress tracking
- **Reports** — 6-month cash flow chart, expense breakdown pie chart, top spending categories
- **Month picker** — navigate between months; all views update accordingly
- **Responsive** — works on desktop and mobile

## Getting Started

Open `index.html` directly in a browser — no build step needed.

```
open index.html
```

## Tech Stack

- Vanilla HTML / CSS / JavaScript
- [Chart.js 4](https://www.chartjs.org/) (loaded via CDN)
- Browser `localStorage` for persistence
