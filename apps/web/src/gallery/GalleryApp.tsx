import { VisualizationGallery } from "../visualizations/VisualizationGallery";

export function GalleryApp() {
  return <main className="gallery-shell">
    <header className="gallery-shell__header">
      <p className="eyebrow">Talk2Data community alpha</p>
      <h1>Static visualization gallery</h1>
      <p>Explore deterministic synthetic examples and the complete finite implementation queue. This gallery makes no network or runtime API requests.</p>
    </header>
    <VisualizationGallery />
  </main>;
}
