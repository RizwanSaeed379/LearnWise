import { useState } from "react";
import { api } from "../api.js";
import { CitedText, ErrorBox, Sources, Spinner, useAsync } from "../components/ui.jsx";

export default function Ask({ documentIds }) {
  const [question, setQuestion] = useState("");
  const [chat, setChat] = useState([]);
  const { loading, error, run } = useAsync();

  const send = (e) => {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3) return;
    setQuestion("");
    setChat((c) => [...c, { role: "user", text: q }]);
    run(async () => {
      const res = await api.ask(q, documentIds);
      setChat((c) => [...c, { role: "bot", text: res.answer, sources: res.sources, grounded: res.grounded }]);
    });
  };

  return (
    <div className="chat">
      <div className="messages">
        {!chat.length && <p className="muted center">Ask anything about your uploaded material. Answers cite the pages they come from.</p>}
        {chat.map((m, i) => (
          <BotOrUser key={i} m={m} />
        ))}
        {loading && <Spinner label="Searching your documents…" />}
        <ErrorBox error={error} />
      </div>
      <form className="composer" onSubmit={send}>
        <input className="input" placeholder="e.g. What is backpropagation?" value={question} onChange={(e) => setQuestion(e.target.value)} />
        <button className="btn" disabled={loading}>Ask</button>
      </form>
    </div>
  );
}

function BotOrUser({ m }) {
  const [open, setOpen] = useState(null);
  if (m.role === "user") return <div className="bubble user"><p>{m.text}</p></div>;
  return (
    <div className="bubble bot">
      <CitedText text={m.text} sources={m.sources} onCite={(i) => setOpen(open === i ? null : i)} />
      {!m.grounded && (
        <p className="muted">
          {m.sources?.length ? "Couldn't fully verify this answer against your documents. Check the cited pages." : "Not found in your documents."}
        </p>
      )}
      <Sources sources={m.sources} open={open} setOpen={setOpen} />
    </div>
  );
}
