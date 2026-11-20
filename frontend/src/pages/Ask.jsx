import { useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Sources, Spinner, useAsync } from "../components/ui.jsx";

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
          <div key={i} className={`bubble ${m.role}`}>
            <p>{m.text}</p>
            {m.role === "bot" && !m.grounded && <p className="muted">Not found in your documents.</p>}
            {m.sources && <Sources sources={m.sources} />}
          </div>
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
