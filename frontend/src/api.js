// All backend calls live here. Shapes follow docs/API_CONTRACT.md.
export const USER_ID = "demo";

async function request(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: options.body instanceof FormData ? {} : { "Content-Type": "application/json" },
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    // Contract: every error is { error: { code, message } }
    throw new Error(data?.error?.message || `Request failed (${res.status})`);
  }
  return data;
}

const post = (path, body) => request(path, { method: "POST", body: JSON.stringify(body) });

// Audio for an answer from the AI voice. Throws with .status 501 when the AI voice is off (use the browser's).
async function speech(text) {
  const res = await fetch("/api/speech", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    const err = new Error(data?.error?.message || `Voice failed (${res.status})`);
    err.status = res.status;
    throw err;
  }
  return res.blob();
}

export const api = {
  health: () => request("/api/health"),
  speech,
  listDocuments: () => request("/api/documents"),
  uploadDocument: (file) => {
    const form = new FormData();
    form.append("file", file);
    return request("/api/documents", { method: "POST", body: form });
  },
  deleteDocument: (id) => request(`/api/documents/${id}`, { method: "DELETE" }),
  ask: (question, documentIds, history = []) => post("/api/ask", { question, document_ids: documentIds, history }),
  notes: (topic, style, documentIds) => post("/api/notes", { topic, style, document_ids: documentIds }),
  quiz: (params) => post("/api/quiz", { user_id: USER_ID, ...params }),
  submitQuiz: (quizId, answers) => post(`/api/quiz/${quizId}/submit`, { user_id: USER_ID, answers }),
  exam: (params) => post("/api/exam", { user_id: USER_ID, ...params }),
  submitExam: (examId, answers, timeTakenSeconds) => post(`/api/exam/${examId}/submit`, { user_id: USER_ID, answers, time_taken_seconds: timeTakenSeconds }),
  examResult: (examId) => request(`/api/exam/${examId}/result`),
  examHistory: () => request(`/api/exam/history/${USER_ID}`),
  mindmap: (topic, maxNodes, documentIds) => post("/api/mindmap", { topic, max_nodes: maxNodes, document_ids: documentIds }),
  flashcards: (topic, count, documentIds) => post("/api/flashcards", { topic, count, document_ids: documentIds }),
  progress: () => request(`/api/progress/${USER_ID}`),
  practice: (params = {}) => post("/api/practice", { user_id: USER_ID, ...params }),
};
