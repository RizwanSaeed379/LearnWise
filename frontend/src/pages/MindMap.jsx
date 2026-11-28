import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { CitedText, ErrorBox, Segmented, Spinner, TopicInput, useAsync } from "../components/ui.jsx";
import { BRANCH_COLORS, bounds, buildTree, canvasMeasure, layoutFlowchart, layoutMindMap, placeLinks } from "../components/mindmapLayout.js";

const VIEWS = ["mind map", "flowchart"];
const LEVELS = ["Main idea", "Topic", "Subtopic", "Detail"];
// Kept while the app is open, so switching to Notes and back doesn't lose the map.
const cache = { map: null, view: "mind map", topic: "", maxNodes: 18 };
const measure = canvasMeasure();

export default function MindMap({ documentIds, topics, docs, goTo }) {
  const [topic, setTopic] = useState(cache.topic);
  const [maxNodes, setMaxNodes] = useState(cache.maxNodes);
  const [view, setView] = useState(cache.view);
  const [map, setMap] = useState(cache.map);
  const [selected, setSelected] = useState(null);
  const { loading, error, run } = useAsync();

  useEffect(() => { Object.assign(cache, { map, view, topic, maxNodes }); }, [map, view, topic, maxNodes]);

  const generate = (t = topic) =>
    run(async () => {
      const res = await api.mindmap(t.trim() || null, maxNodes, documentIds);
      setMap(res);
      setSelected(null);
    });

  const node = map && selected ? map.nodes.find((n) => n.node_id === selected) : null;

  return (
    <div className="stack">
      <form className="card controls" onSubmit={(e) => { e.preventDefault(); generate(); }}>
        <TopicInput value={topic} onChange={setTopic} topics={topics} placeholder="Topic (leave empty to map the whole document)" />
        <label className="num">Nodes <input type="number" min={5} max={40} value={maxNodes} onChange={(e) => setMaxNodes(+e.target.value)} /></label>
        <button className="btn" disabled={loading || maxNodes < 5 || maxNodes > 40}>{topic.trim() ? "Map this topic" : "Map whole document"}</button>
      </form>

      {loading && <Spinner label="Mapping your topics…" />}
      <ErrorBox error={error} />

      {!map && !loading && (
        <div className="card empty">
          <div className="big">🧠</div>
          <p><b>See how the ideas in your lecture fit together.</b></p>
          <p className="muted">
            Leave the topic empty for a map of the whole document, or type a topic to zoom into it. Switch between a
            mind map and a flowchart, click any box for its summary and page, and jump straight to notes or a quiz on it.
          </p>
          {!docs.length && <button className="btn ghost" onClick={() => goTo("library")}>Upload a document first</button>}
        </div>
      )}

      {map && (
        <>
          <div className="row spread">
            <div>
              <h2 className="map-title">{map.title}</h2>
              <span className="muted">{map.nodes.length} ideas · {map.links.length} connections · from {new Set(map.sources.map((s) => s.filename)).size || 0} document(s)</span>
            </div>
            <Segmented options={VIEWS} value={view} onChange={setView} />
          </div>
          <MapCanvas key={map.root_id + map.title} map={map} view={view} selected={selected} onSelect={setSelected} />
          {node && (
            <NodeDetails
              node={node}
              map={map}
              onClose={() => setSelected(null)}
              goTo={goTo}
              onRemap={(label) => { setTopic(label); generate(label); }}
            />
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- the diagram
function MapCanvas({ map, view, selected, onSelect }) {
  const theme = useThemeColors();
  const [collapsed, setCollapsed] = useState(() => new Set());
  const [showLinks, setShowLinks] = useState(true);
  const [t, setT] = useState({ x: 0, y: 0, k: 1 });
  const wrapRef = useRef(null);
  const svgRef = useRef(null);
  const drag = useRef(null);

  const layout = useMemo(() => {
    const tree = buildTree(map, collapsed);
    return view === "flowchart" ? layoutFlowchart(tree, measure) : layoutMindMap(tree, measure);
  }, [map, view, collapsed]);
  const placed = useMemo(() => Object.fromEntries(layout.nodes.map((n) => [n.node_id, n])), [layout]);
  const links = useMemo(
    () => (showLinks ? placeLinks(map.links.filter((l) => placed[l.from_id] && placed[l.to_id]), placed, measure) : []),
    [map, placed, showLinks],
  );
  // what fit and PNG export must keep in view: the boxes plus the link labels (which can sit outside them)
  const extent = useMemo(() => [...layout.nodes, ...links.filter((l) => l.label).map((l) => ({ cx: l.label.x, cy: l.label.y, w: l.label.w, h: 18 }))], [layout, links]);

  const fit = () => {
    const el = wrapRef.current;
    if (!el) return;
    const b = bounds(extent);
    // a wide, flat diagram doesn't need a tall canvas (and a tall one needs at most 75% of the screen)
    const height = Math.round(Math.min(Math.max(360, (el.clientWidth * b.h) / b.w + 30), window.innerHeight * 0.75));
    el.style.height = `${height}px`;
    const k = Math.min(el.clientWidth / b.w, height / b.h, 1.3);
    setT({ k, x: el.clientWidth / 2 - (b.x + b.w / 2) * k, y: height / 2 - (b.y + b.h / 2) * k });
  };
  useEffect(fit, [view, map]); // eslint-disable-line react-hooks/exhaustive-deps

  // wheel = zoom around the cursor (needs a non-passive listener to stop the page scrolling)
  useEffect(() => {
    const el = wrapRef.current;
    const onWheel = (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0015));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);
  const zoomAt = (px, py, f) =>
    setT((v) => {
      const k = Math.min(3, Math.max(0.2, v.k * f));
      return { k, x: px - ((px - v.x) * k) / v.k, y: py - ((py - v.y) * k) / v.k };
    });
  const zoomCenter = (f) => zoomAt(wrapRef.current.clientWidth / 2, wrapRef.current.clientHeight / 2, f);

  const onPointerDown = (e) => {
    if (e.button !== 0) return;
    drag.current = { x: e.clientX, y: e.clientY, tx: t.x, ty: t.y, moved: false };
  };
  const onPointerMove = (e) => {
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) < 4) return;
    if (!d.moved) wrapRef.current.setPointerCapture?.(e.pointerId);
    d.moved = true;
    setT((v) => ({ ...v, x: d.tx + dx, y: d.ty + dy }));
  };
  const onPointerUp = () => setTimeout(() => (drag.current = null), 0);
  const clicked = (fn) => (e) => {
    e.stopPropagation();
    if (!drag.current?.moved) fn();
  };

  const toggle = (id) =>
    setCollapsed((s) => {
      const next = new Set(s);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  const collapseToTopics = () => setCollapsed(new Set(map.nodes.filter((n) => n.level === 1).map((n) => n.node_id)));

  const colorOf = (n) => (n.level === 0 ? theme.accent : BRANCH_COLORS[n.branch % BRANCH_COLORS.length]);

  return (
    <div className="card map-card">
      <div className="map-toolbar">
        <button className="btn ghost sm" onClick={() => zoomCenter(1.25)} title="Zoom in">＋</button>
        <button className="btn ghost sm" onClick={() => zoomCenter(0.8)} title="Zoom out">－</button>
        <button className="btn ghost sm" onClick={fit}>Fit</button>
        <span className="sep" />
        <button className="btn ghost sm" onClick={() => setCollapsed(new Set())} disabled={!collapsed.size}>Expand all</button>
        <button className="btn ghost sm" onClick={collapseToTopics}>Main topics only</button>
        <label className="check"><input type="checkbox" checked={showLinks} onChange={(e) => setShowLinks(e.target.checked)} /> Connections</label>
        <span className="grow" />
        <button className="btn ghost sm" onClick={() => downloadPng(svgRef.current, extent, theme, map.title)}>⬇ PNG</button>
      </div>

      <div
        ref={wrapRef}
        className="map-wrap"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onClick={() => !drag.current?.moved && onSelect(null)}
      >
        <svg ref={svgRef} width="100%" height="100%" style={{ fontFamily: "Inter, system-ui, sans-serif" }}>
          <defs>
            <marker id="mm-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={theme.muted} />
            </marker>
            <marker id="mm-link-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={theme.link} />
            </marker>
          </defs>
          <g className="mm-scene" transform={`translate(${t.x},${t.y}) scale(${t.k})`}>
            {layout.edges.map((e) => (
              <path
                key={e.from.node_id + e.to.node_id}
                d={e.d}
                fill="none"
                stroke={e.arrow ? theme.muted : colorOf(e.to)}
                strokeOpacity={e.arrow ? 0.9 : 0.75}
                strokeWidth={e.arrow ? 1.6 : e.to.level === 1 ? 3 : 2}
                markerEnd={e.arrow ? "url(#mm-arrow)" : undefined}
              />
            ))}

            {links.map((l) => (
              <path key={l.from_id + l.to_id} d={l.d} fill="none" stroke={theme.link} strokeWidth={1.6} strokeDasharray="5 4" markerEnd="url(#mm-link-arrow)" />
            ))}

            {layout.nodes.map((n) => {
              const color = colorOf(n);
              const filled = n.level <= 1;
              const isSel = n.node_id === selected;
              const hasKids = n.childCount > 0;
              const badge = layout.mode === "flowchart" ? { x: 0, y: n.h / 2 } : { x: (n.cx >= 0 ? 1 : -1) * (n.w / 2), y: 0 };
              return (
                <g
                  key={n.node_id}
                  transform={`translate(${n.cx},${n.cy})`}
                  className="mm-node"
                  role="button"
                  tabIndex={0}
                  aria-label={n.label}
                  onClick={clicked(() => onSelect(isSel ? null : n.node_id))}
                  onKeyDown={(e) => e.key === "Enter" && onSelect(n.node_id)}
                >
                  <title>{n.summary || n.label}</title>
                  <rect
                    x={-n.w / 2}
                    y={-n.h / 2}
                    width={n.w}
                    height={n.h}
                    rx={n.level === 0 ? 14 : layout.mode === "flowchart" ? 8 : 10}
                    fill={filled ? color : theme.panel}
                    stroke={isSel ? theme.text : color}
                    strokeWidth={isSel ? 3 : filled ? 0 : 1.8}
                  />
                  <text textAnchor="middle" fontSize={n.font.size} fontWeight={n.font.weight} fill={filled ? "#ffffff" : theme.text}>
                    {n.lines.map((line, i) => (
                      <tspan key={i} x={0} y={(i - (n.lines.length - 1) / 2) * n.lineH} dy="0.35em">{line}</tspan>
                    ))}
                  </text>
                  {hasKids && n.level > 0 && (
                    <g transform={`translate(${badge.x},${badge.y})`} className="mm-toggle" onClick={clicked(() => toggle(n.node_id))}>
                      <title>{n.hiddenCount ? `Show ${n.hiddenCount} hidden` : "Collapse"}</title>
                      <circle r={9} fill={theme.panel} stroke={color} strokeWidth={1.6} />
                      <text textAnchor="middle" dy="0.35em" fontSize={n.hiddenCount ? 10 : 13} fontWeight={700} fill={color}>
                        {n.hiddenCount ? `+${n.hiddenCount}` : "−"}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}

            {links.filter((l) => l.label).map((l) => (
              <g key={`label-${l.from_id}-${l.to_id}`} transform={`translate(${l.label.x},${l.label.y})`} pointerEvents="none">
                <rect x={-l.label.w / 2} y={-9} width={l.label.w} height={18} rx={9} fill={theme.panel} stroke={theme.link} strokeWidth={1} />
                <text textAnchor="middle" dy="0.35em" fontSize={11} fontWeight={500} fill={theme.link}>{l.label.text}</text>
              </g>
            ))}
          </g>
        </svg>
        <div className="map-hint muted">Drag to move · scroll to zoom · click a box for details</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- details of the clicked node
function NodeDetails({ node, map, onClose, goTo, onRemap }) {
  const [showSnippet, setShowSnippet] = useState(false);
  const parent = map.nodes.find((n) => n.node_id === node.parent_id);
  const children = map.nodes.filter((n) => n.parent_id === node.node_id);
  const related = map.links
    .filter((l) => l.from_id === node.node_id || l.to_id === node.node_id)
    .map((l) => {
      const out = l.from_id === node.node_id;
      const other = map.nodes.find((n) => n.node_id === (out ? l.to_id : l.from_id));
      // a full sentence, read left to right: <from box> → <arrow label> → <to box>
      return other && { other, from: out ? node.label : other.label, verb: l.label || "related to", to: out ? other.label : node.label };
    })
    .filter(Boolean);
  const src = node.source;

  return (
    <div className="card node-details">
      <div className="row spread">
        <div className="row">
          <h3>{node.label}</h3>
          <span className="chip">{LEVELS[node.level]}</span>
          {parent && <span className="muted">in {parent.label}</span>}
        </div>
        <button className="btn ghost sm" onClick={onClose}>✕</button>
      </div>
      {node.summary && <CitedText text={node.summary} sources={map.sources} onCite={() => setShowSnippet(true)} />}
      {!!children.length && <div className="chips">{children.map((c) => <span key={c.node_id} className="chip soft">{c.label}</span>)}</div>}
      {!!related.length && (
        <div>
          <div className="sources-title">Connections</div>
          <ul className="related">
            {related.map((r) => (
              <li key={r.other.node_id}>
                <b>{r.from}</b> <span className="muted">→ {r.verb} →</span> <b>{r.to}</b>
              </li>
            ))}
          </ul>
        </div>
      )}
      {src && (
        <div className="source" onClick={() => setShowSnippet(!showSnippet)}>
          <span className="tag">p. {src.page}</span>
          <span>{src.filename}</span>
          <span className="muted">{showSnippet ? "hide passage" : "show passage"}</span>
          {showSnippet && <p className="snippet">“{src.snippet}”</p>}
        </div>
      )}
      <div className="row">
        <button className="btn sm" onClick={() => goTo("notes", node.label)}>📝 Notes</button>
        <button className="btn sm" onClick={() => goTo("quiz", node.label)}>✅ Quiz me</button>
        <button className="btn sm" onClick={() => goTo("flashcards", node.label)}>🃏 Flashcards</button>
        <button className="btn sm" onClick={() => goTo("ask", node.label)}>💬 Ask</button>
        {node.level > 0 && <button className="btn ghost sm" onClick={() => onRemap(node.label)}>🧠 Map this topic</button>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- helpers
// SVG attributes can't use CSS variables once exported, so read the theme's real colours.
function useThemeColors() {
  const read = () => {
    const css = getComputedStyle(document.documentElement);
    const v = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
    return { panel: v("--panel", "#fff"), text: v("--text", "#111827"), muted: v("--muted", "#6b7280"), accent: v("--accent", "#4f46e5"), link: v("--accent", "#4f46e5") };
  };
  const [colors, setColors] = useState(read);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setColors(read());
    mq.addEventListener?.("change", update);
    return () => mq.removeEventListener?.("change", update);
  }, []);
  return colors;
}

function downloadPng(svg, nodes, theme, title) {
  const b = bounds(nodes, 60);
  const scale = 2;
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`);
  clone.setAttribute("width", b.w * scale);
  clone.setAttribute("height", b.h * scale);
  clone.querySelector(".mm-scene").removeAttribute("transform");
  clone.querySelectorAll(".mm-toggle").forEach((el) => el.remove());
  const bg = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  Object.entries({ x: b.x, y: b.y, width: b.w, height: b.h, fill: theme.panel }).forEach(([k, v]) => bg.setAttribute(k, v));
  clone.insertBefore(bg, clone.firstChild);

  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }));
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = b.w * scale;
    canvas.height = b.h * scale;
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    canvas.toBlob((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${title.replace(/[^\w-]+/g, "_").slice(0, 60) || "mindmap"}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    }, "image/png");
  };
  img.src = url;
}
