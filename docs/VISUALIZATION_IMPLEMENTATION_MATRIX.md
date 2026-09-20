# Visualization implementation matrix

This document turns the public graph-gallery inspiration set into a finite, reviewable Talk2Data
product backlog. It is an inventory and independent implementation plan—not a claim that every
example from every gallery is copied or already implemented.

## Source inventory and deduplication

The inventory was captured from the chart-type labels on the landing pages for the
[D3 Graph Gallery](https://d3-graph-gallery.com/),
[R Graph Gallery](https://r-graph-gallery.com/),
[Python Graph Gallery](https://python-graph-gallery.com/), and
[React Graph Gallery](https://www.react-graph-gallery.com/). General tutorial topics such as
colors, animation, interactivity, libraries, and 3D are excluded because they are capabilities,
not semantic chart types.

Normalization collapses spelling and framework differences: `barplot` → `bar`, `doughnut` →
`donut`, `density 2d`/`2D Density` → `density-2d`, `line plot`/`line chart` → `line`, and related
map labels become explicit map targets. React's Voronoi entry is recorded as a spatial-partition
technique within the hierarchy family, rather than inflating the semantic target count.

| Source | Normalized targets on landing page | New targets in ordered union |
| --- | ---: | ---: |
| D3 | 37 | 37 |
| R | 42 | 5 |
| Python | 43 | 2 |
| React | Cross-check | 0 |
| **Deduplicated union** | **44** | **44** |

Machine-readable evidence lives in `contracts/visualization_source_inventory.v1.json` and
`contracts/visualization_source_taxonomy.v1.json`.

## Finite product matrix

One semantic source target can support several useful product forms. For example, `bar` covers
vertical, horizontal, grouped, stacked, diverging, bullet, funnel, and waterfall presentations.
The registry therefore contains 76 deliberately bounded product types.

| Batch | Count | Status | Product types |
| ---: | ---: | --- | --- |
| 1 | 15 | Accepted | Bar, grouped bar, stacked bar, horizontal bar, line, multi-line, area, stacked area, scatter, bubble, histogram, boxplot, heatmap, pie, donut |
| 2 | 10 | Accepted | Violin, density, ridgeline, beeswarm, 2D density, correlogram, connected scatter, lollipop, circular bar, radar |
| 3 | 9 | Queued | Word cloud, parallel coordinates, treemap, circle packing, dendrogram, waffle, table, Venn, sunburst |
| 4 | 10 | Queued | Time series, step line, sparkline, streamgraph, candlestick, bump, slope, horizon, calendar heatmap, range area |
| 5 | 8 | Queued | Choropleth, symbol map, hexbin map, cartogram, connection map, tile map, route map, proportional map |
| 6 | 8 | Queued | Network, force network, Sankey, chord, arc diagram, edge bundling, alluvial, dependency wheel |
| 7 | 8 | Queued | Funnel, bullet, gauge, waterfall, Marimekko, diverging bar, dot plot, dumbbell |
| 8 | 8 | Queued | Small multiples, faceted bar, population pyramid, mosaic, contour, Voronoi, hexbin scatter, polar area |
| **Total** | **76** | **25 accepted / 51 queued** | |

## Accepted-batch contract

Every accepted implementation must:

1. render deterministic synthetic data without a backend or credential;
2. preserve the chart's semantic purpose and accessible name;
3. work at desktop and mobile widths and honor reduced-motion preferences;
4. avoid `fetch`, WebSocket, browser storage, runtime API configuration, and production data;
5. have unit coverage for its deterministic option contract;
6. appear in the dedicated static Pages entry; and
7. remain independently implemented—no copied gallery code, assets, screenshots, or datasets.

Batches 1 and 2 satisfy this contract. The end-user gallery shows only accepted visualizations;
remaining entries stay in this contributor matrix and the machine-readable registry, explicitly
marked queued. A queued registry row is not an implementation claim.

## Contribution workflow

Claim one registry ID per issue. The pull request should include the implementation, a synthetic
fixture and why-it-fits explanation, accessibility behavior, responsive verification,
tests, and source-specific semantic review. Maintainers change `status` to `accepted` only after
all criteria pass. Batch boundaries and totals are validated in CI to prevent an open-ended scope.
