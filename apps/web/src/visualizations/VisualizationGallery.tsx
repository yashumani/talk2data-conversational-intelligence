import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart, BoxplotChart, CustomChart, HeatmapChart, LineChart, PieChart, RadarChart, ScatterChart } from "echarts/charts";
import { GridComponent, PolarComponent, RadarComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { acceptedVisualizations } from "./catalog";
import { optionFor } from "./renderers";
import "./gallery.css";

echarts.use([
  BarChart,
  BoxplotChart,
  CustomChart,
  GridComponent,
  HeatmapChart,
  LineChart,
  PieChart,
  PolarComponent,
  RadarChart,
  RadarComponent,
  ScatterChart,
  SVGRenderer,
  TooltipComponent,
  VisualMapComponent,
]);

type Category = "All" | "Compare" | "Trend" | "Distribution" | "Relationship" | "Composition";

interface Presentation {
  readonly category: Exclude<Category, "All">;
  readonly description: string;
}

const PRESENTATION: Readonly<Record<string, Presentation>> = {
  "bar": { category: "Compare", description: "Compare values across a small set of categories." },
  "grouped-bar": { category: "Compare", description: "Compare multiple series side by side." },
  "stacked-bar": { category: "Composition", description: "See totals and how each segment contributes." },
  "horizontal-bar": { category: "Compare", description: "Rank categories with long, readable labels." },
  "line": { category: "Trend", description: "Follow movement across an ordered period." },
  "multi-line": { category: "Trend", description: "Compare how several measures change together." },
  "area": { category: "Trend", description: "Emphasize the scale of change over time." },
  "stacked-area": { category: "Composition", description: "Track a changing total and its components." },
  "scatter": { category: "Relationship", description: "Reveal association, clusters, and outliers." },
  "bubble": { category: "Relationship", description: "Compare three numeric dimensions at once." },
  "histogram": { category: "Distribution", description: "Understand the shape and spread of a measure." },
  "boxplot": { category: "Distribution", description: "Compare medians, ranges, and unusual values." },
  "heatmap": { category: "Relationship", description: "Spot intensity patterns across two dimensions." },
  "pie": { category: "Composition", description: "Show a simple part-to-whole relationship." },
  "donut": { category: "Composition", description: "Highlight share of total in a compact form." },
  "violin": { category: "Distribution", description: "Compare the full shape of several distributions." },
  "density": { category: "Distribution", description: "See where continuous values concentrate." },
  "ridgeline": { category: "Distribution", description: "Compare distribution shapes across groups." },
  "beeswarm": { category: "Distribution", description: "Show every observation without hiding overlap." },
  "density-2d": { category: "Relationship", description: "Find dense clusters across two measures." },
  "correlogram": { category: "Relationship", description: "Scan the strength and direction of correlations." },
  "connected-scatter": { category: "Relationship", description: "Follow the path between two changing measures." },
  "lollipop": { category: "Compare", description: "Rank categories with a lighter visual footprint." },
  "circular-bar": { category: "Compare", description: "Compare compact scores in a radial layout." },
  "radar": { category: "Compare", description: "Compare multivariate profiles against a benchmark." },
};

const CATEGORIES: readonly Category[] = ["All", "Compare", "Trend", "Distribution", "Relationship", "Composition"];

function ChartPreview({ kind, label }: { kind: string; label: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current || typeof window === "undefined") return;
    const chart = echarts.init(host.current, undefined, { renderer: "svg" });
    chart.setOption(optionFor(kind));
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.dispose(); };
  }, [kind]);
  return <div ref={host} className="chart-preview" role="img" aria-label={`${label} example using synthetic data`} />;
}

export function VisualizationGallery() {
  const [activeCategory, setActiveCategory] = useState<Category>("All");
  const [query, setQuery] = useState("");
  const entries = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return acceptedVisualizations.filter((entry) => {
      const presentation = PRESENTATION[entry.id];
      const matchesCategory = activeCategory === "All" || presentation.category === activeCategory;
      const categoryTerms = presentation.category === "Compare" ? "Compare comparison" : presentation.category;
      const matchesQuery = normalized.length === 0 || `${entry.label} ${categoryTerms} ${presentation.description}`.toLowerCase().includes(normalized);
      return matchesCategory && matchesQuery;
    });
  }, [activeCategory, query]);

  return <section className="visualization-browser" aria-labelledby="gallery-title">
    <div className="browser-heading">
      <div>
        <p className="section-label">Explore the library</p>
        <h2 id="gallery-title">Choose the view that fits your question</h2>
      </div>
      <label className="search-control">
        <span>Search visualizations</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Try trend, comparison, or heatmap"
          aria-controls="visualization-results"
        />
      </label>
    </div>

    <div className="category-controls" role="group" aria-label="Filter by analytical purpose">
      {CATEGORIES.map((category) => <button
        type="button"
        key={category}
        className={category === activeCategory ? "active" : ""}
        aria-pressed={category === activeCategory}
        aria-controls="visualization-results"
        onClick={() => setActiveCategory(category)}
      >{category}</button>)}
    </div>

    <p className="sr-only" aria-live="polite" aria-atomic="true">{entries.length} visualization examples shown.</p>
    <div id="visualization-results" className="gallery-grid">
      {entries.map((entry) => {
        const presentation = PRESENTATION[entry.id];
        return <article className="chart-card" key={entry.id}>
          <div className="card-heading">
            <div>
              <p>{presentation.category}</p>
              <h3>{entry.label}</h3>
            </div>
          </div>
          <p className="chart-description">{presentation.description}</p>
          <ChartPreview kind={entry.id} label={entry.label} />
        </article>;
      })}
      {entries.length === 0 && <div className="empty-state" role="status">
        <h3>No matching visualization</h3>
        <p>Try a broader term or choose another analytical purpose.</p>
      </div>}
    </div>
  </section>;
}
