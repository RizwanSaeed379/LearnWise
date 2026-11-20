import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { ErrorBox, Segmented, Spinner, useAsync } from "../components/ui.jsx";

// Graded mock exam: setup -> timed exam -> marked result with grade and feedback.
export default function Exam({ documentIds, topics }) {
  const [exam, setExam] = useState(null);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState([]);

  const loadHistory = () => api.examHistory().then((h) => setHistory(h.exams)).catch(() => {});
  useEffect(() => { loadHistory(); }, []);

  const reset = () => { setExam(null); setResult(null); };

  return (
    <div className="stack">
      {!exam && <ExamSetup topics={topics} documentIds={documentIds} onReady={setExam} />}
      {exam && !result && <ExamPaper exam={exam} onSubmitted={(r) => { setResult(r); loadHistory(); }} />}
      {result && <ExamResultView exam={exam} result={result} onRestart={reset} />}
      {!exam && !!history.length && <ExamHistoryTable history={history} />}
    </div>
  );
}

function ExamSetup({ topics, documentIds, onReady }) {
  const [picked, setPicked] = useState([]);
  const [difficulty, setDifficulty] = useState("adaptive");
  const [numMcq, setNumMcq] = useState(8);
  const [numShort, setNumShort] = useState(3);
  const [minutes, setMinutes] = useState(30);
  const { loading, error, run } = useAsync();
  const toggle = (t) => setPicked((p) => (p.includes(t) ? p.filter((x) => x !== t) : [...p, t]));

  const start = (e) => {
    e.preventDefault();
    run(async () => onReady(await api.exam({
      topics: picked.length ? picked : null,
      difficulty,
      num_mcq: numMcq,
      num_short: numShort,
      time_limit_minutes: minutes,
      document_ids: documentIds,
    })));
  };

  return (
    <form className="card stack" onSubmit={start}>
      <div>
        <h2>Graded mock exam</h2>
        <p className="muted">
          A timed test built from your documents. Leave topics empty and LearnWise picks them for you: weak topics
          first and with more questions, then topics you haven't been tested on. MCQs are 1 mark each; short answers
          are 3 marks and are marked against a reference answer.
        </p>
      </div>
      {!!topics.length && (
        <div>
          <div className="muted">Topics (optional)</div>
          <div className="chips">
            {topics.map((t) => (
              <button type="button" key={t} className={`chip ${picked.includes(t) ? "" : "soft"} clickable`} onClick={() => toggle(t)}>{t}</button>
            ))}
          </div>
        </div>
      )}
      <div className="controls">
        <Segmented options={["adaptive", "easy", "medium", "hard"]} value={difficulty} onChange={setDifficulty} />
        <label className="num">MCQs <input type="number" min={0} max={40} value={numMcq} onChange={(e) => setNumMcq(+e.target.value)} /></label>
        <label className="num">Short <input type="number" min={0} max={15} value={numShort} onChange={(e) => setNumShort(+e.target.value)} /></label>
        <label className="num">Minutes <input type="number" min={5} max={180} value={minutes} onChange={(e) => setMinutes(+e.target.value)} /></label>
      </div>
      {loading && <Spinner label="Building your exam paper…" />}
      <ErrorBox error={error} />
      <div><button className="btn" disabled={loading || numMcq + numShort === 0}>Start exam</button></div>
    </form>
  );
}

function ExamPaper({ exam, onSubmitted }) {
  const [answers, setAnswers] = useState({});
  const [left, setLeft] = useState(exam.time_limit_minutes * 60);
  const started = useRef(Date.now());
  const submitted = useRef(false);
  const { loading, error, run } = useAsync();
  const set = (qid, v) => setAnswers((a) => ({ ...a, [qid]: v }));
  const answered = exam.questions.filter((q) => (answers[q.question_id] ?? "").trim()).length;

  const submit = () => {
    if (submitted.current) return;
    submitted.current = true;
    run(async () => {
      const payload = exam.questions.map((q) => ({ question_id: q.question_id, answer: answers[q.question_id] ?? "" }));
      const secs = Math.round((Date.now() - started.current) / 1000);
      onSubmitted(await api.submitExam(exam.exam_id, payload, secs));
    }).finally(() => { submitted.current = false; });
  };

  // Countdown; submits automatically when time runs out.
  useEffect(() => {
    const t = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => { if (left === 0) submit(); }, [left]);

  const mm = String(Math.max(0, Math.floor(left / 60))).padStart(2, "0");
  const ss = String(Math.max(0, left % 60)).padStart(2, "0");

  return (
    <div className="stack">
      <div className="card exam-bar">
        <div>
          <h2>{exam.title}</h2>
          <div className="muted">{exam.questions.length} questions · {exam.total_marks} marks · {answered} answered</div>
        </div>
        <div className={`timer ${left < 60 ? "low" : ""}`}>⏱ {mm}:{ss}</div>
      </div>

      <div className="card">
        <h3>Why these topics</h3>
        {exam.plan.map((p) => (
          <div key={p.topic} className="plan-row">
            <b>{p.topic}</b>
            <span className="chip soft">{p.difficulty}</span>
            <span className="muted">{p.num_mcq} MCQ + {p.num_short} short · {p.reason}</span>
          </div>
        ))}
      </div>

      {exam.questions.map((q, i) => (
        <div key={q.question_id} className="card question">
          <div className="q-head">
            <span className="tag">Q{i + 1}</span>
            <span className="chip soft">{q.type === "mcq" ? "Multiple choice" : "Short answer"}</span>
            <span className="chip soft">{q.topic}</span>
            <span className="muted">[{q.marks} mark{q.marks === 1 ? "" : "s"}]</span>
          </div>
          <p className="q-text">{q.question}</p>
          {q.type === "mcq" ? (
            <div className="options">
              {q.options.map((o, idx) => (
                <label key={idx} className={`option ${answers[q.question_id] === String(idx) ? "picked" : ""}`}>
                  <input type="radio" name={q.question_id} checked={answers[q.question_id] === String(idx)} onChange={() => set(q.question_id, String(idx))} />
                  {o}
                </label>
              ))}
            </div>
          ) : (
            <textarea className="input" rows={4} placeholder="Write your answer…" value={answers[q.question_id] || ""} onChange={(e) => set(q.question_id, e.target.value)} />
          )}
        </div>
      ))}
      {loading && <Spinner label="Marking your exam…" />}
      <ErrorBox error={error} />
      <div><button className="btn" onClick={submit} disabled={loading}>Submit exam</button></div>
    </div>
  );
}

function ExamResultView({ exam, result, onRestart }) {
  return (
    <div className="stack">
      <div className="card score">
        <div className={`grade grade-${result.grade}`}>{result.grade}</div>
        <div>
          <div className="score-num">{result.percentage}%</div>
          <b>{result.marks_awarded} / {result.total_marks}</b> marks · {result.passed ? "Passed" : "Not passed"}
          {result.time_taken_seconds != null && (
            <div className="muted">
              Time: {Math.floor(result.time_taken_seconds / 60)}m {result.time_taken_seconds % 60}s of {exam.time_limit_minutes}m
              {result.over_time && " (over time)"}
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <h2>By topic</h2>
        {result.topic_scores.map((t) => (
          <div key={t.topic} className="bar-row">
            <span className="bar-label">{t.topic}</span>
            <div className="bar"><div className={`fill ${t.percentage < 60 ? "low" : ""}`} style={{ width: `${t.percentage}%` }} /></div>
            <span className="muted">{t.marks_awarded}/{t.marks_available}</span>
          </div>
        ))}
        {!!result.strengths.length && <p className="muted">Strong: {result.strengths.join(", ")}</p>}
      </div>

      <div className="card explain">
        <h2>What to do next</h2>
        <ul>{result.recommendations.map((r) => <li key={r}>{r}</li>)}</ul>
      </div>

      {result.results.map((r, i) => (
        <div key={r.question_id} className={`card question ${r.correct ? "right" : "wrong"}`}>
          <div className="q-head">
            <span className="tag">Q{i + 1}</span>
            <span className="chip soft">{r.topic}</span>
            <b>{r.marks_awarded} / {r.marks_available}</b>
          </div>
          <p className="q-text">{r.question}</p>
          <div className="feedback">
            <div><b>Your answer:</b> {r.your_answer || <i>(blank)</i>}</div>
            <div><b>{r.type === "mcq" ? "Correct answer" : "Model answer"}:</b> {r.correct_answer}</div>
            <div className="muted">{r.feedback}</div>
            {!!r.missing_points.length && <div className="muted">Missing: {r.missing_points.join("; ")}</div>}
          </div>
        </div>
      ))}
      <div><button className="btn" onClick={onRestart}>Take another exam</button></div>
    </div>
  );
}

function ExamHistoryTable({ history }) {
  return (
    <div className="card">
      <h2>Past exams</h2>
      <table className="table">
        <tbody>
          {history.map((h) => (
            <tr key={h.exam_id}>
              <td>{h.title.replace("Mock exam: ", "")}</td>
              <td><b>{h.grade}</b></td>
              <td>{h.percentage}%</td>
              <td className="muted">{h.marks_awarded}/{h.total_marks}</td>
              <td className="muted">{new Date(h.taken_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
