import { useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Segmented, Sources, Spinner, TopicInput, useAsync } from "../components/ui.jsx";

export default function Notes({ documentIds, topics }) {
  const [topic, setTopic] = useState("");
  const [style, setStyle] = useState("concise");
  const [notes, setNotes] = useState(null);
  const { loading, error, run } = useAsync();

  const generate = (e) => {
    e.preventDefault();
    run(async () => setNotes(await api.notes(topic, style, documentIds)));
  };

  return (
    <div className="stack">
      <form className="card controls" onSubmit={generate}>
        <TopicInput value={topic} onChange={setTopic} topics={topics} />
        <Segmented options={["concise", "detailed", "exam"]} value={style} onChange={setStyle} />
        <button className="btn" disabled={loading || topic.length < 2}>Generate notes</button>
      </form>
      {loading && <Spinner label="Writing your notes…" />}
      <ErrorBox error={error} />
      {notes && (
        <article className="card notes">
          <h2>{notes.title} <span className="chip">{notes.style}</span></h2>
          {notes.sections.map((s) => (
            <section key={s.heading}>
              <h3>{s.heading}</h3>
              {s.content && <p>{s.content}</p>}
              {!!s.bullets.length && <ul>{s.bullets.map((b) => <li key={b}>{b}</li>)}</ul>}
              {!!s.key_terms.length && <div className="chips">{s.key_terms.map((k) => <span key={k} className="chip soft">{k}</span>)}</div>}
            </section>
          ))}
          <Sources sources={notes.sources} />
        </article>
      )}
    </div>
  );
}
