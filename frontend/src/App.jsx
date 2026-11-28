import { useEffect, useState } from "react";
import { api } from "./api.js";
import Library from "./pages/Library.jsx";
import Ask from "./pages/Ask.jsx";
import Notes from "./pages/Notes.jsx";
import Quiz from "./pages/Quiz.jsx";
import Exam from "./pages/Exam.jsx";
import Flashcards from "./pages/Flashcards.jsx";
import MindMap from "./pages/MindMap.jsx";
import Progress from "./pages/Progress.jsx";

const PAGES = [
  { id: "library", label: "Library", icon: "📚", component: Library },
  { id: "ask", label: "Ask", icon: "💬", component: Ask },
  { id: "notes", label: "Notes", icon: "📝", component: Notes },
  { id: "mindmap", label: "Mind map", icon: "🧠", component: MindMap },
  { id: "quiz", label: "Quiz", icon: "✅", component: Quiz },
  { id: "exam", label: "Mock exam", icon: "🎓", component: Exam },
  { id: "flashcards", label: "Flashcards", icon: "🃏", component: Flashcards },
  { id: "progress", label: "Progress", icon: "📈", component: Progress },
];

export default function App() {
  const [page, setPage] = useState("library");
  const [docs, setDocs] = useState([]);
  const [scope, setScope] = useState("all"); // "all" or a document_id
  const [health, setHealth] = useState(null);
  // goTo("quiz", "Backpropagation") opens a page with its topic filled in (used by the mind map)
  const [nav, setNav] = useState({ topic: null, n: 0 });
  const goTo = (id, topic = null) => {
    setPage(id);
    setNav((v) => ({ topic, n: v.n + 1 }));
  };

  const refreshDocs = () => api.listDocuments().then((d) => setDocs(d.documents)).catch(() => {});

  useEffect(() => {
    refreshDocs();
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);

  const documentIds = scope === "all" ? null : [scope];
  const scopedDocs = scope === "all" ? docs : docs.filter((d) => d.document_id === scope);
  const topics = [...new Set(scopedDocs.flatMap((d) => d.topics))];
  const Current = PAGES.find((p) => p.id === page).component;

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <span className="logo">L</span> LearnWise
        </div>
        <nav>
          {PAGES.map((p) => (
            <button key={p.id} className={`nav-item ${page === p.id ? "active" : ""}`} onClick={() => goTo(p.id)}>
              <span>{p.icon}</span> {p.label}
            </button>
          ))}
        </nav>
        <HealthBadge health={health} />
      </aside>

      <main className="main">
        <header className="topbar">
          <h1>{PAGES.find((p) => p.id === page).label}</h1>
          {page !== "library" && page !== "progress" && (
            <label className="scope">
              Study from
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="all">All documents ({docs.length})</option>
                {docs.map((d) => (
                  <option key={d.document_id} value={d.document_id}>{d.filename}</option>
                ))}
              </select>
            </label>
          )}
        </header>
        <section className={`content ${page === "mindmap" ? "wide" : ""}`}>
          <Current key={`${page}-${nav.n}`} docs={docs} refreshDocs={refreshDocs} documentIds={documentIds} topics={topics} goTo={goTo} initialTopic={nav.topic} />
        </section>
      </main>
    </div>
  );
}

function HealthBadge({ health }) {
  if (!health) return <div className="health">Checking backend…</div>;
  if (health.status !== "ok") return <div className="health bad">● Backend offline</div>;
  if (health.mock_mode) return <div className="health warn">● Mock mode</div>;
  const embOk = health.embedding_mode !== "remote" || health.embeddings_reachable;
  return (
    <div className={`health ${health.llm_reachable && embOk ? "ok" : "bad"}`} title={`${health.llm_base_url}\nembeddings: ${health.embedding_mode} (${health.embedding_model})`}>
      ● {health.llm_model} {health.llm_reachable ? "online" : "unreachable"}
      {!embOk && <div>● embeddings unreachable</div>}
    </div>
  );
}
