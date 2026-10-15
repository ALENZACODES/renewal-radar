import {chartColors, trajectoryData, costData, rateData} from './chart-data.js';

const cad = value => new Intl.NumberFormat('en-CA', {style: 'currency', currency: 'CAD', maximumFractionDigits: 0}).format(value);
const compact = value => new Intl.NumberFormat('en-CA', {notation: 'compact', maximumFractionDigits: 1}).format(value);
function base({dark = false, reducedMotion = false} = {}) {
  const ink = dark ? '#ededed' : '#333333';
  return {
    animation: !reducedMotion, animationDuration: 300, color: chartColors,
    textStyle: {fontFamily: 'Inter', fontSize: 13, color: ink},
    backgroundColor: dark ? '#242424' : '#ffffff',
    aria: {enabled: true, decal: {show: true}},
    tooltip: {renderMode: 'richText', confine: true, textStyle: {fontFamily: 'Inter', fontSize: 12}},
    grid: {left: 12, right: 25, top: 40, bottom: 68, containLabel: true},
    xAxis: {axisLabel: {color: ink}, axisLine: {lineStyle: {color: '#777'}}},
    yAxis: {axisLabel: {color: ink}, splitLine: {lineStyle: {color: dark ? '#444' : '#e1e1e1'}}},
  };
}

export function trajectoryOption(analysis, mode = 'balance', settings = {}) {
  const lines = trajectoryData(analysis, mode);
  if (!lines.length) return null;
  const option = base(settings);
  return {...option,
    aria: {...option.aria, label: {description: mode === 'interest' ? 'Cumulative modelled interest by elapsed month.' : 'Remaining modelled principal by elapsed month. Shorter quoted terms stop at their own term.'}},
    legend: {top: 0, type: 'scroll', textStyle: option.textStyle},
    tooltip: {...option.tooltip, trigger: 'axis', valueFormatter: cad},
    xAxis: {...option.xAxis, type: 'value', name: 'Month', min: 0, max: 'dataMax', minInterval: 1},
    yAxis: {...option.yAxis, type: 'value', axisLabel: {...option.yAxis.axisLabel, formatter: compact}},
    dataZoom: [{type: 'slider', bottom: 5, height: 20, showDetail: false}, {type: 'inside', zoomOnMouseWheel: 'ctrl', moveOnMouseMove: true}],
    series: lines.map(line => ({name: line.name, type: 'line', data: line.points,
      showSymbol: false, smooth: false, lineStyle: {width: 3, type: line.short ? 'dashed' : 'solid'}, emphasis: {focus: 'series'}})),
  };
}

export function costOption(analysis, settings = {}) {
  const rows = costData(analysis);
  if (!rows.length) return null;
  const option = base(settings);
  return {...option,
    aria: {...option.aria, label: {description: 'Comparable borrowing costs split into interest and net fees. A negative fee segment is a fee credit.'}},
    grid: {...option.grid, left: 12, bottom: 35},
    legend: {top: 0, data: ['Interest', 'Net fees / credits'], textStyle: option.textStyle},
    tooltip: {...option.tooltip, trigger: 'axis', axisPointer: {type: 'shadow'}, valueFormatter: cad},
    xAxis: {...option.xAxis, type: 'value', axisLabel: {...option.xAxis.axisLabel, formatter: compact}},
    yAxis: {...option.yAxis, type: 'category', inverse: true, data: rows.map(row => row.name),
      axisLabel: {...option.yAxis.axisLabel, width: 115, overflow: 'truncate'}, splitLine: {show: false}},
    series: [
      {name: 'Interest', type: 'bar', stack: 'cost', data: rows.map(row => row.interest), barMaxWidth: 34},
      {name: 'Net fees / credits', type: 'bar', stack: 'cost', data: rows.map(row => row.fees), barMaxWidth: 34},
    ],
  };
}

export function rateOption(market, settings = {}) {
  const rows = rateData(market);
  if (!rows.length) return null;
  const option = base(settings);
  return {...option,
    aria: {...option.aria, label: {description: 'Latest dated public observations. These different benchmarks are not personalized mortgage quotes or a forecast.'}},
    grid: {...option.grid, top: 15, right: 60, bottom: 35},
    tooltip: {...option.tooltip, trigger: 'axis', valueFormatter: value => `${Number(value).toFixed(2)}%`},
    xAxis: {...option.xAxis, type: 'value', min: 0, axisLabel: {...option.xAxis.axisLabel, formatter: '{value}%'}},
    yAxis: {...option.yAxis, type: 'category', inverse: true,
      data: rows.map(row => row.name), splitLine: {show: false}, axisLabel: {...option.yAxis.axisLabel, fontSize: 12}},
    series: [{name: 'Public benchmark', type: 'bar', data: rows.map(row => row.value),
      barWidth: 7, showBackground: true, backgroundStyle: {color: settings.dark ? '#333' : '#f2f2f2'},
      itemStyle: {color: params => chartColors[params.dataIndex % chartColors.length]},
      label: {show: true, position: 'right', formatter: params => `${params.value.toFixed(2)}%`, color: option.textStyle.color, fontFamily: 'Inter'},
    }],
  };
}
