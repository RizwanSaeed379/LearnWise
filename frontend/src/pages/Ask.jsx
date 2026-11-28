import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import SpeakButton from "../components/SpeakButton.jsx";
import { CitedText, ErrorBox, Sources, Spinner, useAsync } from "../components/ui.jsx";

// Follow-up memory: the last few exchanges go with each question, so "why is that?" works.
// The backend uses them only to understand the question; answers still come from your documents.
const MEMORY_TURNS = 3;
// Kept while the app is open, so switching to Notes and back doesn't lose the conversation.
const saved = { chat: [] };

export default function Ask({ documentIds, initialTopic }) {
  const [question, setQuestion] = useState(initialTopic ? `Explain ${initialTopic}` : "");
  const [chat, setChat] = useState(saved.chat);
  const { loading, error, run } = useAsync();
  const bottom = useRef(null);

  useEffect(() => {
    saved.chat = chat;
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chat, loading]);

  const history = () => {
    const turns = [];
    for (let i = 0; i < chat.length - 1; i++) {
      if (chat[i].role === "user" && chat[i + 1].role === "bot") turns.push({ question: chat[i].text, answer: chat[i + 1].text });
    }
    return turns.slice(-MEMORY_TURNS);
  };

  const send = (e) => {
    e.preventDefault();
    const q = question.trim();
    if (q.length < 3) return;
    const turns = history();
    setQuestion("");
    setChat((c) => [...c, { role: "user", text: q }]);
    run(async () => {
      const res = await api.ask(q, documentIds, turns);
      setChat((c) => [...c, { role: "bot", text: res.answer, sources: res.sources, grounded: res.grounded, searched: res.search_query }]);
    });
  };

  return (
    <div className="chat">
      <div className="messages">
        {!chat.length && (
          <div className="muted center">
            <p>Ask anything about your uploaded material. Answers cite the pages they come from.</p>
            <p>Follow-ups work too: ask “What is photolysis?”, then “Why is it important?”</p>
          </div>
        )}
        {chat.map((m, i) => (
          <BotOrUser key={i} m={m} />
        ))}
        {loading && <Spinner label="Searching your documents…" />}
        <ErrorBox error={error} />
        <div ref={bottom} />
      </div>
      <form className="composer" onSubmit={send}>
        {!!chat.length && (
          <button type="button" className="btn ghost" title="Start over: earlier questions are forgotten" onClick={() => setChat([])} disabled={loading}>
            New chat
          </button>
        )}
        <input className="input" placeholder={chat.length ? "Ask a follow-up, or a new question" : "e.g. What is backpropagation?"} value={question} onChange={(e) => setQuestion(e.target.value)} />
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
      {m.searched && <div className="searched" title="Your follow-up, rewritten so it could be searched on its own">🔎 Searched for: {m.searched}</div>}
      <CitedText text={m.text} sources={m.sources} onCite={(i) => setOpen(open === i ? null : i)} />
      <SpeakButton text={m.text} />
      {!m.grounded && (
        <p className="muted">
          {m.sources?.length ? "Couldn't fully verify this answer against your documents. Check the cited pages." : "Not found in your documents."}
        </p>
      )}
      <Sources sources={m.sources} open={open} setOpen={setOpen} />
    </div>
  );
}
