// Layout for the mind map page. Pure functions (no React), so they are easy to test and reuse.
//
//   buildTree(map, collapsed)        -> { root, byId }   visible tree (collapsed branches hidden)
//   layoutMindMap(tree, measure)     -> root in the middle, main topics split left/right, curved edges
//   layoutFlowchart(tree, measure)   -> top-down tree with elbow arrows
//   linkGeometry(a, b)               -> curved dashed cross-link between two placed nodes
//
// Every placed node gets { cx, cy, w, h, lines, font } (centre, size, wrapped label lines).

export const BRANCH_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"];

const STYLE = [
  { size: 16, weight: 700, maxW: 230, padX: 16, padY: 11 }, // root
  { size: 14, weight: 600, maxW: 190, padX: 14, padY: 9 }, // main topics
  { size: 13, weight: 500, maxW: 170, padX: 12, padY: 8 }, // subtopics
  { size: 12, weight: 500, maxW: 160, padX: 10, padY: 7 }, // details
];

export const fontFor = (level) => STYLE[Math.min(level, 3)];

// A measure(text, font) function backed by a canvas, so boxes fit their text exactly.
export function canvasMeasure() {
  const ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
  return (text, f) => {
    if (!ctx) return text.length * f.size * 0.56;
    ctx.font = `${f.weight} ${f.size}px Inter, system-ui, sans-serif`;
    return ctx.measureText(text).width;
  };
}

function wrap(text, f, measure) {
  const limit = f.maxW - 2 * f.padX;
  const lines = [];
  let line = "";
  for (const word of text.split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (line && measure(next, f) > limit) {
      lines.push(line);
      line = word;
    } else line = next;
  }
  if (line) lines.push(line);
  return lines.slice(0, 4);
}

function size(node, measure) {
  const f = fontFor(node.level);
  const lines = wrap(node.label, f, measure);
  const textW = Math.max(...lines.map((l) => measure(l, f)));
  const lineH = Math.round(f.size * 1.3);
  Object.assign(node, { font: f, lines, lineH, w: Math.max(56, Math.ceil(textW) + 2 * f.padX), h: lines.length * lineH + 2 * f.padY });
}

// Visible tree. Each node: { ...data, children, branch (index of its main topic), hiddenCount }.
export function buildTree(map, collapsed = new Set()) {
  const byId = {};
  for (const n of map.nodes) byId[n.node_id] = { ...n, children: [], branch: 0, hiddenCount: 0, childCount: 0 };
  for (const n of map.nodes) {
    if (n.parent_id && byId[n.parent_id]) {
      byId[n.parent_id].children.push(byId[n.node_id]);
      byId[n.parent_id].childCount += 1;
    }
  }
  const root = byId[map.root_id] || byId[map.nodes[0]?.node_id];
  const visible = {};
  const countAll = (n) => n.children.reduce((s, c) => s + 1 + countAll(c), 0);
  const walk = (n, branch) => {
    n.branch = branch;
    visible[n.node_id] = n;
    if (collapsed.has(n.node_id) && n.children.length) {
      n.hiddenCount = countAll(n);
      n.children = [];
    }
    n.children.forEach((c, i) => walk(c, n === root ? i : branch));
  };
  if (root) walk(root, 0);
  return { root, byId: visible };
}

// ---------------------------------------------------------------- mind map (left / right)
export function layoutMindMap({ root, byId }, measure) {
  Object.values(byId).forEach((n) => size(n, measure));
  root.cx = 0;
  root.cy = 0;
  const gap = (level) => (level <= 1 ? 22 : 12);
  const height = (n) => {
    if (!n.children.length) return (n.sub = n.h);
    const kids = n.children.reduce((s, c) => s + height(c), 0) + gap(n.level + 1) * (n.children.length - 1);
    return (n.sub = Math.max(n.h, kids));
  };
  const main = root.children;
  main.forEach(height);

  // split main topics into right then left halves of roughly equal height, keeping their order
  const total = main.reduce((s, c) => s + c.sub, 0);
  let acc = 0;
  const right = [];
  const left = [];
  for (const c of main) {
    (acc < total / 2 || right.length === 0 ? right : left).push(c);
    acc += c.sub;
  }
  if (main.length > 1 && left.length === 0) left.push(right.pop());

  const edges = [];
  for (const [side, dir] of [[right, 1], [left, -1]]) {
    if (!side.length) continue;
    // column offsets: depth d starts after the widest node of depth d-1 on this side
    const colW = {};
    const collect = (n) => {
      colW[n.level] = Math.max(colW[n.level] || 0, n.w);
      n.children.forEach(collect);
    };
    side.forEach(collect);
    const colX = { 1: root.w / 2 + 70 };
    for (let d = 2; d <= 3; d++) colX[d] = colX[d - 1] + (colW[d - 1] || 0) + 48;

    const place = (n, top) => {
      n.cy = top + n.sub / 2;
      n.cx = dir * (colX[n.level] + n.w / 2);
      const kids = n.children.reduce((s, c) => s + c.sub, 0) + gap(n.level + 1) * (n.children.length - 1);
      let y = n.cy - kids / 2;
      for (const c of n.children) {
        place(c, y);
        edges.push(curve(n, c, dir));
        y += c.sub + gap(c.level);
      }
    };
    const sideH = side.reduce((s, c) => s + c.sub, 0) + gap(1) * (side.length - 1);
    let y = -sideH / 2;
    for (const c of side) {
      place(c, y);
      edges.push(curve(root, c, dir));
      y += c.sub + gap(1);
    }
  }
  return { nodes: Object.values(byId), edges, mode: "mindmap" };
}

function curve(p, c, dir) {
  const x1 = p.cx + (dir * p.w) / 2;
  const x2 = c.cx - (dir * c.w) / 2;
  const mx = (x1 + x2) / 2;
  return { from: p, to: c, d: `M${x1},${p.cy} C${mx},${p.cy} ${mx},${c.cy} ${x2},${c.cy}` };
}

// ---------------------------------------------------------------- flowchart (top-down)
// Children that are all leaves are stacked under their parent like an indented list instead of spread
// sideways: the chart stays narrow, so it fits the screen with readable text.
export function layoutFlowchart({ root, byId }, measure) {
  const nodes = Object.values(byId);
  nodes.forEach((n) => size(n, measure));
  const H_GAP = 22;
  const V_GAP = 64;
  const INDENT = 22;
  const STACK_GAP = 10;
  const stacked = (n) => n.level >= 1 && n.children.length > 0 && n.children.every((c) => !c.children.length);

  const rowH = {};
  const addRow = (n) => {
    rowH[n.level] = Math.max(rowH[n.level] || 0, n.h);
    if (!stacked(n)) n.children.forEach(addRow);
  };
  addRow(root);
  const rowY = { 0: 0 };
  for (let d = 1; d <= 3; d++) rowY[d] = rowY[d - 1] + (rowH[d - 1] || 0) + V_GAP;

  const width = (n) => {
    if (stacked(n)) return (n.sub = Math.max(n.w, INDENT + Math.max(...n.children.map((c) => c.w))));
    const kids = n.children.reduce((s, c) => s + width(c), 0) + H_GAP * Math.max(0, n.children.length - 1);
    return (n.sub = Math.max(n.w, kids));
  };
  width(root);
  const edges = [];
  const place = (n, left) => {
    n.cy = rowY[n.level] + rowH[n.level] / 2;
    if (stacked(n)) {
      n.cx = left + (n.sub - Math.max(n.w, INDENT + Math.max(...n.children.map((c) => c.w)))) / 2 + n.w / 2;
      const boxLeft = n.cx - n.w / 2;
      const spineX = boxLeft + INDENT / 2;
      let y = n.cy + n.h / 2 + 16;
      for (const c of n.children) {
        c.cx = boxLeft + INDENT + c.w / 2;
        c.cy = y + c.h / 2;
        y += c.h + STACK_GAP;
        edges.push({ from: n, to: c, d: `M${spineX},${n.cy + n.h / 2} V${c.cy - 6} Q${spineX},${c.cy} ${spineX + 6},${c.cy} H${c.cx - c.w / 2 - 3}`, arrow: true });
      }
      return;
    }
    n.cx = left + n.sub / 2;
    const kids = n.children.reduce((s, c) => s + c.sub, 0) + H_GAP * Math.max(0, n.children.length - 1);
    let x = n.cx - kids / 2;
    for (const c of n.children) {
      place(c, x);
      x += c.sub + H_GAP;
    }
  };
  place(root, -root.sub / 2);
  for (const n of nodes) {
    if (stacked(n)) continue;
    for (const c of n.children) {
      const y1 = n.cy + n.h / 2;
      const y2 = c.cy - c.h / 2 - 3; // leave room for the arrowhead
      const my = rowY[n.level] + rowH[n.level] + V_GAP / 2; // all elbows of a row share one line
      const r = Math.min(8, Math.abs(c.cx - n.cx) / 2);
      const d =
        Math.abs(c.cx - n.cx) < 1
          ? `M${n.cx},${y1} V${y2}`
          : `M${n.cx},${y1} V${my - r} Q${n.cx},${my} ${n.cx + Math.sign(c.cx - n.cx) * r},${my} H${c.cx - Math.sign(c.cx - n.cx) * r} Q${c.cx},${my} ${c.cx},${my + r} V${y2}`;
      edges.push({ from: n, to: c, d, arrow: true });
    }
  }
  return { nodes, edges, mode: "flowchart" };
}

// ---------------------------------------------------------------- cross-links
// Point where the line from the centre of box n towards (tx, ty) leaves the box.
function edgePoint(n, tx, ty) {
  const dx = tx - n.cx;
  const dy = ty - n.cy;
  if (!dx && !dy) return [n.cx, n.cy];
  const s = Math.min(Math.abs(n.w / 2 / (dx || 1e-9)), Math.abs(n.h / 2 / (dy || 1e-9)));
  return [n.cx + dx * s, n.cy + dy * s];
}

// Curves away from the root (at 0,0), so links between neighbouring boxes go around the tree, not through it.
export function linkGeometry(a, b) {
  const dx = b.cx - a.cx;
  const dy = b.cy - a.cy;
  const dist = Math.hypot(dx, dy) || 1;
  // the curve peaks at half the bend, so boxes stacked in one column need about a box width to clear the boxes between them
  const bend = Math.min(180, Math.max(50, dist * 0.3, (Math.abs(dy) > Math.abs(dx) ? Math.max(a.w, b.w) : Math.max(a.h, b.h)) + 30));
  const mx = (a.cx + b.cx) / 2;
  const my = (a.cy + b.cy) / 2;
  const px = (-dy / dist) * bend;
  const py = (dx / dist) * bend;
  const out = Math.hypot(mx + px, my + py) >= Math.hypot(mx - px, my - py) ? 1 : -1;
  const qx = mx + out * px;
  const qy = my + out * py;
  const [x1, y1] = edgePoint(a, qx, qy);
  const [x2, y2] = edgePoint(b, qx, qy);
  // point on the curve at t (0 = start, 1 = end): lets a label slide along its own arrow
  const at = (t) => ({ x: (1 - t) ** 2 * x1 + 2 * (1 - t) * t * qx + t * t * x2, y: (1 - t) ** 2 * y1 + 2 * (1 - t) * t * qy + t * t * y2 });
  return { d: `M${x1},${y1} Q${qx},${qy} ${x2},${y2}`, label: at(0.5), at };
}

export function bounds(nodes, pad = 40) {
  if (!nodes.length) return { x: 0, y: 0, w: 1, h: 1 };
  const xs = nodes.flatMap((n) => [n.cx - n.w / 2, n.cx + n.w / 2]);
  const ys = nodes.flatMap((n) => [n.cy - n.h / 2, n.cy + n.h / 2]);
  const x = Math.min(...xs) - pad;
  const y = Math.min(...ys) - pad;
  return { x, y, w: Math.max(...xs) + pad - x, h: Math.max(...ys) + pad - y };
}

// Labels of cross-links. Each label stays ON its arrow: it slides along the curve (and then a little off it)
// to the first spot that covers no box and no other label; if there is none, the spot covering least wins.
export function placeLinks(links, placed, measure) {
  const boxes = Object.values(placed).map((n) => ({ x: n.cx - n.w / 2, y: n.cy - n.h / 2, w: n.w, h: n.h }));
  const overlap = (r) =>
    boxes.reduce((sum, b) => sum + Math.max(0, Math.min(r.x + r.w, b.x + b.w) - Math.max(r.x, b.x)) * Math.max(0, Math.min(r.y + r.h, b.y + b.h) - Math.max(r.y, b.y)), 0);
  return links.map((l) => {
    const g = linkGeometry(placed[l.from_id], placed[l.to_id]);
    if (!l.label) return { ...l, d: g.d, label: null };
    const w = measure(l.label, { size: 11, weight: 500 }) + 12;
    let best = null;
    search: for (const dy of [0, -12, 12]) {
      for (const t of [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8]) {
        const p = g.at(t);
        const r = { x: p.x - w / 2, y: p.y + dy - 9, w, h: 18 };
        const cost = overlap(r) + Math.abs(dy) + Math.abs(t - 0.5) * 10;
        if (!best || cost < best.cost) best = { cost, x: p.x, y: p.y + dy };
        if (overlap(r) === 0) break search;
      }
    }
    boxes.push({ x: best.x - w / 2, y: best.y - 9, w, h: 18 });
    return { ...l, d: g.d, label: { text: l.label, x: best.x, y: best.y, w } };
  });
}
