import { useState } from "react";
import { api } from "../api.js";
import QuizRunner from "../components/QuizRunner.jsx";
import { ErrorBox, Segmented, Spinner, TopicInput, useAsync } from "../components/ui.jsx";

export default function Quiz({ documentIds, topics, initialTopic }) {
  const [topic, setTopic] = useState(initialTopic || "");
  const [difficulty, setDifficulty] = useState("medium");
  const [numMcq, setNumMcq] = useState(4);
  const [numShort, setNumShort] = useState(1);
  const [quiz, setQuiz] = useState(null);
  const { loading, error, run } = useAsync();

  const generate = (e) => {
    e.preventDefault();
    setQuiz(null);
    run(async () => setQuiz(await api.quiz({ topic, difficulty, num_mcq: numMcq, num_short: numShort, document_ids: documentIds })));
  };

  return (
    <div className="stack">
      <form className="card controls" onSubmit={generate}>
        <TopicInput value={topic} onChange={setTopic} topics={topics} />
        <Segmented options={["easy", "medium", "hard"]} value={difficulty} onChange={setDifficulty} />
        <label className="num">MCQs <input type="number" min={0} max={20} value={numMcq} onChange={(e) => setNumMcq(+e.target.value)} /></label>
        <label className="num">Short <input type="number" min={0} max={10} value={numShort} onChange={(e) => setNumShort(+e.target.value)} /></label>
        <button className="btn" disabled={loading || topic.length < 2}>Generate quiz</button>
      </form>
      {loading && <Spinner label="Writing questions…" />}
      <ErrorBox error={error} />
      {quiz && <QuizRunner key={quiz.quiz_id} quiz={quiz} />}
    </div>
  );
}
