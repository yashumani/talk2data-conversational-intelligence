import type { EChartsOption } from "echarts";

const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"];
const primary = "#55d6be";
const secondary = "#8b7cf6";
const accent = "#ffb86b";
const axis = { axisLine: { lineStyle: { color: "#68748a" } }, axisLabel: { color: "#aeb8ca" } };
const bubbleSize = (value: unknown) => Array.isArray(value) ? Number(value[2]) : 12;

function cartesian(series: EChartsOption["series"], horizontal = false): EChartsOption {
  return {
    animation: false,
    backgroundColor: "transparent",
    grid: { left: 44, right: 16, top: 20, bottom: 36 },
    tooltip: { trigger: "axis" },
    xAxis: horizontal ? { type: "value", ...axis } : { type: "category", data: months, ...axis },
    yAxis: horizontal ? { type: "category", data: months, ...axis } : { type: "value", ...axis },
    series,
  };
}

export function optionFor(kind: string): EChartsOption {
  const revenue = [42, 51, 48, 64, 71, 78];
  const plan = [38, 45, 52, 58, 63, 69];
  switch (kind) {
    case "bar": return cartesian([{ type: "bar", data: revenue, itemStyle: { color: primary } }]);
    case "grouped-bar": return cartesian([
      { name: "Actual", type: "bar", data: revenue, itemStyle: { color: primary } },
      { name: "Plan", type: "bar", data: plan, itemStyle: { color: secondary } },
    ]);
    case "stacked-bar": return cartesian([
      { name: "Digital", type: "bar", stack: "total", data: [21, 24, 25, 31, 36, 40], itemStyle: { color: primary } },
      { name: "Retail", type: "bar", stack: "total", data: [17, 21, 27, 27, 27, 29], itemStyle: { color: secondary } },
    ]);
    case "horizontal-bar": return cartesian([{ type: "bar", data: revenue, itemStyle: { color: primary } }], true);
    case "line": return cartesian([{ type: "line", data: revenue, smooth: true, lineStyle: { color: primary }, itemStyle: { color: primary } }]);
    case "multi-line": return cartesian([
      { name: "Actual", type: "line", data: revenue, lineStyle: { color: primary } },
      { name: "Plan", type: "line", data: plan, lineStyle: { color: secondary } },
    ]);
    case "area": return cartesian([{ type: "line", data: revenue, smooth: true, areaStyle: { color: primary, opacity: 0.35 }, lineStyle: { color: primary } }]);
    case "stacked-area": return cartesian([
      { name: "Digital", type: "line", stack: "total", areaStyle: {}, data: [21, 24, 25, 31, 36, 40], lineStyle: { color: primary } },
      { name: "Retail", type: "line", stack: "total", areaStyle: {}, data: [17, 21, 27, 27, 27, 29], lineStyle: { color: secondary } },
    ]);
    case "scatter": return cartesian([{ type: "scatter", data: [[1, 18], [2, 29], [3, 25], [4, 44], [5, 49], [6, 61]], itemStyle: { color: primary } }]);
    case "bubble": return cartesian([{ type: "scatter", data: [[1, 18, 9], [2, 29, 16], [3, 25, 12], [4, 44, 24], [5, 49, 20], [6, 61, 28]], symbolSize: bubbleSize, itemStyle: { color: secondary, opacity: 0.8 } }]);
    case "histogram": return cartesian([{ type: "bar", data: [3, 8, 17, 23, 15, 6], barCategoryGap: "4%", itemStyle: { color: accent } }]);
    case "boxplot": return cartesian([{ type: "boxplot", data: [[12, 20, 28, 36, 44], [18, 24, 31, 39, 48], [21, 27, 35, 43, 52], [25, 31, 38, 47, 58], [28, 35, 42, 51, 63], [31, 38, 46, 55, 68]], itemStyle: { color: secondary, borderColor: primary } }]);
    case "heatmap": return {
      animation: false, grid: { left: 58, right: 30, top: 20, bottom: 40 },
      xAxis: { type: "category", data: ["Mon", "Tue", "Wed", "Thu", "Fri"], ...axis },
      yAxis: { type: "category", data: ["North", "South", "East", "West"], ...axis },
      visualMap: { min: 0, max: 100, show: false, inRange: { color: ["#182035", primary] } },
      series: [{ type: "heatmap", data: Array.from({ length: 20 }, (_, index) => [index % 5, Math.floor(index / 5), (index * 17 + 23) % 100]) }],
    };
    case "pie": return { animation: false, tooltip: { trigger: "item" }, series: [{ type: "pie", radius: "68%", data: [{ value: 44, name: "Digital" }, { value: 31, name: "Retail" }, { value: 25, name: "Partner" }] }] };
    case "donut": return { animation: false, tooltip: { trigger: "item" }, series: [{ type: "pie", radius: ["42%", "70%"], data: [{ value: 44, name: "Digital" }, { value: 31, name: "Retail" }, { value: 25, name: "Partner" }] }] };
    default: throw new Error(`Unsupported accepted renderer: ${kind}`);
  }
}
