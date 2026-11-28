"""Fake data used when USE_MOCKS=true, so the frontend works before the AI is ready."""
import uuid

from app.schemas import (
    DocumentInfo,
    Flashcard,
    MindMapLink,
    MindMapNode,
    MindMapResponse,
    NoteSection,
    QuizQuestion,
    SourceRef,
)
from app.services import store

SAMPLE_DOC_ID = "doc_sample01"


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def seed() -> None:
    if SAMPLE_DOC_ID not in store.documents:
        store.documents[SAMPLE_DOC_ID] = DocumentInfo(
            document_id=SAMPLE_DOC_ID,
            filename="Lecture3_NeuralNetworks.pdf",
            pages=24,
            chunks=61,
            topics=["Perceptron", "Activation functions", "Backpropagation", "Gradient descent", "Overfitting"],
            status="ready",
            uploaded_at=store.now(),
        )


def fake_document(filename: str) -> DocumentInfo:
    return DocumentInfo(
        document_id=_id("doc"),
        filename=filename,
        pages=12,
        chunks=30,
        topics=["Introduction", "Key concepts", "Worked example", "Summary"],
        status="ready",
        uploaded_at=store.now(),
    )


def sources(n: int = 2) -> list[SourceRef]:
    doc = store.documents.get(SAMPLE_DOC_ID)
    filename = doc.filename if doc else "Lecture3_NeuralNetworks.pdf"
    passages = [
        (7, "Backpropagation applies the chain rule to compute the gradient of the loss with respect to every weight, layer by layer from the output back to the input."),
        (8, "The computed gradients are then used by gradient descent to update each weight: w = w - learning_rate * dL/dw."),
        (12, "Overfitting happens when a model memorises training data; regularisation and dropout reduce it."),
    ]
    return [
        SourceRef(document_id=SAMPLE_DOC_ID, filename=filename, page=p, chunk_id=f"{SAMPLE_DOC_ID}_c{p:03d}", snippet=t, score=round(0.86 - i * 0.07, 2))
        for i, (p, t) in enumerate(passages[:n])
    ]


def answer(question: str) -> str:
    return (
        f"(mock answer to: \"{question}\") Backpropagation is the algorithm that computes how much each weight "
        "contributed to the error by applying the chain rule from the output layer backwards [S1]. "
        "Those gradients are then used by gradient descent to update the weights [S2]."
    )


def notes(topic: str, style: str) -> list[NoteSection]:
    base = [
        NoteSection(heading=f"What is {topic}?", content=f"(mock {style} notes) {topic} is a core idea from the lecture [S1].", bullets=["Defined on page 7", "Builds on the chain rule"], key_terms=[topic.lower(), "gradient"]),
        NoteSection(heading="How it works", content="Errors flow backwards through the network and weights are updated [S2].", bullets=["Forward pass computes the output", "Backward pass computes gradients", "Update step changes the weights"], key_terms=["forward pass", "backward pass"]),
    ]
    if style in ("detailed", "exam"):
        base.append(NoteSection(heading="Worked example", content="For a single neuron with squared error, dL/dw = (y_hat - y) * x.", bullets=[], key_terms=["squared error"]))
    if style == "exam":
        base.append(NoteSection(heading="Likely exam questions", content="", bullets=["Derive the weight update for one neuron.", "Explain why gradients can vanish in deep networks."], key_terms=[]))
    return base


def quiz_questions(topic: str, difficulty: str, num_mcq: int, num_short: int) -> tuple[list[QuizQuestion], dict[str, tuple[str, str]]]:
    src = sources(1)[0]
    mcq_bank = [
        ("Which rule does backpropagation rely on?", ["Chain rule", "Bayes' rule", "Product rule only", "L'Hopital's rule"], "0", "Backprop applies the chain rule layer by layer [S1]."),
        ("What does the learning rate control?", ["Number of layers", "Step size of each update", "Batch order", "Dataset size"], "1", "It scales the gradient in the update step [S2]."),
        ("Which technique reduces overfitting?", ["Adding more epochs", "Removing validation data", "Dropout", "Larger learning rate"], "2", "Dropout is a regulariser [S3]."),
        ("In which direction are gradients propagated?", ["Input to output", "Randomly", "Only in the first layer", "Output to input"], "3", "Gradients flow from the output back to the input [S1]."),
    ]
    questions, keys = [], {}
    for i in range(num_mcq):
        q, opts, ans, expl = mcq_bank[i % len(mcq_bank)]
        qid = _id("q")
        questions.append(QuizQuestion(question_id=qid, type="mcq", question=q, options=opts, topic=topic, difficulty=difficulty, source=src))
        keys[qid] = (ans, expl)
    for _ in range(num_short):
        qid = _id("q")
        questions.append(QuizQuestion(question_id=qid, type="short", question=f"In one or two sentences, explain {topic}.", options=None, topic=topic, difficulty=difficulty, source=src))
        keys[qid] = (f"{topic} uses the chain rule to compute gradients that update the weights.", "A good answer mentions gradients, the chain rule and weight updates.")
    return questions, keys


def grade_short(reference: str, student: str) -> float:
    """Mock grader: share of reference keywords the student used. The real one asks the LLM."""
    ref = {w for w in reference.lower().split() if len(w) > 4}
    got = {w for w in student.lower().split() if len(w) > 4}
    return round(len(ref & got) / len(ref), 2) if ref else 0.0


def flashcards(topic: str, count: int) -> list[Flashcard]:
    bank = [
        ("Backpropagation", "Algorithm that computes weight gradients using the chain rule, from output to input."),
        ("Learning rate", "Step size used when updating weights with gradient descent."),
        ("Overfitting", "When a model memorises training data and performs poorly on new data."),
        ("Activation function", "Non-linear function applied to a neuron's output, e.g. ReLU or sigmoid."),
        ("Dropout", "Randomly disabling neurons during training to reduce overfitting."),
    ]
    src = sources(1)[0]
    return [Flashcard(card_id=_id("card"), front=bank[i % len(bank)][0], back=bank[i % len(bank)][1], topic=topic, source=src) for i in range(count)]


def explanation(topic: str) -> str:
    return (
        f"(mock) Think of {topic} like retracing your steps after getting lost: you start from where you ended up "
        "(the error) and walk back to find which turns (weights) caused it, then adjust them."
    )


# (label, parent label, summary, source index) for the mock mind map. The first row is the root.
_MINDMAP = [
    ("Neural networks", None, "Models made of layers of neurons whose weights are learned from data.", 0),
    ("Perceptron", "Neural networks", "A single neuron: a weighted sum of inputs passed through an activation.", 0),
    ("Weights and bias", "Perceptron", "The learnable numbers that scale each input and shift the sum.", 0),
    ("Activation functions", "Neural networks", "Non-linear functions applied to each neuron's output.", 0),
    ("ReLU", "Activation functions", "Outputs max(0, x); the usual default for hidden layers.", 0),
    ("Sigmoid", "Activation functions", "Squashes values into 0-1; its gradients can vanish.", 0),
    ("Backpropagation", "Neural networks", "Applies the chain rule from the output back to the input.", 0),
    ("Chain rule", "Backpropagation", "Multiplies local derivatives layer by layer to get each weight's gradient.", 0),
    ("Vanishing gradients", "Backpropagation", "Gradients shrink in deep networks, so early layers learn slowly.", 0),
    ("Gradient descent", "Neural networks", "Updates each weight: w = w - learning_rate * dL/dw.", 1),
    ("Learning rate", "Gradient descent", "Step size of each update; too large overshoots the minimum.", 1),
    ("Mini-batches", "Gradient descent", "Each update uses a small random subset of the training data.", 1),
    ("Overfitting", "Neural networks", "The model memorises training data and does worse on new data.", 2),
    ("Dropout", "Overfitting", "Randomly disables neurons during training to reduce overfitting.", 2),
    ("Regularisation", "Overfitting", "Penalises large weights so the model stays simpler.", 2),
]
_MINDMAP_LINKS = [("Backpropagation", "Gradient descent", "gradients used by"), ("Sigmoid", "Vanishing gradients", "can cause"), ("Learning rate", "Overfitting", "affects")]


def mindmap(topic: str | None, max_nodes: int) -> MindMapResponse:
    srcs = sources(3)
    rows = list(_MINDMAP)
    if topic:  # centre the fake map on the requested topic
        rows[0] = (topic, None, f"(mock) {topic}, as covered in the lecture.", 0)
        rows = [r if i == 0 or r[1] != "Neural networks" else (r[0], topic, r[2], r[3]) for i, r in enumerate(rows)]
        rows = [rows[0]] + [r for r in rows[1:] if r[0].lower() != topic.lower()]
        rows = [r for r in rows if r[1] is None or any(p[0] == r[1] for p in rows)]  # drop orphans of a removed row
    rows = rows[:max_nodes]
    ids = {label: f"n{i + 1}" for i, (label, *_ ) in enumerate(rows)}
    level = {}
    nodes = []
    for label, parent, summary, si in rows:
        level[label] = 0 if parent is None else level[parent] + 1
        nodes.append(MindMapNode(node_id=ids[label], label=label, summary=summary, parent_id=ids.get(parent), level=level[label], source=srcs[si]))
    links = [MindMapLink(from_id=ids[a], to_id=ids[b], label=t) for a, b, t in _MINDMAP_LINKS if a in ids and b in ids]
    title = f"Mind map: {topic}" if topic else "Lecture 3: Neural networks"
    return MindMapResponse(title=title, topic=topic, root_id="n1", nodes=nodes, links=links, sources=srcs)
