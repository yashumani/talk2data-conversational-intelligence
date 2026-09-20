export type VisualizationStatus = "accepted" | "queued";

export interface VisualizationEntry {
  readonly id: string;
  readonly label: string;
  readonly target: string;
  readonly batch: number;
  readonly status: VisualizationStatus;
  readonly rendererKind: string;
}

type EntryTuple = readonly [id: string, label: string, target: string, rendererKind?: string];

function batch(number: number, status: VisualizationStatus, entries: readonly EntryTuple[]) {
  return entries.map(([id, label, target, rendererKind]) => Object.freeze({
    id, label, target, batch: number, status, rendererKind: rendererKind ?? target,
  }));
}

export const VISUALIZATION_REGISTRY: readonly VisualizationEntry[] = Object.freeze([
  ...batch(1, "accepted", [
    ["bar", "Bar", "bar"], ["grouped-bar", "Grouped bar", "grouped-stacked-bar"],
    ["stacked-bar", "Stacked bar", "grouped-stacked-bar"], ["horizontal-bar", "Horizontal bar", "bar"],
    ["line", "Line", "line"], ["multi-line", "Multi-line", "line"], ["area", "Area", "area"],
    ["stacked-area", "Stacked area", "stacked-area"], ["scatter", "Scatter", "scatter"],
    ["bubble", "Bubble", "bubble"], ["histogram", "Histogram", "histogram"],
    ["boxplot", "Boxplot", "boxplot"], ["heatmap", "Heatmap", "heatmap"],
    ["pie", "Pie", "pie"], ["donut", "Donut", "donut"],
  ]),
  ...batch(2, "accepted", [
    ["violin", "Violin", "violin"], ["density", "Density", "density"],
    ["ridgeline", "Ridgeline", "ridgeline"], ["beeswarm", "Beeswarm", "beeswarm"],
    ["density-2d", "2D density", "density-2d"], ["correlogram", "Correlogram", "correlogram"],
    ["connected-scatter", "Connected scatter", "connected-scatter"], ["lollipop", "Lollipop", "lollipop"],
    ["circular-bar", "Circular bar", "circular-bar"], ["radar", "Radar", "radar"],
  ]),
  ...batch(3, "queued", [
    ["wordcloud", "Word cloud", "wordcloud"], ["parallel-coordinates", "Parallel coordinates", "parallel-coordinates"],
    ["treemap", "Treemap", "treemap"], ["circle-packing", "Circle packing", "circle-packing"],
    ["dendrogram", "Dendrogram", "dendrogram"], ["waffle", "Waffle", "waffle"],
    ["table", "Table", "table"], ["venn", "Venn", "venn"], ["sunburst", "Sunburst", "treemap"],
  ]),
  ...batch(4, "queued", [
    ["time-series", "Time series", "time-series"], ["step-line", "Step line", "line"],
    ["sparkline", "Sparkline", "line"], ["streamgraph", "Streamgraph", "streamgraph"],
    ["candlestick", "Candlestick", "candlestick"], ["bump-chart", "Bump chart", "line"],
    ["slope-chart", "Slope chart", "connected-scatter"], ["horizon-chart", "Horizon chart", "area"],
    ["calendar-heatmap", "Calendar heatmap", "heatmap"], ["range-area", "Range area", "area"],
  ]),
  ...batch(5, "queued", [
    ["choropleth", "Choropleth", "choropleth"], ["symbol-map", "Symbol map", "bubble-map"],
    ["hexbin-map", "Hexbin map", "hexbin-map"], ["cartogram", "Cartogram", "cartogram"],
    ["connection-map", "Connection map", "connection-map"], ["tile-map", "Tile map", "map"],
    ["route-map", "Route map", "connection-map"], ["proportional-map", "Proportional symbol map", "bubble-map"],
  ]),
  ...batch(6, "queued", [
    ["network", "Network", "network"], ["force-network", "Force network", "network"],
    ["sankey", "Sankey", "sankey"], ["chord", "Chord", "chord"],
    ["arc-diagram", "Arc diagram", "arc-diagram"], ["edge-bundling", "Edge bundling", "edge-bundling"],
    ["alluvial", "Alluvial", "sankey"], ["dependency-wheel", "Dependency wheel", "chord"],
  ]),
  ...batch(7, "queued", [
    ["funnel", "Funnel", "bar"], ["bullet", "Bullet", "bar"], ["gauge", "Gauge", "donut"],
    ["waterfall", "Waterfall", "bar"], ["marimekko", "Marimekko", "grouped-stacked-bar"],
    ["diverging-bar", "Diverging bar", "bar"], ["dot-plot", "Dot plot", "lollipop"],
    ["dumbbell", "Dumbbell", "connected-scatter"],
  ]),
  ...batch(8, "queued", [
    ["small-multiples", "Small multiples", "line"], ["faceted-bar", "Faceted bar", "bar"],
    ["population-pyramid", "Population pyramid", "grouped-stacked-bar"],
    ["mosaic", "Mosaic", "grouped-stacked-bar"], ["contour", "Contour", "density-2d"],
    ["voronoi", "Voronoi", "circle-packing"], ["hexbin-scatter", "Hexbin scatter", "density-2d"],
    ["polar-area", "Polar area", "radar"],
  ]),
]);

export const acceptedVisualizations = VISUALIZATION_REGISTRY.filter((entry) => entry.status === "accepted");
export const queuedVisualizations = VISUALIZATION_REGISTRY.filter((entry) => entry.status === "queued");
