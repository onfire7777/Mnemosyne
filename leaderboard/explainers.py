"""Source-reviewed editorial content; independent of submitted result data."""

from html import escape


SYSTEMS = (
    (
        "Mem0",
        "Mem0 extracts useful facts from interactions and retrieves them for later "
        "conversations. Its current project description combines semantic similarity, "
        "keyword matching and entity links. The managed service includes proprietary "
        "optimizations, so an open-source SDK run and a hosted-service run must be "
        "identified separately.",
        "https://github.com/mem0ai/mem0",
    ),
    (
        "Graphiti and Zep",
        "Graphiti represents people, things and their relationships in a graph that "
        "tracks when facts are valid and where they came from. Retrieval combines "
        "meaning, keywords and graph connections. Zep provides managed context "
        "infrastructure built around this approach; it is a distinct deployment "
        "from the open-source Graphiti framework.",
        "https://github.com/getzep/graphiti",
    ),
    (
        "Letta",
        "Letta gives an agent persistent state. Named memory blocks hold editable "
        "text; attached blocks remain in the agent's context, and blocks can be "
        "shared between agents. Tools let the agent update that memory. Evaluating "
        "the agent therefore requires disclosing its model, tools and memory setup, "
        "not only a document search configuration.",
        "https://docs.letta.com/v1-sdk/concepts/stateful-agents",
    ),
    (
        "Cognee",
        "Cognee turns source material into searchable chunks, entities and "
        "relationships. Its retrieval can select graph, vector or code context. "
        "Session learning can feed accepted lessons into longer-term memory. The "
        "extraction model, embedding model, storage backend and retrieval strategy "
        "are part of the evaluated configuration.",
        "https://github.com/topoteretes/cognee",
    ),
    (
        "MemOS",
        "MemOS organizes memory through operations for storing, retrieving, "
        "editing and deleting it. Memory cubes group knowledge for controlled "
        "sharing and composition, and its documented inputs include text, images "
        "and tool traces. Hosted, self-hosted and local-plugin deployments differ; "
        "a result must name the one actually measured.",
        "https://github.com/MemTensor/MemOS",
    ),
    (
        "Supermemory",
        "Supermemory describes a learning component that decides what to retain "
        "and relate, backed by a temporal graph with vector and full-text search. "
        "Applications add material and retrieve relevant memory through its API. "
        "This explains the vendor's documented design; it does not independently "
        "verify its internal implementation or performance claims.",
        "https://supermemory.ai/docs/concepts/how-it-works",
    ),
    (
        "HippoRAG",
        "HippoRAG combines document retrieval with a knowledge graph and "
        "Personalized PageRank, which spreads relevance through connected nodes. "
        "Its interface distinguishes retrieving passages from answering with an "
        "LLM. A retrieval score and the quality of the resulting answer measure "
        "different stages, even when they use the same index.",
        "https://github.com/OSU-NLP-Group/HippoRAG",
    ),
    (
        "Mnemosyne — operator entry",
        "Mnemosyne keeps content-addressed evidence and derives searchable "
        "projections from it. It combines hybrid retrieval, time-aware beliefs "
        "and provenance, with local SQLite and PostgreSQL deployment paths. Its "
        "own documentation records unfinished capabilities and validation gaps. "
        "This site's operator must provide the same measured evidence required "
        "from every other entry.",
        "https://github.com/onfire7777/Mnemosyne/blob/864258b5274ccb8b25a065398ab5b93d0e9a66c2/README.md",
    ),
)


def systems_body() -> str:
    """Render fixed editorial summaries without reading data or using a network."""
    sections = "".join(
        f"<section><h2>{escape(name)}</h2><p>{escape(description)}</p>"
        f'<p><a href="{escape(source, quote=True)}" rel="noreferrer">'
        f"Primary source: {escape(name)}</a></p></section>"
        for name, description, source in SYSTEMS
    )
    return (
        '<article class="prose"><h1>How memory systems work</h1>'
        '<p class="intro">Different ways to retain useful context and find it again.</p>'
        '<p>Reviewed against the linked primary sources on 2026-10-04. These are '
        'architecture summaries, not rankings or evidence of benchmark admission. '
        'Products change; each result must identify its exact version and settings.</p>'
        '<p>As a simple example, remembering a changed delivery address requires '
        'more than finding an old message: the system must select the current fact '
        'and preserve enough evidence to justify it. A graph, a memory block and '
        'a searchable document offer different ways to organize that information.</p>'
        + sections
        + '<h2>Architecture does not determine the winner</h2><p>Extraction may lose '
        'details, retrieval may miss relevant evidence, and an answering model may '
        'misread what it receives. Measure these stages separately, together with '
        'latency, resource use and safety under the registered protocol.</p>'
        '<p><a href="methods.html">Read the measurement guide</a></p></article>'
    )
