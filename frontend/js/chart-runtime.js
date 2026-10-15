import {trajectoryOption, costOption, rateOption} from './chart-options.js';
import {penaltyCurveOption} from './penalty-studio.js';

export function mountMortgageCharts(root, getWorkspace, {
  library = globalThis.echarts, Observer = globalThis.ResizeObserver,
  reducedMotion = () => globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true,
  download = (url, filename) => {
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = filename; anchor.click();
  },
} = {}) {
  const entries = new Map();
  const modes = new Map();
  let observer = null;
  function settings() {return {dark: getWorkspace().theme === 'dark', reducedMotion: reducedMotion()};}
  function option(kind, mode) {
    const workspace = getWorkspace();
    if (kind === 'trajectory') return trajectoryOption(workspace.analysis, mode, settings());
    if (kind === 'cost') return costOption(workspace.analysis, settings());
    if (kind === 'rates') return rateOption(workspace.market, settings());
    if (kind === 'penalty') return penaltyCurveOption(workspace.penaltyTimeline, settings(), workspace.penaltyMonth || 0);
    return null;
  }
  function disposeCharts() {
    observer?.disconnect(); observer = null;
    for (const entry of entries.values()) entry.chart.dispose();
    entries.clear();
  }
  function refresh() {
    disposeCharts();
    if (Observer) observer = new Observer(() => {for (const entry of entries.values()) entry.chart.resize();});
    for (const element of root.querySelectorAll('[data-chart]')) {
      const {chart: kind, chartId: id} = element.dataset;
      const mode = modes.get(id) || 'balance';
      const config = option(kind, mode);
      if (!library || !config) {element.textContent = 'Chart unavailable. See chart data.'; continue;}
      const chart = library.init(element, null, {renderer: 'svg'});
      chart.setOption(config);
      entries.set(id, {chart, element, kind});
      observer?.observe(element);
      for (const button of root.querySelectorAll('[data-chart-mode]')) {
        if (button.dataset.chartTarget === id) button.setAttribute('aria-pressed', String(button.dataset.chartMode === mode));
      }
    }
  }
  function click(event) {
    const modeButton = event.target.closest('[data-chart-mode]');
    if (modeButton && root.contains(modeButton)) {
      const {chartMode: mode, chartTarget: id} = modeButton.dataset;
      if (!['balance', 'interest'].includes(mode)) return;
      const entry = entries.get(id);
      if (!entry) return;
      modes.set(id, mode);
      entry.chart.setOption(option(entry.kind, mode), true);
      for (const button of root.querySelectorAll('[data-chart-mode]')) {
        if (button.dataset.chartTarget === id) button.setAttribute('aria-pressed', String(button === modeButton));
      }
    }
    const exportButton = event.target.closest('[data-chart-download]');
    if (exportButton && root.contains(exportButton)) {
      const entry = entries.get(exportButton.dataset.chartDownload);
      if (entry) download(entry.chart.getDataURL({type: 'svg', backgroundColor: settings().dark ? '#242424' : '#fff'}), 'renewal-radar-chart.svg');
    }
  }
  root.addEventListener('click', click);
  return {refresh, dispose: () => {disposeCharts(); root.removeEventListener('click', click);}};
}
