import { useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Spinner, useAsync } from "./ui.jsx";

// Shows a quiz, collects answers, submits, then shows the result per question.
export default function QuizRunner({ quiz, onDone }) {
  const [answers, setAnswers] = useState({});
  const [result, setResult] = useState(null);
  const { loading, error, run } = useAsync();
  const set = (qid, value) => setAnswers((a) => ({ ...a, [qid]: value }));
  const byId = Object.fromEntries((result?.results || []).map((r) => [r.question_id, r]));

  const submit = () =>
    run(async () => {
      const payload = quiz.questions.map((q) => ({ question_id: q.question_id, answer: answers[q.question_id] ?? "" }));
      const res = await api.submitQuiz(quiz.quiz_id, payload);
      setResult(res);
      onDone?.(res);
    });

  return (
    <div className="stack">
      {result && (
        <div className="card score">
          <div className="score-num">{result.percentage}%</div>
          <div>
            <b>{result.score} / {result.total}</b> points
            {!!result.weak_topics.length && <div className="muted">Needs work: {result.weak_topics.join(", ")}</div>}
          </div>
        </div>
      )}
      {quiz.questions.map((q, i) => {
        const r = byId[q.question_id];
        return (
          <div key={q.question_id} className={`card question ${r ? (r.correct ? "right" : "wrong") : ""}`}>
            <div className="q-head">
              <span className="tag">Q{i + 1}</span>
              <span className="chip soft">{q.type === "mcq" ? "Multiple choice" : "Short answer"}</span>
              <span className="chip soft">{q.difficulty}</span>
              {q.source && <span className="muted">p. {q.source.page}</span>}
            </div>
            <p className="q-text">{q.question}</p>
            {q.type === "mcq" ? (
              <div className="options">
                {q.options.map((o, idx) => (
                  <label key={idx} className={`option ${answers[q.question_id] === String(idx) ? "picked" : ""}`}>
                    <input type="radio" name={q.question_id} disabled={!!result} checked={answers[q.question_id] === String(idx)} onChange={() => set(q.question_id, String(idx))} />
                    {o}
                  </label>
                ))}
              </div>
            ) : (
              <textarea className="input" rows={3} disabled={!!result} placeholder="Your answer…" value={answers[q.question_id] || ""} onChange={(e) => set(q.question_id, e.target.value)} />
            )}
            {r && (
              <div className="feedback">
                <b>{r.correct ? "Correct" : "Not quite"}</b> ({Math.round(r.score * 100)}%). Answer: {r.correct_answer}
                <div className="muted">{r.explanation}</div>
              </div>
            )}
          </div>
        );
      })}
      {loading && <Spinner label="Marking…" />}
      <ErrorBox error={error} />
      {!result && <button className="btn" onClick={submit} disabled={loading}>Submit answers</button>}
    </div>
  );
}
