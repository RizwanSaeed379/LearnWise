import { useState } from "react";

export function ErrorBox({ error }) {
  return error ? <div className="error">⚠ {error}</div> : null;
}

export function Spinner({ label = "Thinking…" }) {
  return (
    <div className="spinner">
      <span className="dot" /> {label}
    </div>
  );
}

// Free-text topic with suggestions taken from the uploaded documents.
export function TopicInput({ value, onChange, topics }) {
  return (
    <>
      <input list="topic-list" className="input" placeholder="Topic, e.g. Backpropagation" value={value} onChange={(e) => onChange(e.target.value)} />
      <datalist id="topic-list">
        {topics.map((t) => <option key={t} value={t} />)}
      </datalist>
    </>
  );
}

export function Segmented({ options, value, onChange }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button key={o} type="button" className={o === value ? "on" : ""} onClick={() => onChange(o)}>{o}</button>
      ))}
    </div>
  );
}

// Answer text with [S1], [S2] ... turned into clickable tags that open the matching source.
export function CitedText({ text, sources, onCite }) {
  const parts = text.split(/(\[S\d+\])/g);
  return (
    <p>
      {parts.map((part, i) => {
        const m = part.match(/^\[S(\d+)\]$/);
        const src = m && sources?.[+m[1] - 1];
        if (!src) return <span key={i}>{part}</span>;
        return (
          <button key={i} type="button" className="cite" title={`${src.filename}, page ${src.page}`} onClick={() => onCite?.(+m[1] - 1)}>
            S{m[1]} · p.{src.page}
          </button>
        );
      })}
    </p>
  );
}

export function Sources({ sources, open: openProp, setOpen: setOpenProp }) {
  const [openLocal, setOpenLocal] = useState(null);
  const open = openProp !== undefined ? openProp : openLocal;
  const setOpen = setOpenProp || setOpenLocal;
  if (!sources?.length) return null;
  return (
    <div className="sources">
      <div className="sources-title">Sources</div>
      {sources.map((s, i) => (
        <div key={s.chunk_id} className="source" onClick={() => setOpen(open === i ? null : i)}>
          <span className="tag">S{i + 1}</span>
          <span>{s.filename} · page {s.page}</span>
          <span className="muted">{Math.round(s.score * 100)}% match</span>
          {open === i && <p className="snippet">“{s.snippet}”</p>}
        </div>
      ))}
    </div>
  );
}

// Hook that wraps an async call with loading + error state.
export function useAsync() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const run = async (fn) => {
    setLoading(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };
  return { loading, error, run };
}
