import { useEffect, useRef, useState } from "react";
import { BarChart, BoxplotChart, HeatmapChart, LineChart, PieChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { acceptedVisualizations, queuedVisualizations, VISUALIZATION_REGISTRY } from "./catalog";
import { optionFor } from "./renderers";
import "./gallery.css";

echarts.use([
  BarChart,
  BoxplotChart,
  GridComponent,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  SVGRenderer,
  TooltipComponent,
  VisualMapComponent,
]);

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
  return <div ref={host} className="chart-preview" role="img" aria-label={`${label} synthetic visualization`} />;
}

export function VisualizationGallery() {
  const [view, setView] = useState<"accepted" | "queue">("accepted");
  const entries = view === "accepted" ? acceptedVisualizations : queuedVisualizations;
  return <section aria-labelledby="gallery-title">
    <div className="gallery-summary">
      <div><strong>44</strong><span>source targets</span></div>
      <div><strong>{VISUALIZATION_REGISTRY.length}</strong><span>product types</span></div>
      <div><strong>{acceptedVisualizations.length}</strong><span>Batch 1 accepted</span></div>
      <div><strong>{queuedVisualizations.length}</strong><span>queued</span></div>
    </div>
    <div className="gallery-controls" role="group" aria-label="Visualization status">
      <button className={view === "accepted" ? "active" : ""} onClick={() => setView("accepted")}>Implemented</button>
      <button className={view === "queue" ? "active" : ""} onClick={() => setView("queue")}>Finite queue</button>
    </div>
    <h2 id="gallery-title">{view === "accepted" ? "Batch 1 renderers" : "Batches 2–8"}</h2>
    <div className={`gallery-grid ${view === "queue" ? "queue" : ""}`}>
      {entries.map((entry) => <article className="chart-card" key={entry.id}>
        <div className="card-heading"><div><p>Batch {entry.batch} · {entry.target}</p><h3>{entry.label}</h3></div><span>{entry.status}</span></div>
        {entry.status === "accepted"
          ? <ChartPreview kind={entry.id} label={entry.label} />
          : <p className="queue-note">Registry contract reserved. Implementation and source-specific review are intentionally queued.</p>}
      </article>)}
    </div>
  </section>;
}
