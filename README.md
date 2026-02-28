# 🔍 Project VERA — Virtual Engineering Review Agent

> A Multi-Agent System for Technical Document Auditing & Compliance — Adaptable to Any Industry

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-Stateful_Agents-green.svg)](https://github.com/langchain-ai/langgraph)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_Store-orange.svg)](https://www.trychroma.com/)
[![Gemini](https://img.shields.io/badge/Google_Gemini-Cloud_LLM-red.svg)](https://ai.google.dev/)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-purple.svg)](https://ollama.com/)

---

## 📋 Table of Contents

- [Overview](#overview)
- [Problem Statement](#problem-statement)
- [Architecture](#architecture)
- [Agent Descriptions](#agent-descriptions)
- [Security Implementation (RBAC)](#security-implementation-rbac)
- [Installation & Setup](#installation--setup)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Technology Stack](#technology-stack)

---

## Overview

**Project VERA** is an industry-agnostic Multi-Agent System that audits technical documents, emails, and Standard Operating Procedures (SOPs) for compliance issues. While the included demo uses a **semiconductor manufacturing** scenario, VERA's architecture is designed for **any document-heavy industry** — including aerospace, pharmaceuticals, automotive, energy, and more. It supports **two LLM backends**:

- **Google Gemini** (cloud API) — higher quality, requires API key
- **Ollama** (100% local) — no API key needed, runs on your laptop, no rate limits

### Key Capabilities

| Capability | Description |
|-----------|-------------|
| 🔒 **Role-Based Access Control** | Metadata-driven RBAC that filters document retrieval based on user clearance level |
| 📧 **Email Context Analysis** | Searches through ingested email threads to find informal engineering decisions |
| ⚠️ **Discrepancy Detection** | Automatically identifies conflicts between datasheets, emails, DB records, and document versions |
| 🚨 **Human Escalation** | Triggers supervisor review with detailed context summaries for unauthorized access attempts |
| 🤖 **Multi-Agent Orchestration** | LangGraph-based workflow with specialized agents for different document types |
| 🗄️ **DB Info Integration** | Queries structured database records (SQLite-style) for production lot tracking and test results |
| 📑 **Document Version Comparison** | Detects changes between different versions of the same specification document |

---

## Problem Statement

In many industries, **official specifications** (datasheets, manuals) often become outdated when teams make critical decisions via **informal channels** (emails, chat). This creates a dangerous gap. In our demo scenario (semiconductor manufacturing):

```
📄 Datasheet says:     "RTX-9000 max voltage = 5.0V"
📧 Internal email says: "URGENT: Lowering RTX-9000 to 3.3V due to heat failures"
```

**VERA** bridges this gap by:
1. Ingesting ALL document types (datasheets, emails, SOPs)
2. Applying strict access controls so only authorized personnel see sensitive info
3. Automatically detecting and reporting discrepancies between sources
4. Escalating unauthorized access attempts to supervisors

---

## Architecture

```mermaid
graph TD
    A["🧑 User Query + Role"] --> B["🔀 Router Agent"]
    
    B -->|"Surgical Route: db_query"| C1["🗄️ DB Agent"]
    B -->|"Surgical Route: spec_retrieval"| C2["📊 Official Docs Agent"]
    B -->|"Surgical Route: cross_reference"| C3["🧠 Full Chain (DB+Official+Informal)"]
    B -->|"🚨 Security Flag"| E["⚠️ Human Escalation"]
    
    C1 --> D["🧩 Structured Facts"]
    C2 --> D
    C3 --> D
    
    D --> F["🤖 Response Generator"]
    F --> G["🔍 Discrepancy Agent"]
    G -->|"Report Generated"| H["📤 Final Response"]
    E -->|"Detailed Escalation Summary"| H

    subgraph "Knowledge Sources"
        I["📄 Official Specs\n(ChromaDB)"]
        J["📧 Informal Emails\n(ChromaDB)"]
        K["🗄️ Production DB\n(SQLite)"]
        L["📋 SOPs\n(ChromaDB)"]
    end

    C1 -.->|"SQL Query"| K
    C2 -.->|"Semantic Search"| I
    C3 -.->|"Full RAG"| I & J & K & L

    style E fill:#ff6b6b,stroke:#c92a2a,color:#fff
    style B fill:#4dabf7,stroke:#1864ab,color:#fff
    style G fill:#ffd43b,stroke:#f59f00,color:#333
    style H fill:#69db7c,stroke:#2b8a3e,color:#333
```

### Data Flow (Surgical Routing)

1. **User** submits a query with their role (Senior/Junior).
2. **Router Agent** performs **LLM-based NER** to extract entities/attributes and classifies intent into fine-grained categories (`db_query`, `spec_retrieval`, `cross_reference`).
3. **Retrieval Agents** perform **Structured Fact Extraction**:
    *   **DB Agent** translates NL to SQL and queries SQLite databases.
    *   **Official/Informal Agents** use high-precision RAG (filtering by entity) to extract facts into Pydantic models.
4. **Generator** synthesizes a response using the extracted facts, leading with a **Discrepancy Summary** if conflicts are found.
5. **Discrepancy Agent** performs a final audit, comparing the generated response against raw documents to ensure no hallucinations.

### Data Flow

1. **User** submits a query with their role (Senior/Junior)
2. **Router Agent** classifies intent and performs security checks
3. **Retrieval Agent** fetches documents with RBAC metadata filters
4. **Generator** synthesizes a response citing sources
5. **Case Agent** checks for cross-source discrepancies
6. **Final response** delivered (or escalated if unauthorized)

---

## Agent Descriptions

| Agent | LangGraph Node | Role |
| :--- | :--- | :--- |
| **🔀 Router** | `route_query` | Orchestrator: performs NER, security checks, and surgical routing to specific domain subchains. |
| **🗄️ DB Agent** | `{domain}_db_query` | SQL Specialist: inspects schemas and executes read-only queries on domain SQLite databases. |
| **📊 Official Docs** | `{domain}_official` | Fact Extractor: retrieves high-precision specs from datasheets and manuals via entity-filtered RAG. |
| **📧 Informal Docs**| `{domain}_informal` | Context Researcher: searches engineering emails and design memos for undocumented changes. |
| **🔍 Discrepancy** | `{domain}_discrepancy` | Auditor: cross-references all facts and identifies conflicts (e.g., DB says 3.3V, Datasheet says 5.0V). |
| **🤖 Response Gen** | `generate_response` | Compiler: formats structured facts into a final report with clear source citations. |
| **⚠️ Escalation** | `escalate` | Security: handles unauthorized access or out-of-domain queries with detailed context. |

---

## Industrial Genericity

VERA is designed for **"Plug-and-Play" multi-industry deployment**. The core system (`shared/`) is 100% domain-agnostic. To add a new industry (e.g., Medical), simply:
1. Create `agents_logic/medical_agents/`
2. Define domain-specific keywords in `domain_config.py`
3. Add data to `source_documents/medical/`

The system will **automatically discover** the new agents and route "Medical" queries to them without any changes to the core code.

---

## Security Implementation (RBAC)

### How It Works

Project VERA implements **Role-Based Access Control** at the retrieval layer using ChromaDB metadata filtering. This ensures that access controls are enforced *before* any document content reaches the LLM.

```
┌─────────────────────────────────────────────────────────────────┐
│                    RBAC ENFORCEMENT LAYER                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User Role: "senior"                                           │
│  ├── ChromaDB Filter: NONE (access all documents)              │
│  └── Result: Datasheets + Emails + SOPs (all access levels)    │
│                                                                 │
│  User Role: "junior"                                           │
│  ├── ChromaDB Filter: {"access_level": "public"}               │
│  └── Result: Only public datasheets and SOPs                   │
│                                                                 │
│  Security Check (Router):                                      │
│  ├── Junior + Internal query intent → ESCALATE                 │
│  └── Junior + Public query intent → PROCEED with filter        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Access Levels

| Access Level | Senior Engineer (User A) | Junior Intern (User B) |
|-------------|:---:|:---:|
| `public` | ✅ Full Access | ✅ Full Access |
| `internal_only` | ✅ Full Access | ❌ Blocked |
| `confidential` | ✅ Full Access | ❌ Blocked + Escalated |

### RBAC Code Implementation

The RBAC filter is applied in the `retrieve_with_rbac()` function in `app.py`:

```python
# Junior users: ONLY public documents
if user_role == "junior":
    filter_conditions = {"access_level": "public"}

# Senior users: ALL documents (no filter)
elif user_role == "senior":
    filter_conditions = {}  # No restriction

# Query ChromaDB with the filter
results = vector_store.similarity_search(
    query, k=4, filter=filter_conditions
)
```

### Security Layers

1. **Layer 1 — Router Security Check**: Keyword-based intent classification detects if a junior user’s query implies access to restricted information
2. **Layer 2 — Metadata Filtering**: ChromaDB `where` clause filters out non-public documents for junior users
3. **Layer 3 — Escalation**: Flagged queries are routed to the human escalation node instead of retrieval

---

## Installation & Setup

### Prerequisites

- Python 3.10+
- **Option A** — Google Gemini API key ([get one free](https://aistudio.google.com/apikey))
- **Option B** — [Ollama](https://ollama.com/) installed locally (recommended for laptops)

### Step 1: Create Conda Environment

```bash
cd proj_vera
conda env create -f environment.yml
conda activate vera
```

Alternatively, install via pip:

```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment

Create a `.env` file in the project root. Choose your backend:

**Option A — Google Gemini (cloud):**
```env
LLM_BACKEND=gemini
GEMINI_API_KEY=your_gemini_api_key_here
```

**Option B — Ollama (local, no API key needed):**
```bash
# Install Ollama models first
ollama pull hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF
ollama pull hf.co/CompendiumLabs/bge-base-en-v1.5-gguf
```
```env
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=hf.co/bartowski/Llama-3.2-1B-Instruct-GGUF
OLLAMA_EMBED_MODEL=hf.co/CompendiumLabs/bge-base-en-v1.5-gguf
```

> **💡 Tip:** Ollama runs entirely on your machine — no internet, no rate limits, no API costs.

### Step 3: Run Data Ingestion

```bash
python ingestion.py
```

This will:
- Create mock documents (datasheets, emails, SOPs) — easily replaceable with real data from any industry
- Split them into chunks with `RecursiveCharacterTextSplitter`
- Generate embeddings using the selected backend (Gemini or Ollama)
- Persist to ChromaDB at `./chroma_db`

> **⚠️ Important:** If you switch backends, re-run `python ingestion.py` to regenerate embeddings with the matching model.

### Step 4: Run the VERA Agent System

**Option A — Interactive Chat UI (recommended):**

```bash
streamlit run streamlit_app.py
```

This opens a browser-based chat interface at `http://localhost:8501` where you can:
- Switch between Senior/Junior roles in the sidebar
- Ask questions interactively
- View retrieved documents, RBAC audit logs, and discrepancy reports
- See the full agent execution trace

**Option B — CLI test scenarios:**

```bash
python app.py
```

This runs 5 automated test scenarios demonstrating:
1. Senior user with full access
2. Junior user with restricted access
3. Junior user triggering escalation (with detailed context)
4. Compliance query with email context
5. DB info + document version discrepancy detection

---

## Usage

### Test Scenarios

| Test | User Role | Query | Expected Behavior |
|------|-----------|-------|-------------------|
| 1 | Senior | "What is the max voltage for RTX-9000?" | Full info including internal email about 3.3V change |
| 2 | Junior | "What is the max voltage for RTX-9000?" | Only public datasheet info (5.0V) |
| 3 | Junior | "Were there internal emails about skipping burn-in?" | **ESCALATED** — access denied with detailed context |
| 4 | Senior | "What are quality audit procedures + recent email changes?" | SOPs + email communications retrieved |
| 5 | Senior | "Compare RTX-9000 spec versions + check production DB" | DB records + versioned docs with version discrepancy report |
| 6 | Senior (semiconductor) | "What are the FDA clinical trial requirements?" | **ESCALATED** — out-of-domain query detected |

---

## Project Structure

```
proj_vera/
├── shared/                 # ⚙️ Shared infrastructure (100% Generic)
│   ├── advanced_rag.py     # High-precision retrieval & fact extraction
│   ├── config.py           # LLM, VectorStore, RBAC, factory methods
│   ├── db_utils.py         # Dynamic SQLite discovery & querying
│   ├── graph_state.py      # GraphState TypedDict (state schema)
│   └── dynamic_loader.py   # Auto-discovers domain agents & configs
├── agents_logic/           # 🤖 Agent modules
│   ├── router_agent.py     # LLM-NER & Surgical Routing
│   ├── response_agent.py   # Report compiler
│   ├── escalation_agent.py # Security & domain-mismatch handler
│   └── semiconductor_agents/ # Domain: semiconductor (example)
│       ├── db_agent.py              # SQL query capability
│       ├── official_docs_agent.py   # Datasheet retrieval
│       ├── informal_docs_agent.py   # Email/Memo research
│       ├── discrepancy_agent.py     # Audit logic
│       └── domain_config.py         # Domain keywords & heuristics
├── source_documents/       # 📁 Source data per domain
│   └── semiconductor/      # .txt docs and .db files
├── streamlit_app.py        # 🖥️ Interactive Web UI
├── app.py                  # Main LangGraph orchestrator
├── ingestion.py            # Data ingestion pipeline (ChromaDB)
└── output/                 # 📂 System-generated logs (domain-specific)
```

---

## Technology Stack

| Technology | Purpose | Version |
|-----------|---------|---------|
| **LangGraph** | Multi-agent state machine orchestration | ≥ 0.2.0 |
| **LangChain** | RAG pipeline, prompt management, output parsing | ≥ 0.3.0 |
| **ChromaDB** | Local vector store with metadata filtering | ≥ 0.5.0 |
| **Streamlit** | Interactive chat UI with real-time agent feedback | ≥ 1.40.0 |
| **Google Gemini** | Cloud LLM + Embeddings (Option A) | Latest |
| **Ollama** | Local LLM + Embeddings (Option B) | Latest |
| **Python** | Core runtime | 3.10+ |

---

## 📄 License

This project was developed as a Capstone Project for Data Science & AI certification.

---

*Built with ❤️ using LangGraph, LangChain, ChromaDB, Google Gemini & Ollama*
