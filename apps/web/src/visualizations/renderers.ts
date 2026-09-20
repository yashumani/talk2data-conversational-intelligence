import type { EChartsOption } from "echarts";

const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"];
const primary = "#55d6be";
const secondary = "#8b7cf6";
const accent = "#ffb86b";
const axis = { axisLine: { lineStyle: { color: "#68748a" } }, axisLabel: { color: "#aeb8ca" } };
const bubbleSize = (value: unknown) => Array.isArray(value) ? Number(value[2]) : 12;
const numericAxis = { type: "value" as const, ...axis };
const ridgeLabel = (value: number) => ["", "North", "South", "East", "West"][value] ?? "";
const violinRenderItem = (_params: unknown, api: { value: (index: number) => number; coord: (value: number[]) => number[]; size: (value: number[]) => number[] }) => {
  const category = api.value(0);
  const values = [api.value(1), api.value(2), api.value(3), api.value(4), api.value(5)];
  const center = api.coord([category, values[2]])[0];
  const width = Math.min(api.size([1, 0])[0] * .32, 28);
  const profile = [0, .62, 1, .62, 0];
  const left = values.map((value, index) => [center - width * profile[index], api.coord([category, value])[1]]);
  const right = values.slice().reverse().map((value, index) => [center + width * profile[4 - index], api.coord([category, value])[1]]);
  return { type: "polygon", shape: { points: [...left, ...right] }, style: { fill: primary, opacity: .58, stroke: primary } };
};

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
    case "violin": return {
      animation: false,
      grid: { left: 48, right: 20, top: 20, bottom: 36 },
      xAxis: { type: "category", data: ["North", "South", "East", "West"], ...axis },
      yAxis: numericAxis,
      series: [{
        type: "custom",
        data: [[0, 18, 28, 36, 49, 62], [1, 12, 24, 33, 44, 58], [2, 20, 31, 41, 52, 69], [3, 16, 27, 38, 48, 64]],
        renderItem: violinRenderItem,
      }],
    } as EChartsOption;
    case "density": return {
      animation: false, grid: { left: 44, right: 16, top: 20, bottom: 36 }, tooltip: { trigger: "axis" },
      xAxis: numericAxis, yAxis: numericAxis,
      series: [{ type: "line", smooth: true, showSymbol: false, data: [[0, 0], [10, .08], [20, .32], [30, .72], [40, 1], [50, .76], [60, .38], [70, .12], [80, 0]], areaStyle: { color: primary, opacity: .3 }, lineStyle: { color: primary, width: 3 } }],
    };
    case "ridgeline": return {
      animation: false, grid: { left: 58, right: 16, top: 20, bottom: 36 },
      xAxis: numericAxis, yAxis: { type: "value", min: 0, max: 4.6, interval: 1, axisLabel: { color: "#aeb8ca", formatter: ridgeLabel }, axisLine: { lineStyle: { color: "#68748a" } } },
      series: [1, 2, 3, 4].map((offset, index) => ({ type: "line" as const, smooth: true, showSymbol: false, data: [[10, offset], [20, offset + .12], [30, offset + .42 - index * .03], [40, offset + .68], [50, offset + .4], [60, offset + .1], [70, offset]], areaStyle: { color: [primary, secondary, accent, "#6ca8ff"][index], opacity: .18 }, lineStyle: { color: [primary, secondary, accent, "#6ca8ff"][index], width: 2 } })),
    };
    case "beeswarm": return {
      animation: false, grid: { left: 58, right: 20, top: 20, bottom: 36 },
      xAxis: numericAxis, yAxis: { type: "category", data: ["North", "South", "East"], ...axis },
      series: [{ type: "scatter", symbolSize: 10, itemStyle: { color: primary, opacity: .78 }, data: Array.from({ length: 36 }, (_, index) => [18 + ((index * 17) % 55), index % 3 + ((index % 5) - 2) * .055]) }],
    };
    case "density-2d": return {
      animation: false, grid: { left: 44, right: 24, top: 20, bottom: 36 },
      xAxis: { type: "category", data: ["1", "2", "3", "4", "5", "6"], ...axis },
      yAxis: { type: "category", data: ["A", "B", "C", "D", "E"], ...axis },
      visualMap: { min: 0, max: 100, show: false, inRange: { color: ["#182035", "#315e68", primary, accent] } },
      series: [{ type: "heatmap", data: Array.from({ length: 30 }, (_, index) => [index % 6, Math.floor(index / 6), Math.max(4, 96 - Math.abs(index % 6 - 3) * 18 - Math.abs(Math.floor(index / 6) - 2) * 20)]) }],
    };
    case "correlogram": return {
      animation: false, grid: { left: 70, right: 24, top: 20, bottom: 48 },
      xAxis: { type: "category", data: ["Revenue", "Orders", "Margin", "Churn"], ...axis },
      yAxis: { type: "category", data: ["Revenue", "Orders", "Margin", "Churn"], ...axis },
      visualMap: { min: -1, max: 1, show: false, inRange: { color: ["#8b7cf6", "#182035", primary] } },
      series: [{ type: "heatmap", label: { show: true, color: "#f7f9fc" }, data: [[0,0,1],[1,0,.82],[2,0,.46],[3,0,-.61],[0,1,.82],[1,1,1],[2,1,.35],[3,1,-.52],[0,2,.46],[1,2,.35],[2,2,1],[3,2,-.28],[0,3,-.61],[1,3,-.52],[2,3,-.28],[3,3,1]] }],
    };
    case "connected-scatter": return {
      animation: false, grid: { left: 44, right: 20, top: 20, bottom: 36 }, tooltip: { trigger: "axis" },
      xAxis: numericAxis, yAxis: numericAxis,
      series: [{ type: "line", data: [[18,22],[27,34],[35,31],[44,49],[57,55],[68,72]], symbolSize: 9, lineStyle: { color: primary, width: 3 }, itemStyle: { color: accent } }],
    };
    case "lollipop": return {
      animation: false, grid: { left: 72, right: 24, top: 20, bottom: 36 },
      xAxis: numericAxis, yAxis: { type: "category", data: ["Partner", "Retail", "Digital", "Direct"], ...axis },
      series: [
        { type: "bar", data: [36, 51, 67, 82], barWidth: 3, itemStyle: { color: "#53627a" } },
        { type: "scatter", data: [[36,0],[51,1],[67,2],[82,3]], symbolSize: 14, itemStyle: { color: primary } },
      ],
    };
    case "circular-bar": return {
      animation: false, polar: { radius: ["18%", "82%"] },
      angleAxis: { type: "value", max: 100, show: false },
      radiusAxis: { type: "category", data: ["North", "South", "East", "West"], axisLabel: { color: "#aeb8ca" } },
      tooltip: { trigger: "item" },
      series: [{ type: "bar", coordinateSystem: "polar", data: [72, 58, 84, 66], roundCap: true, itemStyle: { color: primary } }],
    };
    case "radar": return {
      animation: false,
      radar: { indicator: [{ name: "Growth", max: 100 }, { name: "Margin", max: 100 }, { name: "Retention", max: 100 }, { name: "Quality", max: 100 }, { name: "Velocity", max: 100 }], axisName: { color: "#aeb8ca" }, splitLine: { lineStyle: { color: "#354057" } }, splitArea: { areaStyle: { color: ["transparent"] } } },
      series: [{ type: "radar", data: [{ value: [82, 64, 76, 88, 71], name: "Current" }, { value: [70, 72, 68, 75, 78], name: "Plan" }], areaStyle: { opacity: .18 }, lineStyle: { width: 2 } }],
    };
    default: throw new Error(`Unsupported accepted renderer: ${kind}`);
  }
}
