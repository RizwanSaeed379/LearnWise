import { useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Spinner, TopicInput, useAsync } from "../components/ui.jsx";

export default function Flashcards({ documentIds, topics, initialTopic }) {
  const [topic, setTopic] = useState(initialTopic || "");
  const [count, setCount] = useState(8);
  const [cards, setCards] = useState([]);
  const [i, setI] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const { loading, error, run } = useAsync();

  const generate = (e) => {
    e.preventDefault();
    run(async () => {
      const res = await api.flashcards(topic, count, documentIds);
      setCards(res.cards);
      setI(0);
      setFlipped(false);
    });
  };
  const move = (d) => { setFlipped(false); setI((x) => (x + d + cards.length) % cards.length); };
  const card = cards[i];

  return (
    <div className="stack">
      <form className="card controls" onSubmit={generate}>
        <TopicInput value={topic} onChange={setTopic} topics={topics} />
        <label className="num">Cards <input type="number" min={1} max={30} value={count} onChange={(e) => setCount(+e.target.value)} /></label>
        <button className="btn" disabled={loading || topic.length < 2}>Make flashcards</button>
      </form>
      {loading && <Spinner label="Making cards…" />}
      <ErrorBox error={error} />
      {card && (
        <div className="flash-wrap">
          <div className={`flashcard ${flipped ? "flipped" : ""}`} onClick={() => setFlipped(!flipped)}>
            <div className="face front">{card.front}</div>
            <div className="face back">
              {card.back}
              {card.source && <div className="muted small">{card.source.filename} · p. {card.source.page}</div>}
            </div>
          </div>
          <div className="row center">
            <button className="btn ghost" onClick={() => move(-1)}>← Prev</button>
            <span className="muted">{i + 1} / {cards.length} · click card to flip</span>
            <button className="btn ghost" onClick={() => move(1)}>Next →</button>
          </div>
        </div>
      )}
    </div>
  );
}
