import { useState } from "react";
import { api } from "../api.js";
import SpeakButton from "../components/SpeakButton.jsx";
import { CitedText, ErrorBox, Segmented, Sources, Spinner, TopicInput, useAsync } from "../components/ui.jsx";

// What the voice reads for one section: heading, text, bullets, key terms (citations are dropped when speaking).
const sectionText = (s) =>
  [s.heading + ".", s.content, ...s.bullets.map((b) => (/[.!?]$/.test(b) ? b : b + ".")), s.key_terms.length ? `Key terms: ${s.key_terms.join(", ")}.` : ""]
    .filter(Boolean)
    .join(" ");

export default function Notes({ documentIds, topics, initialTopic }) {
  const [topic, setTopic] = useState(initialTopic || "");
  const [style, setStyle] = useState("concise");
  const [notes, setNotes] = useState(null);
  const [open, setOpen] = useState(null);
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
          <div className="row spread">
            <h2>{notes.title} <span className="chip">{notes.style}</span></h2>
            <SpeakButton parts={[`${notes.title}.`, ...notes.sections.map(sectionText)]} label="Listen to notes" />
          </div>
          {notes.sections.map((s) => (
            <section key={s.heading}>
              <div className="row section-head">
                <h3>{s.heading}</h3>
                <SpeakButton parts={[sectionText(s)]} label="" compact />
              </div>
              {s.content && <CitedText text={s.content} sources={notes.sources} onCite={setOpen} />}
              {!!s.bullets.length && <ul>{s.bullets.map((b) => <li key={b}>{b}</li>)}</ul>}
              {!!s.key_terms.length && <div className="chips">{s.key_terms.map((k) => <span key={k} className="chip soft">{k}</span>)}</div>}
            </section>
          ))}
          <Sources sources={notes.sources} open={open} setOpen={setOpen} />
        </article>
      )}
    </div>
  );
}
