import { VisualizationGallery } from "../visualizations/VisualizationGallery";

export function GalleryApp() {
  return <main className="gallery-shell">
    <header className="gallery-shell__header">
      <a className="brand" href="#gallery-title" aria-label="Talk2Data visualization studio home">
        <span className="brand-mark" aria-hidden="true">T2D</span>
        <span>Talk2Data</span>
      </a>
      <div className="hero-copy">
        <p className="eyebrow">Visualization studio</p>
        <h1>Turn data into a clear decision.</h1>
        <p>Explore practical chart patterns for comparison, trends, composition, distributions, and relationships—using safe sample data that runs entirely in your browser.</p>
        <a className="primary-action" href="#gallery-title">Explore visualizations <span aria-hidden="true">↓</span></a>
      </div>
      <aside className="hero-note" aria-label="How to use this gallery">
        <p>Start with the question</p>
        <ol>
          <li><span>01</span>Choose an analytical purpose</li>
          <li><span>02</span>Compare the visual patterns</li>
          <li><span>03</span>Select the clearest story</li>
        </ol>
      </aside>
    </header>
    <VisualizationGallery />
    <footer className="gallery-footer">
      <p>Talk2Data · Visualization patterns using synthetic sample data</p>
      <a href="../licenses/THIRD_PARTY_NOTICES.md">Third-party notices</a>
    </footer>
  </main>;
}
