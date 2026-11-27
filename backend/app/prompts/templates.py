"""Prompt templates (owner: Sana).

Each builder returns a list of chat messages for LLMClient.chat / chat_json.
Rules that every prompt follows:
  * use ONLY the CONTEXT passages; say so if the answer is not there (grounding)
  * cite passages as [S1], [S2] ... (so we can map them back to pages)
  * for structured tasks, reply with JSON matching the shape shown (structured generation)
  * one short example of the JSON (few-shot) to fix the format
"""
import json

SYSTEM = (
    "You are LearnWise, a study assistant for university students. "
    "You only use the course material given in CONTEXT. If the context does not contain "
    "the answer, say you could not find it in the uploaded material. Be accurate and clear."
)


def _msgs(user: str) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def ask_prompt(question: str, context: str) -> list[dict[str, str]]:
    return _msgs(
        f"CONTEXT:\n{context}\n\nQUESTION: {question}\n\n"
        "Answer in 1-4 short sentences for a student.\n"
        "Rules:\n"
        "- Every sentence must state a fact that is written in the CONTEXT. Reuse the passage's own words "
        "where you can.\n"
        "- Do NOT add background knowledge, examples, benefits or consequences that the CONTEXT does not state, "
        "even if they are true. Stop when the CONTEXT has nothing more to say.\n"
        "- End every sentence with the passage it came from, like [S1].\n"
        "- Do not write sentences about the passages themselves (no 'as described in [S1]' or 'the passage explains').\n"
        "If the context is not relevant, reply exactly: NOT_FOUND"
    )


NOTE_STYLES = {
    "concise": "short revision notes: 3-5 sections, each 1-2 sentences plus up to 4 bullets",
    "detailed": "detailed study notes: 4-7 sections with explanations, definitions and an example each",
    "exam": "exam-focused notes: key definitions, formulas, likely exam questions and common mistakes",
}

NOTES_EXAMPLE = {
    "title": "Gradient Descent",
    "sections": [
        {
            "heading": "Definition",
            "content": "An iterative method that moves parameters against the gradient to reduce the loss [S1].",
            "bullets": ["Update: w = w - lr * dL/dw"],
            "key_terms": ["learning rate", "loss"],
        }
    ],
}


def notes_prompt(topic: str, style: str, context: str) -> list[dict[str, str]]:
    return _msgs(
        f"CONTEXT:\n{context}\n\nTOPIC: {topic}\n"
        f"Write {NOTE_STYLES[style]}.\n"
        f"Reply with ONLY JSON in this shape:\n{json.dumps(NOTES_EXAMPLE)}"
    )


QUIZ_EXAMPLE = {
    "questions": [
        {
            "type": "mcq",
            "question": "What does the learning rate control in gradient descent?",
            "options": ["The step size", "The number of layers", "The batch order", "The activation function"],
            "answer": "0",
            "explanation": "The learning rate scales each update step [S1].",
            "source": "S1",
        },
        {
            "type": "short",
            "question": "Why can a very large learning rate prevent convergence?",
            "options": None,
            "answer": "Steps overshoot the minimum, so the loss oscillates or diverges.",
            "explanation": "Large steps jump past the minimum [S1].",
            "source": "S1",
        },
    ]
}

DIFFICULTY_GUIDE = {
    "easy": "recall of definitions and facts",
    "medium": "understanding and applying concepts",
    "hard": "analysis, comparison and multi-step reasoning",
}


def quiz_prompt(topic: str, difficulty: str, num_mcq: int, num_short: int, context: str) -> list[dict[str, str]]:
    return _msgs(
        f"CONTEXT:\n{context}\n\nTOPIC: {topic}\nDIFFICULTY: {difficulty} ({DIFFICULTY_GUIDE[difficulty]})\n"
        f"Write {num_mcq} multiple-choice questions (exactly 4 options, 'answer' is the index of the correct "
        f"option as a string) and {num_short} short-answer questions. Each needs an explanation and the "
        f"source passage label.\n"
        f"Rules: every question must be about the TOPIC. The correct answer (and the short-answer reference "
        f"answer) must be a fact written in the CONTEXT, using the passage's own key words, not outside "
        f"knowledge. 'source' must be the label of the passage that states that answer.\nReply with ONLY JSON in this shape:\n{json.dumps(QUIZ_EXAMPLE)}"
    )


FLASHCARD_EXAMPLE = {"cards": [{"front": "What is a learning rate?", "back": "The step size of each gradient update.", "source": "S1"}]}


def flashcards_prompt(topic: str, count: int, context: str) -> list[dict[str, str]]:
    return _msgs(
        f"CONTEXT:\n{context}\n\nTOPIC: {topic}\n"
        f"Create {count} flashcards. Front: a short question or term. Back: an answer under 30 words.\n"
        f"Reply with ONLY JSON in this shape:\n{json.dumps(FLASHCARD_EXAMPLE)}"
    )


def grade_short_prompt(question: str, reference: str, student: str) -> list[dict[str, str]]:
    return _msgs(
        f"QUESTION: {question}\nREFERENCE ANSWER: {reference}\nSTUDENT ANSWER: {student}\n"
        'Grade the student answer. Reply with ONLY JSON: {"score": 0.0-1.0, "feedback": "one sentence"}'
    )


def explain_prompt(topic: str, context: str) -> list[dict[str, str]]:
    return _msgs(
        f"CONTEXT:\n{context}\n\nThe student is struggling with: {topic}.\n"
        "Explain it again in simpler words, in 3-5 sentences, with one everyday analogy."
    )


EXAM_GRADE_EXAMPLE = {
    "score": 0.67,
    "feedback": "You explained that the steps overshoot, but did not say the loss can diverge.",
    "missing_points": ["the loss can diverge"],
}


def exam_grade_prompt(question: str, reference: str, student: str, marks: float) -> list[dict[str, str]]:
    """Strict, rubric-style marking for the graded mock exam (short answers)."""
    return _msgs(
        f"You are marking a university mock exam. The question is worth {marks:g} marks.\n"
        f"QUESTION: {question}\nREFERENCE ANSWER: {reference}\nSTUDENT ANSWER: {student or '(blank)'}\n\n"
        "Grade the student answer against the key points of the reference answer. Give credit for correct "
        "ideas in different words; give no credit for vague, off-topic or blank answers.\n"
        "score = fraction of the key points the student covered (0.0 to 1.0).\n"
        "feedback = one or two sentences the student can learn from.\n"
        "missing_points = short phrases for key points they left out (empty list if none).\n"
        f"Reply with ONLY JSON in this shape:\n{json.dumps(EXAM_GRADE_EXAMPLE)}"
    )
