import type { Thread } from "../api";

const COLUMNS: Record<string, number> = { SENSOR_READING: 0, MACHINE: 1, RUN: 2, BATCH: 3, ORDER: 4, UNKNOWN: 4, SHIPMENT: 5 };
const COL_TITLES = ["Sensor", "Machine", "Runs", "Batches", "Orders", "Shipments"];
const W = 150, H = 46, GAP_X = 52, GAP_Y = 18, TOP = 34;

export function TraceGraph({ thread }: { thread: Thread }) {
  const cols: string[][] = [[], [], [], [], [], []];
  for (const n of thread.nodes) cols[COLUMNS[n.type] ?? 5].push(n.id);
  const rows = Math.max(...cols.map((c) => c.length));
  const height = TOP + rows * (H + GAP_Y);
  const pos = new Map<string, { x: number; y: number }>();
  cols.forEach((ids, ci) => {
    const offset = ((rows - ids.length) * (H + GAP_Y)) / 2;
    ids.forEach((id, ri) => pos.set(id, { x: ci * (W + GAP_X), y: TOP + offset + ri * (H + GAP_Y) }));
  });
  const width = 6 * W + 5 * GAP_X;
  const byId = new Map(thread.nodes.map((n) => [n.id, n]));

  return (
    <div className="graph-scroll">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label="Traceability graph from sensor reading to shipments">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" className="edge-head" />
          </marker>
        </defs>
        {COL_TITLES.map((t, i) => (
          <text key={t} x={i * (W + GAP_X) + W / 2} y={14} textAnchor="middle" className="col-title">{t}</text>
        ))}
        {thread.edges.map((e) => {
          const a = pos.get(e.source), b = pos.get(e.target);
          if (!a || !b) return null;
          const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2, mx = (x1 + x2) / 2;
          return (
            <path key={`${e.source}-${e.target}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 2},${y2}`}
              className={`edge ${e.status === "UNKNOWN" ? "edge-unknown" : ""}`} markerEnd="url(#arrow)">
              <title>{`${e.source} ${e.relation} ${e.target} (${e.status})`}</title>
            </path>
          );
        })}
        {[...pos.entries()].map(([id, p]) => {
          const n = byId.get(id)!;
          const cls = `node node-${n.type.toLowerCase()} status-${n.status.toLowerCase()}${n.trace_status === "UNKNOWN" ? " trace-unknown" : ""}`;
          return (
            <g key={id} transform={`translate(${p.x},${p.y})`} className={cls}>
              <rect width={W} height={H} rx={8} />
              <text x={10} y={18} className="node-id">{n.type === "UNKNOWN" ? "UNKNOWN" : id}</text>
              <text x={10} y={35} className="node-label">{n.type === "BATCH" ? `${n.status} · ${n.label}` : n.label}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
