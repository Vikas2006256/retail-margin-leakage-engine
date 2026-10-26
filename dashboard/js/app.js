/**
 * Retail Margin & Inventory Leakage — Universal Reactive Dashboard Controller
 * Full client-side cross-filtering across KPIs, Charts, Heatmaps, and Alert Queues
 */

let dashboardData = null;
let currentFilters = {
  year: 'ALL',
  category: 'ALL',
  region: 'ALL',
  shipMode: 'ALL',
  priority: 'ALL',
  actionCode: 'ALL',
  search: ''
};
let activeStateMetric = 'margin_pct';
let activeSubcatMetric = 'margin_pct';
let activeTab = 'tab-executive';

document.addEventListener('DOMContentLoaded', () => {
  initApp();
});

async function initApp() {
  setupNavigation();
  setupFilterListeners();
  setupModal();
  await loadDashboardData();
}

// ── Tab Navigation ─────────────────────────────────────────────────────────
function setupNavigation() {
  const tabs = document.querySelectorAll('.tab-btn');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const targetId = tab.dataset.tab;
      if (!targetId) return;

      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
      });

      const activeContent = document.getElementById(targetId);
      if (activeContent) {
        activeContent.classList.add('active');
        activeTab = targetId;
        refreshActiveTabCharts();
      }
    });
  });
}

// ── Data Ingestion & State Initialization ─────────────────────────────────
async function loadDashboardData() {
  try {
    const response = await fetch('data/dashboard_data.json');
    if (!response.ok) {
      throw new Error(`HTTP error: ${response.status}`);
    }
    dashboardData = await response.json();
    
    // Initial render using full dataset
    const meta = dashboardData.metadata;
    const updateElem = document.getElementById('last-updated-text');
    if (updateElem && meta.generated_at) {
      updateElem.textContent = `Live Pipeline Engine · ${meta.dataset_rows.toLocaleString()} Transactions (${meta.years_covered.join('-')})`;
    }

    // Populate SQL lab (static reference queries)
    populateSqlQueries(dashboardData.sql_queries);

    // Run reactive calculation & render across all components
    recalculateAndRenderDashboard();
  } catch (err) {
    console.error('Failed to load dashboard data:', err);
    showNotification('Error loading dashboard data. Ensure dashboard_data.json exists.', 'error');
  }
}

// ── Reactive Filtering Engine ─────────────────────────────────────────────
function filterRecords(records) {
  if (!records) return [];
  const q = currentFilters.search.trim().toLowerCase();

  return records.filter(r => {
    if (currentFilters.year !== 'ALL' && r.yr !== Number(currentFilters.year)) return false;
    if (currentFilters.category !== 'ALL' && r.cat !== currentFilters.category) return false;
    if (currentFilters.region !== 'ALL' && r.reg !== currentFilters.region) return false;
    if (currentFilters.shipMode !== 'ALL' && r.sm !== currentFilters.shipMode) return false;
    if (currentFilters.actionCode !== 'ALL' && r.action !== currentFilters.actionCode) return false;
    
    if (currentFilters.priority !== 'ALL') {
      if (currentFilters.priority === 'ALERT_ONLY' && r.priority === 0) return false;
      if (currentFilters.priority !== 'ALERT_ONLY' && r.priority !== Number(currentFilters.priority)) return false;
    }

    if (q) {
      const match = r.id.toLowerCase().includes(q) ||
                    r.sc.toLowerCase().includes(q) ||
                    r.cat.toLowerCase().includes(q) ||
                    r.st.toLowerCase().includes(q) ||
                    r.reg.toLowerCase().includes(q) ||
                    (r.prod && r.prod.toLowerCase().includes(q));
      if (!match) return false;
    }
    return true;
  });
}

function recalculateAndRenderDashboard() {
  if (!dashboardData || !dashboardData.records) return;

  const records = filterRecords(dashboardData.records);
  const totalRecords = records.length;

  renderActiveFilterChips();

  // 1. Calculate Executive KPIs
  let grossSales = 0;
  let netProfit = 0;
  let discountBleed = 0;
  let lossCount = 0;
  const uniqueOrderIds = new Set();

  records.forEach(r => {
    grossSales += r.sales;
    netProfit += r.profit;
    discountBleed += r.bleed;
    if (r.profit < 0) lossCount++;
    uniqueOrderIds.add(r.id);
  });

  const blendedMargin = grossSales > 0 ? (netProfit / grossSales) * 100 : 0;
  const lossPct = totalRecords > 0 ? (lossCount / totalRecords) * 100 : 0;

  document.getElementById('kpi-gross-sales').textContent = formatCurrency(grossSales);
  document.getElementById('kpi-net-profit').textContent = formatCurrency(netProfit);
  document.getElementById('kpi-margin-pct').textContent = blendedMargin.toFixed(1) + '%';
  document.getElementById('kpi-discount-loss').textContent = formatCurrency(discountBleed);

  const deltaSalesEl = document.getElementById('delta-sales');
  if (deltaSalesEl) {
    deltaSalesEl.textContent = `${totalRecords.toLocaleString()} line items`;
    deltaSalesEl.className = 'kpi-delta neutral';
  }

  const deltaMarginEl = document.getElementById('delta-margin');
  if (deltaMarginEl) {
    deltaMarginEl.textContent = `${blendedMargin >= 0 ? '+' : ''}${blendedMargin.toFixed(1)}% margin`;
    deltaMarginEl.className = `kpi-delta ${blendedMargin >= 0 ? 'positive' : 'negative'}`;
  }

  const totalOrdersEl = document.getElementById('metric-total-orders');
  if (totalOrdersEl) totalOrdersEl.textContent = uniqueOrderIds.size.toLocaleString();

  const lossOrdersEl = document.getElementById('metric-loss-orders');
  if (lossOrdersEl) lossOrdersEl.textContent = `${lossCount.toLocaleString()} (${lossPct.toFixed(1)}%)`;

  // 2. Waterfall Components
  const origListPrice = grossSales + discountBleed;
  const estCogs = grossSales - netProfit;
  const waterfallData = {
    gross_list_price: round2(origListPrice),
    discount_applied: round2(-discountBleed),
    net_sales: round2(grossSales),
    cost_of_goods: round2(-estCogs),
    net_profit: round2(netProfit)
  };
  ChartEngine.renderWaterfallChart('chart-waterfall', waterfallData);

  // 3. Monthly Trend
  const monthlyMap = {};
  records.forEach(r => {
    if (!monthlyMap[r.ym]) {
      monthlyMap[r.ym] = { month: r.ym, sales: 0, profit: 0 };
    }
    monthlyMap[r.ym].sales += r.sales;
    monthlyMap[r.ym].profit += r.profit;
  });
  const monthlyTrend = Object.values(monthlyMap)
    .sort((a, b) => a.month.localeCompare(b.month))
    .map(m => ({
      month: m.month,
      sales: round2(m.sales),
      profit: round2(m.profit),
      margin_pct: m.sales > 0 ? round2((m.profit / m.sales) * 100) : 0
    }));
  ChartEngine.renderDualAxisTrend('chart-monthly-trend', monthlyTrend);

  // 4. Geographic State Cartogram Heatmap
  const stateAgg = {};
  dashboardData.executive.states.forEach(s => {
    stateAgg[s.state] = {
      state: s.state,
      code: s.code,
      region: s.region,
      grid_row: s.grid_row,
      grid_col: s.grid_col,
      sales: 0,
      profit: 0,
      bleed: 0,
      avg_discount: 0,
      alert_count: 0
    };
  });
  records.forEach(r => {
    if (stateAgg[r.st]) {
      stateAgg[r.st].sales += r.sales;
      stateAgg[r.st].profit += r.profit;
      stateAgg[r.st].bleed += r.bleed;
      if (r.priority > 0) stateAgg[r.st].alert_count++;
    }
  });
  const filteredStates = Object.values(stateAgg).map(s => ({
    ...s,
    sales: round2(s.sales),
    profit: round2(s.profit),
    discount_bleed: round2(s.bleed),
    margin_pct: s.sales > 0 ? round2((s.profit / s.sales) * 100) : 0
  }));
  populateStateCartogram(filteredStates, activeStateMetric);

  // 5. Category & Sub-Category Diagnostics
  const subcatAgg = {};
  records.forEach(r => {
    if (!subcatAgg[r.sc]) {
      subcatAgg[r.sc] = {
        sub_category: r.sc,
        category: r.cat,
        sales: 0,
        profit: 0,
        bleed: 0,
        discSum: 0,
        count: 0,
        regional_matrix: { West: null, Central: null, East: null, South: null }
      };
    }
    const sc = subcatAgg[r.sc];
    sc.sales += r.sales;
    sc.profit += r.profit;
    sc.bleed += r.bleed;
    sc.discSum += r.disc;
    sc.count += 1;

    // Regional grouping for Visual 7
    if (!sc.regional_matrix[r.reg]) {
      sc.regional_matrix[r.reg] = { sales: 0, profit: 0, discSum: 0, count: 0 };
    }
    sc.regional_matrix[r.reg].sales += r.sales;
    sc.regional_matrix[r.reg].profit += r.profit;
    sc.regional_matrix[r.reg].discSum += r.disc;
    sc.regional_matrix[r.reg].count += 1;
  });

  const filteredSubcats = Object.values(subcatAgg).map(sc => {
    const avgDisc = sc.count > 0 ? (sc.discSum / sc.count) * 100 : 0;
    const mrg = sc.sales > 0 ? (sc.profit / sc.sales) * 100 : 0;
    
    let quadrant = "STAR (Low Disc, High Margin)";
    if (avgDisc >= 20 && mrg >= 0) quadrant = "MONITOR (High Disc, Profitable)";
    else if (avgDisc < 20 && mrg < 0) quadrant = "INVESTIGATE (Low Disc, Loss)";
    else if (avgDisc >= 20 && mrg < 0) quadrant = "DANGER ZONE (High Disc + Margin Bleed)";

    const formattedRegions = {};
    ['West', 'Central', 'East', 'South'].forEach(reg => {
      const regObj = sc.regional_matrix[reg];
      if (regObj && regObj.count > 0) {
        formattedRegions[reg] = {
          sales: round2(regObj.sales),
          profit: round2(regObj.profit),
          margin_pct: regObj.sales > 0 ? round2((regObj.profit / regObj.sales) * 100) : 0,
          avg_discount: round2((regObj.discSum / regObj.count) * 100)
        };
      }
    });

    return {
      sub_category: sc.sub_category,
      category: sc.category,
      sales: round2(sc.sales),
      profit: round2(sc.profit),
      margin_pct: round2(mrg),
      avg_discount_pct: round2(avgDisc),
      discount_bleed: round2(sc.bleed),
      quadrant: quadrant,
      regional_matrix: formattedRegions
    };
  });

  ChartEngine.renderCategoryRankingChart('chart-category-ranking', filteredSubcats);
  ChartEngine.renderPricingQuadrantScatter('chart-pricing-quadrant', filteredSubcats);
  populateSubcatRegionHeatmap(filteredSubcats, activeSubcatMetric);

  // 6. Frontline Operations & Queue
  const alertRecords = records.filter(r => r.priority > 0);
  let freezeCount = 0;
  let auditCount = 0;
  let restockCount = 0;
  let revAtRisk = 0;

  alertRecords.forEach(a => {
    if (a.action === 'FREEZE_DISCOUNT') freezeCount++;
    else if (a.action === 'AUDIT_FREIGHT') auditCount++;
    else if (a.action === 'URGENT_RESTOCK') restockCount++;
    revAtRisk += a.sales;
  });

  document.getElementById('op-kpi-freeze').textContent = freezeCount.toLocaleString();
  document.getElementById('op-kpi-audit').textContent = auditCount.toLocaleString();
  document.getElementById('op-kpi-restock').textContent = restockCount.toLocaleString();
  document.getElementById('op-kpi-revenue-risk').textContent = formatCurrency(revAtRisk);

  const navAlertBadge = document.getElementById('nav-alert-count');
  if (navAlertBadge) navAlertBadge.textContent = alertRecords.length.toLocaleString();

  // Fulfillment Lag Distribution
  const lagBins = [
    { bin: "0-1 Days (Optimal)", count: 0 },
    { bin: "2-3 Days (Target)", count: 0 },
    { bin: "4-5 Days (Acceptable)", count: 0 },
    { bin: "6-7 Days (At Risk)", count: 0 },
    { bin: "8+ Days (SLA Breach)", count: 0 }
  ];
  records.forEach(r => {
    if (r.ship_d <= 1) lagBins[0].count++;
    else if (r.ship_d <= 3) lagBins[1].count++;
    else if (r.ship_d <= 5) lagBins[2].count++;
    else if (r.ship_d <= 7) lagBins[3].count++;
    else lagBins[4].count++;
  });
  const lagHistogram = lagBins.map(b => ({
    bin: b.bin,
    count: b.count,
    pct: totalRecords > 0 ? round2((b.count / totalRecords) * 100) : 0
  }));
  ChartEngine.renderFulfillmentHistogram('chart-fulfillment-lag', lagHistogram);

  // Fulfillment Delay Matrix (Region x Ship Mode)
  const regShipAgg = {};
  ['West', 'Central', 'East', 'South'].forEach(rg => {
    regShipAgg[rg] = {
      region: rg,
      modes: {
        'Same Day': { sumDays: 0, count: 0, breaches: 0 },
        'First Class': { sumDays: 0, count: 0, breaches: 0 },
        'Second Class': { sumDays: 0, count: 0, breaches: 0 },
        'Standard Class': { sumDays: 0, count: 0, breaches: 0 }
      }
    };
  });
  records.forEach(r => {
    if (regShipAgg[r.reg] && regShipAgg[r.reg].modes[r.sm]) {
      const m = regShipAgg[r.reg].modes[r.sm];
      m.sumDays += r.ship_d;
      m.count += 1;
      if (r.ship_d > 5) m.breaches += 1;
    }
  });
  const heatmapMatrix = Object.values(regShipAgg).map(rg => {
    const row = { region: rg.region, modes: {} };
    Object.keys(rg.modes).forEach(sm => {
      const item = rg.modes[sm];
      row.modes[sm] = {
        avg_days: item.count > 0 ? round2(item.sumDays / item.count) : 0,
        breaches: item.breaches,
        breach_rate: item.count > 0 ? round2((item.breaches / item.count) * 100) : 0
      };
    });
    return row;
  });
  populateHeatmap(heatmapMatrix, ['Same Day', 'First Class', 'Second Class', 'Standard Class']);

  // Frontline Queue Table
  populateAlertQueueTable(alertRecords);
}

// ── Active Filter Chips Renderer ──────────────────────────────────────────
function renderActiveFilterChips() {
  const container = document.getElementById('active-filter-chips');
  if (!container) return;

  const activeChips = [];
  if (currentFilters.year !== 'ALL') activeChips.push({ key: 'year', label: `Year: FY ${currentFilters.year}` });
  if (currentFilters.category !== 'ALL') activeChips.push({ key: 'category', label: `Category: ${currentFilters.category}` });
  if (currentFilters.region !== 'ALL') activeChips.push({ key: 'region', label: `Region: ${currentFilters.region}` });
  if (currentFilters.shipMode !== 'ALL') activeChips.push({ key: 'shipMode', label: `Ship Mode: ${currentFilters.shipMode}` });
  if (currentFilters.priority !== 'ALL') {
    const pLabel = currentFilters.priority === 'ALERT_ONLY' ? 'Active Alerts' : `Priority ${currentFilters.priority}`;
    activeChips.push({ key: 'priority', label: `Risk: ${pLabel}` });
  }
  if (currentFilters.actionCode !== 'ALL') activeChips.push({ key: 'actionCode', label: `Action: ${currentFilters.actionCode.replace('_', ' ')}` });
  if (currentFilters.search) activeChips.push({ key: 'search', label: `Search: "${currentFilters.search}"` });

  if (activeChips.length === 0) {
    container.style.display = 'none';
    container.innerHTML = '';
    return;
  }

  container.style.display = 'flex';
  container.innerHTML = `
    <span style="font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); font-weight: 700; margin-right: 4px;">Active Filters:</span>
    ${activeChips.map(c => `
      <div class="filter-chip">
        <span>${c.label}</span>
        <span class="chip-remove" onclick="removeFilter('${c.key}')" title="Remove filter">&times;</span>
      </div>
    `).join('')}
  `;
}

function removeFilter(key) {
  if (key === 'search') {
    currentFilters.search = '';
    const searchInput = document.getElementById('filter-search');
    if (searchInput) searchInput.value = '';
  } else {
    currentFilters[key] = 'ALL';
    const selectElem = document.getElementById(`filter-${key === 'actionCode' ? 'action' : key.toLowerCase()}`);
    if (selectElem) selectElem.value = 'ALL';
  }
  recalculateAndRenderDashboard();
}

function resetAllFilters() {
  currentFilters = {
    year: 'ALL',
    category: 'ALL',
    region: 'ALL',
    shipMode: 'ALL',
    priority: 'ALL',
    actionCode: 'ALL',
    search: ''
  };

  ['year', 'category', 'region', 'shipmode', 'priority', 'action'].forEach(id => {
    const el = document.getElementById(`filter-${id}`);
    if (el) el.value = 'ALL';
  });

  const searchInput = document.getElementById('filter-search');
  if (searchInput) searchInput.value = '';

  recalculateAndRenderDashboard();
  showNotification('All filters reset to defaults', 'info');
}

// ── Setup Filter Listeners ────────────────────────────────────────────────
function setupFilterListeners() {
  const mapping = [
    { id: 'filter-year', key: 'year' },
    { id: 'filter-category', key: 'category' },
    { id: 'filter-region', key: 'region' },
    { id: 'filter-shipmode', key: 'shipMode' },
    { id: 'filter-priority', key: 'priority' },
    { id: 'filter-action', key: 'actionCode' }
  ];

  mapping.forEach(m => {
    const el = document.getElementById(m.id);
    if (el) {
      el.addEventListener('change', (e) => {
        currentFilters[m.key] = e.target.value;
        recalculateAndRenderDashboard();
      });
    }
  });

  const searchInput = document.getElementById('filter-search');
  if (searchInput) {
    let debounceTimer;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        currentFilters.search = e.target.value.trim();
        recalculateAndRenderDashboard();
      }, 200);
    });
  }

  const resetBtn = document.getElementById('btn-reset-filters');
  if (resetBtn) {
    resetBtn.addEventListener('click', resetAllFilters);
  }

  const exportBtn = document.getElementById('btn-export-alerts');
  if (exportBtn) {
    exportBtn.addEventListener('click', exportFilteredAlertsToCSV);
  }

  // State Cartogram Heatmap Metric Toggles
  const stateToggles = document.querySelectorAll('#state-heatmap-toggles .metric-toggle-btn');
  stateToggles.forEach(btn => {
    btn.addEventListener('click', () => {
      stateToggles.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeStateMetric = btn.dataset.metric;
      recalculateAndRenderDashboard();
    });
  });

  // Sub-Category Region Heatmap Metric Toggles
  const subcatToggles = document.querySelectorAll('#subcat-heatmap-toggles .metric-toggle-btn');
  subcatToggles.forEach(btn => {
    btn.addEventListener('click', () => {
      subcatToggles.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeSubcatMetric = btn.dataset.metric;
      recalculateAndRenderDashboard();
    });
  });
}

// ── Visual 3: Geographic State Cartogram Heatmap ─────────────────────────
function populateStateCartogram(states, metric) {
  const container = document.getElementById('state-cartogram-container');
  if (!container || !states) return;

  container.innerHTML = states.map(s => {
    let valStr = '';
    let bgColor = '';

    if (metric === 'margin_pct') {
      valStr = (s.margin_pct >= 0 ? '+' : '') + s.margin_pct.toFixed(0) + '%';
      if (s.sales === 0) bgColor = 'rgba(255, 255, 255, 0.03)';
      else if (s.margin_pct < -15) bgColor = 'rgba(239, 68, 68, 0.85)';
      else if (s.margin_pct < 0) bgColor = 'rgba(248, 113, 113, 0.65)';
      else if (s.margin_pct < 8) bgColor = 'rgba(245, 158, 11, 0.65)';
      else if (s.margin_pct < 15) bgColor = 'rgba(52, 211, 153, 0.65)';
      else bgColor = 'rgba(16, 185, 129, 0.85)';
    } else if (metric === 'discount_bleed') {
      valStr = '$' + (s.discount_bleed >= 1000 ? (s.discount_bleed / 1000).toFixed(0) + 'k' : s.discount_bleed.toFixed(0));
      bgColor = s.discount_bleed > 50000 ? 'rgba(239, 68, 68, 0.8)' : s.discount_bleed > 15000 ? 'rgba(245, 158, 11, 0.65)' : 'rgba(59, 130, 246, 0.45)';
    } else if (metric === 'profit') {
      valStr = (s.profit >= 0 ? '$' : '-$') + (Math.abs(s.profit) >= 1000 ? (Math.abs(s.profit) / 1000).toFixed(0) + 'k' : Math.abs(s.profit).toFixed(0));
      bgColor = s.profit < 0 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(16, 185, 129, 0.75)';
    } else if (metric === 'alert_count') {
      valStr = s.alert_count + ' ⚠️';
      bgColor = s.alert_count > 30 ? 'rgba(239, 68, 68, 0.8)' : s.alert_count > 10 ? 'rgba(245, 158, 11, 0.65)' : 'rgba(59, 130, 246, 0.4)';
    }

    const gridStyle = `grid-row: ${s.grid_row + 1}; grid-column: ${s.grid_col + 1}; background-color: ${bgColor};`;

    return `
      <div class="state-tile" style="${gridStyle}" title="${s.state} (${s.region})\nSales: $${s.sales.toLocaleString()}\nProfit: $${s.profit.toLocaleString()}\nMargin: ${s.margin_pct}%\nAlerts: ${s.alert_count}" onclick="filterByState('${s.state}')">
        <span class="state-code">${s.code}</span>
        <span class="state-val">${valStr}</span>
      </div>
    `;
  }).join('');
}

function filterByState(stateName) {
  currentFilters.search = stateName;
  const searchInput = document.getElementById('filter-search');
  if (searchInput) searchInput.value = stateName;
  recalculateAndRenderDashboard();
  showNotification(`Filtered to state: ${stateName}`, 'info');
}

// ── Visual 7: Sub-Category x Region Cross-Dimensional Heatmap ────────────
function populateSubcatRegionHeatmap(subcategories, metric) {
  const container = document.getElementById('subcat-heatmap-container');
  if (!container || !subcategories) return;

  const regions = ['West', 'Central', 'East', 'South'];

  let html = `
    <table class="matrix-heatmap-table">
      <thead>
        <tr>
          <th style="text-align: left; width: 180px;">Sub-Category</th>
          <th>Category</th>
          ${regions.map(r => `<th>${r} Region</th>`).join('')}
          <th>Total / Blended</th>
        </tr>
      </thead>
      <tbody>
  `;

  subcategories.forEach(sc => {
    html += `
      <tr>
        <td class="subcat-label-cell" style="font-weight: 700;">${sc.sub_category}</td>
        <td style="color: var(--text-secondary); font-size: 0.75rem;">${sc.category}</td>
    `;

    regions.forEach(reg => {
      const regData = sc.regional_matrix ? sc.regional_matrix[reg] : null;
      let displayVal = '-';
      let bgColor = 'rgba(255, 255, 255, 0.03)';
      let textColor = 'var(--text-main)';

      if (regData) {
        if (metric === 'margin_pct') {
          const m = regData.margin_pct;
          displayVal = (m >= 0 ? '+' : '') + m.toFixed(1) + '%';
          if (m < -15) { bgColor = 'rgba(239, 68, 68, 0.75)'; textColor = '#FFF'; }
          else if (m < 0) { bgColor = 'rgba(248, 113, 113, 0.5)'; textColor = '#FFF'; }
          else if (m < 8) { bgColor = 'rgba(245, 158, 11, 0.5)'; textColor = '#FFF'; }
          else if (m < 15) { bgColor = 'rgba(52, 211, 153, 0.45)'; textColor = '#FFF'; }
          else { bgColor = 'rgba(16, 185, 129, 0.75)'; textColor = '#FFF'; }
        } else if (metric === 'profit') {
          const p = regData.profit;
          displayVal = (p >= 0 ? '$' : '-$') + (Math.abs(p) >= 1000 ? (Math.abs(p) / 1000).toFixed(0) + 'k' : Math.abs(p).toFixed(0));
          bgColor = p < 0 ? 'rgba(239, 68, 68, 0.65)' : 'rgba(16, 185, 129, 0.65)';
        } else if (metric === 'sales') {
          displayVal = '$' + (regData.sales >= 1000 ? (regData.sales / 1000).toFixed(0) + 'k' : regData.sales.toFixed(0));
          bgColor = 'rgba(59, 130, 246, 0.4)';
        } else if (metric === 'avg_discount') {
          displayVal = regData.avg_discount.toFixed(1) + '%';
          bgColor = regData.avg_discount > 25 ? 'rgba(239, 68, 68, 0.65)' : regData.avg_discount > 15 ? 'rgba(245, 158, 11, 0.5)' : 'rgba(16, 185, 129, 0.4)';
        }
      }

      html += `<td style="background: ${bgColor}; color: ${textColor};">${displayVal}</td>`;
    });

    let totalVal = '-';
    let totalBg = 'rgba(255, 255, 255, 0.05)';
    if (metric === 'margin_pct') {
      totalVal = (sc.margin_pct >= 0 ? '+' : '') + sc.margin_pct.toFixed(1) + '%';
      totalBg = sc.margin_pct < 0 ? 'rgba(239, 68, 68, 0.65)' : 'rgba(16, 185, 129, 0.65)';
    } else if (metric === 'profit') {
      totalVal = (sc.profit >= 0 ? '$' : '-$') + (Math.abs(sc.profit) >= 1000 ? (Math.abs(sc.profit) / 1000).toFixed(0) + 'k' : Math.abs(sc.profit).toFixed(0));
      totalBg = sc.profit < 0 ? 'rgba(239, 68, 68, 0.65)' : 'rgba(16, 185, 129, 0.65)';
    } else if (metric === 'sales') {
      totalVal = '$' + (sc.sales >= 1000 ? (sc.sales / 1000).toFixed(0) + 'k' : sc.sales.toFixed(0));
    } else if (metric === 'avg_discount') {
      totalVal = sc.avg_discount_pct.toFixed(1) + '%';
    }

    html += `<td style="background: ${totalBg}; font-weight: 700;">${totalVal}</td></tr>`;
  });

  html += `</tbody></table>`;
  container.innerHTML = html;
}

// ── Visual 8: Regional Bottleneck Heatmap ─────────────────────────────────
function populateHeatmap(matrix, shipModes) {
  const container = document.getElementById('heatmap-container');
  if (!container || !matrix) return;

  let html = `
    <table class="heatmap-table">
      <thead>
        <tr>
          <th style="text-align: left;">Region</th>
          ${shipModes.map(m => `<th>${m}</th>`).join('')}
        </tr>
      </thead>
      <tbody>
  `;

  matrix.forEach(row => {
    html += `<tr><td class="row-header">${row.region}</td>`;
    shipModes.forEach(sm => {
      const cell = row.modes[sm] || { avg_days: 0, breach_rate: 0 };
      const days = cell.avg_days;
      let colorClass = 'cell-optimal';
      if (days > 6) colorClass = 'cell-breach';
      else if (days > 5) colorClass = 'cell-risk';
      else if (days > 4) colorClass = 'cell-monitor';
      else if (days > 2) colorClass = 'cell-acceptable';

      html += `
        <td class="${colorClass}" title="${row.region} ${sm}: ${days} avg days | SLA Breaches: ${cell.breach_rate}%">
          ${days.toFixed(1)}d
          <div style="font-size: 0.65rem; opacity: 0.85; font-weight: normal;">${cell.breach_rate > 0 ? cell.breach_rate + '% breach' : 'Within SLA'}</div>
        </td>
      `;
    });
    html += `</tr>`;
  });

  html += `</tbody></table>`;
  container.innerHTML = html;
}

// ── Frontline Queue Table ─────────────────────────────────────────────────
function populateAlertQueueTable(alerts) {
  const tbody = document.getElementById('alert-queue-tbody');
  const countBadge = document.getElementById('queue-count-badge');
  if (!tbody) return;

  if (countBadge) {
    countBadge.textContent = `Showing ${alerts.length.toLocaleString()} active alerts`;
  }

  if (!alerts || alerts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" style="text-align:center; padding: 30px; color: var(--text-muted);">No alerts matching current filters</td></tr>`;
    return;
  }

  // Display top 100 alerts
  const displayAlerts = alerts.slice(0, 100);

  tbody.innerHTML = displayAlerts.map(a => {
    const isMultiRule = a.rules && a.rules.length >= 2;
    let badgeClass = 'badge-freeze';
    if (a.action === 'AUDIT_FREIGHT') badgeClass = 'badge-audit';
    else if (a.action === 'URGENT_RESTOCK') badgeClass = 'badge-restock';

    const profitColor = a.profit < 0 ? 'var(--rose-400)' : 'var(--teal-400)';

    return `
      <tr class="${isMultiRule ? 'multi-rule-row' : ''}" onclick="openOrderModal('${a.id}')">
        <td><span class="priority-pill priority-${a.priority}">${a.priority}</span></td>
        <td style="font-family: var(--font-mono); font-weight: 600;">${a.id}</td>
        <td><span class="action-badge ${badgeClass}">${a.action.replace('_', ' ')}</span></td>
        <td>${a.cat}</td>
        <td>${a.sc}</td>
        <td>${a.reg}</td>
        <td style="font-weight: 600;">$${a.sales.toLocaleString()}</td>
        <td style="font-weight: 600; color: ${profitColor};">$${a.profit.toLocaleString()}</td>
        <td style="color: ${a.mrg < 0 ? 'var(--rose-400)' : 'var(--text-main)'};">${a.mrg}%</td>
        <td><span style="font-size: 0.75rem; color: var(--text-secondary);">${a.owner} (${a.sla}h)</span></td>
      </tr>
    `;
  }).join('');
}

// ── Order Modal Drawer ────────────────────────────────────────────────────
function setupModal() {
  const overlay = document.getElementById('order-modal');
  const closeBtn = document.getElementById('modal-close-btn');
  const ackBtn = document.getElementById('modal-ack-btn');

  if (closeBtn) {
    closeBtn.addEventListener('click', () => {
      overlay.classList.remove('open');
    });
  }
  if (overlay) {
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  }
  if (ackBtn) {
    ackBtn.addEventListener('click', () => {
      showNotification('Alert marked as Acknowledged. Action task routed to owner.', 'success');
      overlay.classList.remove('open');
    });
  }
}

function openOrderModal(orderId) {
  if (!dashboardData || !dashboardData.records) return;
  const item = dashboardData.records.find(o => o.id === orderId);
  if (!item) return;

  document.getElementById('modal-order-id').textContent = item.id;
  document.getElementById('modal-product').textContent = item.prod || `${item.cat} / ${item.sc}`;
  document.getElementById('modal-sales').textContent = `$${item.sales.toLocaleString()}`;
  document.getElementById('modal-profit').textContent = `$${item.profit.toLocaleString()}`;
  document.getElementById('modal-margin').textContent = `${item.mrg}%`;
  document.getElementById('modal-discount').textContent = `${(item.disc * 100).toFixed(0)}%`;
  document.getElementById('modal-action').textContent = item.action.replace('_', ' ');
  document.getElementById('modal-owner').textContent = `${item.owner} (SLA: ${item.sla} hrs)`;
  document.getElementById('modal-rationale').textContent = item.rationale || 'High risk transaction identified by operational rules engine.';

  const rulesList = document.getElementById('modal-rules-list');
  if (rulesList && item.rules) {
    rulesList.innerHTML = item.rules.map(r => `
      <span style="display:inline-block; font-size: 0.72rem; padding: 2px 8px; border-radius: 4px; background: rgba(239, 68, 68, 0.15); color: #FCA5A5; border: 1px solid rgba(239, 68, 68, 0.3); margin-right: 6px; margin-bottom: 4px;">
        ${r}
      </span>
    `).join('');
  }

  document.getElementById('order-modal').classList.add('open');
}

// ── SQL Lab Reference Queries ─────────────────────────────────────────────
function populateSqlQueries(queryData) {
  const container = document.getElementById('sql-queries-container');
  if (!container || !queryData) return;

  const queries = [
    {
      id: 'q1',
      title: 'Query 1: High-Volume Margin Bleed Ranking',
      desc: 'Isolates loss-making sub-categories and ranks products by absolute profit destruction using CTEs and RANK().',
      key: 'q1_high-volume_margin_bleed__sub-category'
    },
    {
      id: 'q2',
      title: 'Query 2: Last-Mile Fulfillment Latency & Carrier Chokepoints',
      desc: 'Calculates regional shipping delays and SLA breach rates per carrier ship mode via AVG() OVER PARTITION BY.',
      key: 'q2_last-mile_fulfillment_latency__region__'
    },
    {
      id: 'q3',
      title: 'Query 3: Order Decile & Profitability Distribution (NTILE)',
      desc: 'Segments transactions into 10 deciles (D1 to D10) proving that bottom 30% destroys more profit than top 10% generates.',
      key: 'q3_order_decile___profitability_distributio'
    },
    {
      id: 'q4',
      title: 'Query 4: YoY Cohort Summary & Margin Drift via LAG()',
      desc: 'Tracks yearly revenue growth versus net margin point compression across all categories.',
      key: 'q4_yoy_cohort_summary__revenue_vs._net_mar'
    }
  ];

  let html = '';
  queries.forEach(q => {
    const res = queryData[q.key] || { rows: [], columns: [], total_rows: 0 };
    html += `
      <div class="sql-accordion-item">
        <div class="sql-header">
          <div class="sql-title-text">
            <h4>${q.title}</h4>
            <p>${q.desc}</p>
          </div>
          <span style="font-size: 0.75rem; color: var(--cyan-400); font-weight: 600;">${res.total_rows} Records Output</span>
        </div>
        <div class="query-preview-table">
          <div class="data-table-wrapper" style="max-height: 260px;">
            <table class="data-table">
              <thead>
                <tr>${res.columns.slice(0, 8).map(c => `<th>${c}</th>`).join('')}</tr>
              </thead>
              <tbody>
                ${res.rows.slice(0, 8).map(row => `
                  <tr>
                    ${res.columns.slice(0, 8).map(col => `<td>${formatCellValue(row[col])}</td>`).join('')}
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

// ── Export CSV ────────────────────────────────────────────────────────────
function exportFilteredAlertsToCSV() {
  if (!dashboardData || !dashboardData.records) return;
  const filtered = filterRecords(dashboardData.records).filter(r => r.priority > 0);
  if (filtered.length === 0) {
    showNotification('No alert rows to export under current filters', 'error');
    return;
  }

  const headers = ['order_id', 'order_date', 'category', 'sub_category', 'region', 'state', 'sales', 'profit', 'margin_pct', 'action_code', 'priority', 'owner'];
  const csvRows = [headers.join(',')];

  filtered.forEach(r => {
    const row = [r.id, r.dt, r.cat, r.sc, r.reg, r.st, r.sales, r.profit, r.mrg, r.action, r.priority, r.owner];
    csvRows.push(row.map(v => typeof v === 'string' ? `"${v.replace(/"/g, '""')}"` : v).join(','));
  });

  const blob = new Blob([csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `frontline_action_queue_filtered_${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
  showNotification(`Exported ${filtered.length} filtered alerts to CSV`, 'success');
}

// ── Helpers ───────────────────────────────────────────────────────────────
function formatCurrency(val) {
  if (val === null || val === undefined) return '$0';
  const num = Number(val);
  if (Math.abs(num) >= 1000000) {
    return '$' + (num / 1000000).toFixed(2) + 'M';
  } else if (Math.abs(num) >= 1000) {
    return '$' + (num / 1000).toFixed(1) + 'K';
  }
  return '$' + num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCellValue(val) {
  if (val === null || val === undefined) return '-';
  if (typeof val === 'number') {
    return val.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  return String(val);
}

function round2(val) {
  return Math.round((Number(val) + Number.EPSILON) * 100) / 100;
}

function showNotification(msg, type = 'info') {
  const notif = document.createElement('div');
  notif.style.position = 'fixed';
  notif.style.bottom = '24px';
  notif.style.right = '24px';
  notif.style.padding = '12px 20px';
  notif.style.borderRadius = '8px';
  notif.style.background = type === 'error' ? '#EF4444' : '#10B981';
  notif.style.color = '#FFFFFF';
  notif.style.fontSize = '0.85rem';
  notif.style.fontWeight = '600';
  notif.style.boxShadow = '0 8px 24px rgba(0,0,0,0.5)';
  notif.style.zIndex = '999';
  notif.textContent = msg;
  document.body.appendChild(notif);
  setTimeout(() => notif.remove(), 3200);
}

function refreshActiveTabCharts() {
  recalculateAndRenderDashboard();
}
