// One colour per model, the same everywhere (chart, legend, lists). Colours are assigned in order of first appearance.
export const MODEL_COLORS = ["#38bdf8", "#a78bfa", "#f472b6", "#fbbf24", "#4ade80", "#fb923c", "#2dd4bf", "#94a3b8"];

export function colorFor(models: string[], model: string): string {
  const index = models.indexOf(model);
  return MODEL_COLORS[(index < 0 ? models.length : index) % MODEL_COLORS.length];
}
