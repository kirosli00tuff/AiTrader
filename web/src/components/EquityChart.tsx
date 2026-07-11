import type { EquityPoint } from "../api/types";

// Dependency-free SVG area chart. Green when up over the window, red when down.
// When drawdown is on, shade the underwater region (below the running peak) so
// risk is visible alongside growth.
export default function EquityChart({ points, height = 220, drawdown = false }: {
  points: EquityPoint[]; height?: number; drawdown?: boolean;
}) {
  if (!points || points.length < 2) {
    return <div className="empty">No equity history yet.</div>;
  }
  const W = 800;
  const H = height;
  const pad = 6;
  const ys = points.map((p) => p.equity);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const n = points.length;
  const x = (i: number) => pad + (i / (n - 1)) * (W - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - 2 * pad);
  const up = ys[n - 1] >= ys[0];
  const color = up ? "var(--green)" : "var(--red)";
  const fill = up ? "var(--green-dim)" : "var(--red-dim)";
  const line = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.equity).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${H - pad} L${x(0).toFixed(1)},${H - pad} Z`;

  // Underwater region: fill between the running peak and the equity line.
  let ddArea = "";
  if (drawdown) {
    let peak = ys[0];
    const peaks = ys.map((v) => (peak = Math.max(peak, v)));
    const top = peaks.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    const back = points.map((_p, i) => `L${x(n - 1 - i).toFixed(1)},${y(ys[n - 1 - i]).toFixed(1)}`).join(" ");
    ddArea = `${top} ${back} Z`;
  }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={height}
      preserveAspectRatio="none" role="img" aria-label="Equity curve">
      <path d={area} fill={fill} stroke="none" />
      {drawdown && <path d={ddArea} fill="var(--red-dim)" stroke="none" />}
      <path d={line} fill="none" stroke={color} strokeWidth={2} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
