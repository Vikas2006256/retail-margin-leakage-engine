/**
 * Retail Margin & Inventory Leakage — Chart Renderers
 * Built using Chart.js with customized modern dark mode styling
 */

const ChartEngine = {
  charts: {},

  // Common dark theme chart defaults
  commonOptions: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        labels: {
          color: '#94A3B8',
          font: { family: "'Plus Jakarta Sans', sans-serif", size: 12 }
        }
      },
      tooltip: {
        backgroundColor: 'rgba(15, 23, 42, 0.95)',
        titleColor: '#F8FAFC',
        bodyColor: '#CBD5E1',
        borderColor: 'rgba(255, 255, 255, 0.12)',
        borderWidth: 1,
        padding: 12,
        cornerRadius: 8,
        titleFont: { family: "'Outfit', sans-serif", weight: 'bold', size: 13 },
        bodyFont: { family: "'Plus Jakarta Sans', sans-serif", size: 12 }
      }
    },
    scales: {
      x: {
        grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
        ticks: { color: '#64748B', font: { family: "'Plus Jakarta Sans', sans-serif", size: 11 } }
      },
      y: {
        grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
        ticks: { color: '#64748B', font: { family: "'Plus Jakarta Sans', sans-serif", size: 11 } }
      }
    }
  },

  destroy(id) {
    if (this.charts[id]) {
      this.charts[id].destroy();
      delete this.charts[id];
    }
  },

  // 1. Dual-Axis Revenue & Margin Trend (Page 1)
  renderDualAxisTrend(canvasId, monthlyTrend) {
    this.destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const labels = monthlyTrend.map(d => d.month);
    const salesData = monthlyTrend.map(d => d.sales);
    const marginData = monthlyTrend.map(d => d.margin_pct);

    this.charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          {
            type: 'bar',
            label: 'Gross Sales ($)',
            data: salesData,
            backgroundColor: 'rgba(59, 130, 246, 0.65)',
            borderColor: '#3B82F6',
            borderWidth: 1,
            borderRadius: 4,
            yAxisID: 'ySales',
            order: 2
          },
          {
            type: 'line',
            label: 'Blended Margin %',
            data: marginData,
            borderColor: '#F59E0B',
            backgroundColor: 'rgba(245, 158, 11, 0.1)',
            borderWidth: 2.5,
            pointBackgroundColor: '#F59E0B',
            pointRadius: 3,
            tension: 0.35,
            yAxisID: 'yMargin',
            order: 1
          }
        ]
      },
      options: {
        ...this.commonOptions,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: {
            grid: { display: false },
            ticks: {
              color: '#64748B',
              maxTicksLimit: 12,
              font: { size: 11 }
            }
          },
          ySales: {
            type: 'linear',
            position: 'left',
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: {
              color: '#94A3B8',
              callback: val => '$' + (val >= 1000 ? (val / 1000).toFixed(0) + 'k' : val)
            }
          },
          yMargin: {
            type: 'linear',
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: {
              color: '#F59E0B',
              callback: val => val.toFixed(0) + '%'
            }
          }
        }
      }
    });
  },

  // 2. Waterfall Profit Leakage Bridge Chart (Page 1)
  renderWaterfallChart(canvasId, waterfallData) {
    this.destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // Formatted steps
    const labels = [
      'Gross List Price',
      'Discount Applied',
      'Net Sales Revenue',
      'Cost of Goods',
      'Net Profit'
    ];

    const values = [
      waterfallData.gross_list_price,
      waterfallData.discount_applied,
      waterfallData.net_sales,
      waterfallData.cost_of_goods,
      waterfallData.net_profit
    ];

    const colors = [
      '#06B6D4', // Gross List - Cyan
      '#EF4444', // Discount Bleed - Red
      '#3B82F6', // Net Sales - Blue
      '#F97316', // COGS - Orange
      waterfallData.net_profit >= 0 ? '#10B981' : '#EF4444' // Net Profit - Teal/Red
    ];

    this.charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Amount ($)',
          data: values,
          backgroundColor: colors.map(c => c + 'CC'),
          borderColor: colors,
          borderWidth: 1.5,
          borderRadius: 6
        }]
      },
      options: {
        ...this.commonOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: item => ' $' + Math.abs(item.raw).toLocaleString(undefined, { minimumFractionDigits: 2 })
            }
          }
        },
        scales: {
          y: {
            ticks: {
              color: '#94A3B8',
              callback: val => '$' + (val / 1000000).toFixed(2) + 'M'
            }
          }
        }
      }
    });
  },

  // 3. Sub-Category Net Profit / Loss Leader Ranking (Page 2)
  renderCategoryRankingChart(canvasId, subcategories) {
    this.destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    // Sort ascending by profit (loss leaders at top)
    const sorted = [...subcategories].sort((a, b) => a.profit - b.profit);
    const labels = sorted.map(s => s.sub_category);
    const profits = sorted.map(s => s.profit);
    const colors = sorted.map(s => s.profit < 0 ? '#EF4444' : '#10B981');

    this.charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Net Profit ($)',
          data: profits,
          backgroundColor: colors.map(c => c + '99'),
          borderColor: colors,
          borderWidth: 1,
          borderRadius: 4
        }]
      },
      options: {
        ...this.commonOptions,
        indexAxis: 'y',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => ` Net Profit: $${ctx.raw.toLocaleString()} (Margin: ${sorted[ctx.dataIndex].margin_pct}%)`
            }
          }
        },
        scales: {
          x: {
            ticks: {
              color: '#94A3B8',
              callback: val => '$' + (val / 1000).toFixed(0) + 'k'
            }
          }
        }
      }
    });
  },

  // 4. Pricing Quadrant Bubble / Scatter Chart (Page 2)
  renderPricingQuadrantScatter(canvasId, subcategories) {
    this.destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const categoryColors = {
      'Furniture': '#F59E0B',
      'Technology': '#06B6D4',
      'Office Supplies': '#8B5CF6'
    };

    const datasets = ['Furniture', 'Technology', 'Office Supplies'].map(cat => {
      const items = subcategories.filter(s => s.category === cat);
      return {
        label: cat,
        data: items.map(s => ({
          x: s.avg_discount_pct,
          y: s.margin_pct,
          r: Math.max(Math.sqrt(s.sales) / 12, 6),
          subCategory: s.sub_category,
          sales: s.sales,
          profit: s.profit,
          quadrant: s.quadrant
        })),
        backgroundColor: (categoryColors[cat] || '#3B82F6') + '88',
        borderColor: categoryColors[cat] || '#3B82F6',
        borderWidth: 1.5
      };
    });

    this.charts[canvasId] = new Chart(ctx, {
      type: 'bubble',
      data: { datasets },
      options: {
        ...this.commonOptions,
        plugins: {
          tooltip: {
            callbacks: {
              title: items => items[0].raw.subCategory,
              label: item => [
                ` Category: ${item.dataset.label}`,
                ` Avg Discount: ${item.raw.x.toFixed(1)}%`,
                ` Margin: ${item.raw.y.toFixed(1)}%`,
                ` Revenue: $${item.raw.sales.toLocaleString()}`,
                ` Net Profit: $${item.raw.profit.toLocaleString()}`,
                ` Quadrant: ${item.raw.quadrant}`
              ]
            }
          }
        },
        scales: {
          x: {
            title: { display: true, text: 'Average Discount Rate (%)', color: '#94A3B8' },
            ticks: { callback: v => v + '%' }
          },
          y: {
            title: { display: true, text: 'Blended Profit Margin (%)', color: '#94A3B8' },
            ticks: { callback: v => v + '%' }
          }
        }
      }
    });
  },

  // 5. Fulfillment Lag Distribution Histogram (Page 3)
  renderFulfillmentHistogram(canvasId, lagHistogram) {
    this.destroy(canvasId);
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    const labels = lagHistogram.map(d => d.bin);
    const counts = lagHistogram.map(d => d.count);
    const pcts = lagHistogram.map(d => d.pct);

    const colors = [
      '#10B981', // Optimal
      '#84CC16', // Target
      '#F59E0B', // Acceptable
      '#F97316', // At Risk
      '#EF4444'  // Breach
    ];

    this.charts[canvasId] = new Chart(ctx, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          label: 'Order Count',
          data: counts,
          backgroundColor: colors.map(c => c + '99'),
          borderColor: colors,
          borderWidth: 1.5,
          borderRadius: 6
        }]
      },
      options: {
        ...this.commonOptions,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: item => ` ${item.raw.toLocaleString()} orders (${pcts[item.dataIndex]}% of volume)`
            }
          }
        },
        scales: {
          y: {
            ticks: {
              color: '#94A3B8',
              callback: val => val.toLocaleString()
            }
          }
        }
      }
    });
  }
};

window.ChartEngine = ChartEngine;
