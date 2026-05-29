// Returns Streamlit-matching color for a geo/final score
export function scoreColor(score: number | null): string {
  if (score === null) return "#a8a29e";
  if (score >= 0.65) return "#2ecc71";
  if (score >= 0.35) return "#f39c12";
  return "#e74c3c";
}

// Returns Streamlit-matching circle radius: 6 + score * 14
export function scoreRadius(score: number | null): number {
  if (score === null) return 6;
  return 6 + score * 14;
}
