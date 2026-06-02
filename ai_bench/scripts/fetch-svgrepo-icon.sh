#!/bin/sh
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/icons"
curl -fsSL -A "maitrix-extension/1.0" -o "$DIR/svgrepo-chart.svg" "https://www.svgrepo.com/download/283605/line-chart-line-graph.svg"
echo "OK — rasterize to icon16/48/128.png"
