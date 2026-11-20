import { useRef, useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Spinner, useAsync } from "../components/ui.jsx";

export default function Library({ docs, refreshDocs, goTo }) {
  const input = useRef();
  const [drag, setDrag] = useState(false);
  const { loading, error, run } = useAsync();

  const upload = (file) => file && run(async () => { await api.uploadDocument(file); await refreshDocs(); });
  const remove = (id) => run(async () => { await api.deleteDocument(id); await refreshDocs(); });

  return (
    <div className="stack">
      <div
        className={`dropzone ${drag ? "drag" : ""}`}
        onClick={() => input.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]); }}
      >
        <div className="big">⬆</div>
        <div><b>Drop a lecture PDF or PPTX here</b> or click to choose</div>
        <div className="muted">Up to 25 MB. Text-based files work best.</div>
        <input ref={input} type="file" accept=".pdf,.pptx" hidden onChange={(e) => upload(e.target.files[0])} />
      </div>
      {loading && <Spinner label="Reading and indexing your document…" />}
      <ErrorBox error={error} />

      <div className="grid">
        {docs.map((d) => (
          <div key={d.document_id} className="card doc">
            <div className="doc-head">
              <span className="file-icon">{d.filename.endsWith(".pptx") ? "📊" : "📄"}</span>
              <div>
                <div className="doc-name">{d.filename}</div>
                <div className="muted">{d.pages} pages · {d.chunks} chunks · {d.status}</div>
              </div>
            </div>
            <div className="chips">{d.topics.map((t) => <span key={t} className="chip">{t}</span>)}</div>
            <div className="row">
              <button className="btn" onClick={() => goTo("ask")}>Ask questions</button>
              <button className="btn ghost" onClick={() => remove(d.document_id)}>Remove</button>
            </div>
          </div>
        ))}
        {!docs.length && <p className="muted">No documents yet. Upload one to get started.</p>}
      </div>
    </div>
  );
}
