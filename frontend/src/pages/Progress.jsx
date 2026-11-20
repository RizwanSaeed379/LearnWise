import { useEffect, useState } from "react";
import { api } from "../api.js";
import QuizRunner from "../components/QuizRunner.jsx";
import { ErrorBox, Spinner, useAsync } from "../components/ui.jsx";

export default function Progress() {
  const [progress, setProgress] = useState(null);
  const [practice, setPractice] = useState(null);
  const { loading, error, run } = useAsync();

  const load = () => api.progress().then(setProgress).catch(() => {});
  useEffect(() => { load(); }, []);

  const startPractice = () => run(async () => setPractice(await api.practice({ max_topics: 2, questions_per_topic: 3 })));

  return (
    <div className="stack">
      <div className="card">
        <div className="row spread">
          <h2>Mastery by topic</h2>
          <button className="btn" onClick={startPractice} disabled={loading}>Practise my weak topics</button>
        </div>
        {!progress?.topics.length && <p className="muted">Take a quiz to start tracking your progress.</p>}
        {progress?.topics.map((t) => (
          <div key={t.topic} className="bar-row">
            <span className="bar-label">{t.topic}</span>
            <div className="bar"><div className={`fill ${t.mastery < 0.6 ? "low" : ""}`} style={{ width: `${t.mastery * 100}%` }} /></div>
            <span className="muted">{Math.round(t.mastery * 100)}%</span>
          </div>
        ))}
      </div>

      {!!progress?.recent_quizzes.length && (
        <div className="card">
          <h2>Recent quizzes</h2>
          <table className="table">
            <tbody>
              {progress.recent_quizzes.map((q) => (
                <tr key={q.quiz_id}><td>{q.topic}</td><td>{q.difficulty}</td><td>{q.percentage}%</td><td className="muted">{new Date(q.taken_at).toLocaleString()}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loading && <Spinner label="Picking your weak topics…" />}
      <ErrorBox error={error} />
      {practice && (
        <>
          {practice.selected.map((s) => (
            <div key={s.topic} className="card explain">
              <h3>{s.topic} <span className="chip soft">{s.reason}</span></h3>
              <p>{s.explanation}</p>
            </div>
          ))}
          <QuizRunner key={practice.quiz.quiz_id} quiz={practice.quiz} onDone={load} />
        </>
      )}
    </div>
  );
}
