# 🚚 Supply-Chain Disruption Agent

> **AI-powered shipment delay prediction, investigation, and decision support**

A three-week AI engineering project: an intelligent **Supply-Chain Disruption Agent** that predicts which shipments are at risk of delay, investigates the risky ones by collecting evidence, and produces a briefing with recommended actions for logistics and operations teams.

The system combines:

* 📊 Machine learning (XGBoost delay-risk model)
* 🤖 An AI investigation agent orchestrated with LangGraph
* 🔎 Retrieval-Augmented Generation (RAG) over operational procedures
* 🧠 Azure OpenAI for briefing generation, with a deterministic fallback
* 🌦️ Historical weather from Open-Meteo
* 📦 Shipment, inventory, and supplier data
* ⚡ FastAPI backend and ⚛️ React frontend

---

# 📌 Table of Contents

* [1. Project Overview](#1-project-overview)
* [2. Problem Statement](#2-problem-statement)
* [3. Solution Overview](#3-solution-overview)
* [4. Key Features](#4-key-features)
* [5. Investigation Workflow](#5-investigation-workflow)
* [6. Architecture](#6-architecture)
* [7. API](#7-api)
* [8. Machine Learning Layer](#8-machine-learning-layer)
* [9. RAG and Briefing Layer](#9-rag-and-briefing-layer)
* [10. Technology Stack](#10-technology-stack)
* [11. Repository Structure](#11-repository-structure)
* [12. Getting Started](#12-getting-started)
* [13. Environment Variables](#13-environment-variables)
* [14. Running the Tests](#14-running-the-tests)
* [15. Important Limitations](#15-important-limitations)
* [16. Deployment Status](#16-deployment-status)
* [17. Development Principles](#17-development-principles)
* [18. Future Improvements](#18-future-improvements)

---

# 1. Project Overview

The **Supply-Chain Disruption Agent** is a logistics decision-support system designed to identify potential shipment delays before they develop into operational problems.

Machine learning estimates the probability that a shipment will be delayed.

An AI agent then investigates shipments that need attention by calling tools that collect evidence, retrieving relevant operational procedures through RAG, and generating an understandable **operations briefing with recommended actions**.

The system provides decision support. Final operational decisions remain with human users.

---

# 2. Problem Statement

A late shipment can create a chain reaction:

```text
Shipment Delay
      ↓
Inventory Shortage
      ↓
Production / Operations Disruption
      ↓
Customer Service Impact
      ↓
Financial Impact
```

The problem is that logistics teams may only become aware of the disruption after it has already occurred.

The goal of this project is therefore to build a system that can answer:

> **Which shipments are likely to be disrupted, why are they at risk, what could be affected, and what should the operations team consider doing?**

---

# 3. Solution Overview

The solution is built around a **risk-first workflow**. The ML model evaluates a shipment first; only shipments requiring attention move into deeper AI investigation.

~~~text
SHIPMENT DATA
       ↓
XGBOOST ML MODEL
       ↓
DELAY PROBABILITY
       ↓
RISK GATE
   ┌───┴───────────────┐
   │                   │
 LOW RISK        MEDIUM / HIGH RISK
   │                   │
   ▼                   ▼
NO INVESTIGATION    AI AGENT (LangGraph)
                       │
                EVIDENCE COLLECTION
        shipment · history · weather
           inventory · supplier
                       │
                       ▼
          RAG  + LLM
                       │
                       ▼
             DISRUPTION BRIEFING
                       │
                       ▼
              OPERATIONS DASHBOARD
                       │
                       ▼
                HUMAN DECISION
~~~

The architecture separates five responsibilities:

1. **Predict** — ML estimates delay risk.
2. **Gate** — the risk gate determines whether deeper investigation is needed.
3. **Investigate** — the agent collects evidence from its tools.
4. **Ground and explain** — RAG provides operational knowledge and the LLM turns the evidence into a briefing.
5. **Decide** — the operations team reviews the result and makes the final decision.

> **ML predicts. The agent investigates. Tools provide evidence. RAG provides knowledge. The LLM communicates. Humans decide.**

---

# 4. Key Features

* **Delay-risk prediction** — an XGBoost model returns a delay probability and a LOW / MEDIUM / HIGH risk level for a shipment.
* **Risk gate** — LOW-risk shipments are not investigated; the investigation endpoints reject them with a clear message.
* **Six-step evidence collection** — the agent gathers risk, shipment, historical-delay, weather, inventory, and supplier evidence (see the next section).
* **Graceful degradation** — weather, historical context, inventory, and supplier evidence are optional. If one cannot be collected, the investigation continues and the gap is reported as a limitation.
* **Grounded briefing** — when supporting documents are retrieved, the briefing cites them. When they are not, the briefing is still produced from the collected evidence, with no citations.
* **Live progress** — the investigation can be streamed step by step using Server-Sent Events.
* **Traceability** — every tool call is recorded in the response's `tool_trace`, and every caveat in `limitations`.
* **Operations dashboard** — a React control tower showing shipments, investigations, evidence, briefings, and recommended actions.

---

# 5. Investigation Workflow

An investigation runs six evidence-collection steps in a fixed order and then generates the briefing. The workflow is a LangGraph state graph defined in `backend/services/agent_service.py`.

| # | Step (tool name) | What it collects | If it fails |
| --- | --- | --- | --- |
| 1 | `get_delay_risk` | Delay probability, risk level, and the risk-gate decision from the ML model | Investigation stops |
| 2 | `get_shipment` | The shipment record (product, category, destination, shipping mode, schedule) | Investigation stops |
| 3 | `get_historical_delay_context` | Historical delay rates for the shipment's product, market, and shipping mode | Reported as a limitation |
| 4 | `get_destination_weather` | Historical weather at the destination city for the scheduled transit window (Open-Meteo) | Reported as a limitation |
| 5 | `get_inventory_coverage` | The product-level inventory record for the shipment's product | Reported as a limitation |
| 6 | `find_alternative_supplier` | Alternative supplier candidates for the shipment's product category | Reported as a limitation |
| → | Briefing generation | Summary, recommended actions, and citations of any retrieved documents | See [section 9](#9-rag-and-briefing-layer) |

The names above are the step names that appear in `tool_trace` and in the stream events. Each step calls the function of the same name in `backend/services/agent_tools.py`, except step 6: the `find_alternative_supplier` step calls `get_alternative_suppliers()`, which uses the supplier service's `find_alternative_supplier()`.

After step 1 the **risk gate** applies: a shipment that does not require investigation ends there and no further tool is called.

~~~text
get_delay_risk ──► RISK GATE ──► LOW: investigation not required
                       │
                       ▼
                 get_shipment
                       ▼
       get_historical_delay_context
                       ▼
          get_destination_weather
                       ▼
          get_inventory_coverage
                       ▼
         find_alternative_supplier
                       ▼
              generate briefing
~~~

---

# 6. Architecture

~~~text
┌────────────────────────────────────────────────────────────────────┐
│                         OPERATIONS USER                            │
│                    React Dashboard (Vite)                          │
└───────────────────────────────┬────────────────────────────────────┘
                                │  REST + Server-Sent Events
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│                         FASTAPI BACKEND                            │
│                  API / Validation / Orchestration                  │
└───────────────┬───────────────────────────────┬────────────────────┘
                │                               │
                ▼                               ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│         ML RISK LAYER         │   │   INVESTIGATION (LangGraph)   │
│ Preprocessor → XGBoost →      │   │ Risk gate → evidence steps →  │
│ Probability + Risk Level      │   │ briefing                      │
└───────────────────────────────┘   └───────────────┬───────────────┘
                                                    │
                    ┌───────────────┬───────────────┼───────────────┐
                    ▼               ▼               ▼               ▼
              Shipment data     Open-Meteo     Inventory data   Supplier data
                 (DataCo)        (weather)      (synthetic)      (synthetic)
                                                    │
                                                    ▼
                                    RAG (Chroma + Azure embeddings)
                                    LLM (Azure OpenAI) 
~~~

### Architecture Responsibilities

| Component | Responsibility |
| --- | --- |
| Data layer | Prepared shipment, inventory, and supplier datasets |
| ML model | Estimate shipment delay risk |
| Risk gate | Decide whether deeper investigation is required |
| AI agent | Orchestrate the investigation and collect evidence |
| Tools | Retrieve operational evidence |
| RAG | Retrieve documented procedures and operational knowledge |
| LLM | Explain evidence and generate the briefing |
| Dashboard | Present risk, evidence, and recommendations |
| Human operator | Make the final operational decision |

### Data Sources

| Component | Source | Purpose |
| --- | --- | --- |
| Shipment Tool | DataCo test-period data (`shipment_tool_data.csv`) | Shipment/order information |
| ML Model | DataCo training data | Delay-risk prediction |
| Weather Tool | Open-Meteo historical archive | Weather at the destination for the transit window |
| Inventory Tool | Synthetic inventory dataset (`inventory_tool_data.csv`) | Product-level stock record |
| Supplier Tool | Synthetic supplier dataset (`supplier_tool_data.csv`) | Alternative supplier candidates |
| RAG | Five demonstration procedure documents (`rag/documents/`) | Operational knowledge |

**Important:** the inventory and supplier datasets and the procedure documents are synthetic, created for this MVP. They are not real company records or policies. DataCo outcome fields such as `Late_delivery_risk`, `Delivery Status`, `Days for shipping (real)`, and post-outcome shipping dates are not ML input features.

---

# 7. API

The backend exposes these endpoints. Interactive documentation is available at `/docs` when the backend is running.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `GET` | `/api/shipments/{shipment_reference}` | Shipment record, for example `SHP-153444` |
| `POST` | `/api/predictions/evaluate/{shipment_id}` | Delay probability, risk level, and gate decision |
| `POST` | `/api/agent/investigate/{shipment_id}` | Run the investigation and return the briefing |
| `GET` | `/api/agent/investigate/{shipment_id}/stream` | Same investigation, streamed as Server-Sent Events |
| `GET` | `/api/inventory/shipment/{shipment_reference}` | Product-level inventory record for the shipment's product |
| `POST` | `/api/briefing/generate` | Generate a briefing from supplied evidence |

The stream emits `tool_start`, `tool_complete`, `tool_error`, `message`, and `done` events, or a single `error` event if the investigation cannot be completed.

The investigation response contains the shipment reference, risk level, delay probability, `evidence` (one summary per evidence source), `rag_policy_citations`, `summary`, `recommended_actions`, `tool_trace`, and `limitations`.

Investigating a LOW-risk shipment returns `400` with the reason; an unknown shipment returns `404`.

---

# 8. Machine Learning Layer

The ML component predicts the probability that a shipment will be delayed.

```text
0 = On Time
1 = Delayed
```

The probability is translated into a risk level using two configurable thresholds:

```text
0.00 - 0.39 → LOW      (not investigated)
0.40 - 0.69 → MEDIUM   (investigated)
0.70 - 1.00 → HIGH     (investigated)
```

The thresholds are set by `RISK_THRESHOLD` (default `0.40`) and `HIGH_RISK_THRESHOLD` (default `0.70`).

The model is an XGBoost classifier with a scikit-learn preprocessor, stored in `models/`. Training and evaluation are documented in the notebooks in `notebooks/`. The model was trained and evaluated on a chronological split of the DataCo data, so it is evaluated on orders placed after the ones it was trained on.

For supply-chain disruption detection, particular attention is paid to **false negatives**, because failing to identify a genuinely risky shipment may have significant operational consequences.

---

# 9. RAG and Briefing Layer

The briefing is produced after the evidence has been collected.

```text
Collected evidence
        ↓
Retrieve supporting documents (Chroma vector store + Azure OpenAI embeddings)
        ↓
Generate briefing (Azure OpenAI)
        ↓
Summary + recommended actions + citations
```

Retrieval and the language model are both **optional**. The briefing is always generated:

| Situation | Briefing text | Citations |
| --- | --- | --- |
| Documents retrieved and Azure OpenAI available | Written by Azure OpenAI from the evidence and retrieved guidance | Sources of the retrieved documents |
| Documents retrieved, Azure OpenAI unavailable | Assembled directly from the evidence and retrieved guidance | Sources of the retrieved documents |
| Retrieval unavailable (no Azure configuration, no vector store, or a failed search) | Assembled directly from the collected evidence | None |
| Retrieval returns nothing usable | Assembled directly from the collected evidence | None |

Citations are only ever the sources of documents that were actually retrieved. When none were retrieved, the citation list is empty and the briefing's `limitations` state that supporting document retrieval was unavailable.

The knowledge base consists of five procedure documents in `rag/documents/`, covering shipment delay escalation, weather disruption, alternative suppliers, inventory stockout response, and transport rerouting. A persisted vector store built from them is included in `rag/vector_store/`.

To rebuild the vector store after changing the documents (requires the Azure OpenAI embedding configuration):

```bash
python -m rag.ingestion
```

---

# 10. Technology Stack

| Layer            | Technology                                   |
| ---------------- | -------------------------------------------- |
| Frontend         | React 18, Vite                               |
| Backend          | FastAPI, Python                              |
| Machine Learning | scikit-learn, XGBoost                        |
| AI Agent         | LangGraph                                    |
| LLM              | Azure OpenAI                                 |
| RAG              | LangChain, Chroma, Azure OpenAI embeddings   |
| Data Processing  | Pandas, NumPy                                |
| Weather          | Open-Meteo (no API key required)             |
| Packaging        | uv (`pyproject.toml`, `uv.lock`), `requirements.txt` |
| Testing          | Pytest (backend), Node test runner (frontend) |
| Version Control  | Git / GitHub                                 |

---

# 11. Repository Structure

```text
.
├── README.md
├── pyproject.toml              # Python project and dependencies
├── uv.lock                     # Locked dependency versions
├── requirements.txt            # Dependencies for pip-based installs
├── .env.example                # Backend environment variables
├── startup.sh                  # Starts the backend with uvicorn
│
├── backend/
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Settings loaded from the environment
│   ├── exceptions.py
│   ├── api/
│   │   ├── routes_shipments.py
│   │   ├── routes_predictions.py
│   │   ├── routes_agent.py     # Investigation and streaming endpoints
│   │   ├── routes_inventory.py
│   │   └── routes_briefing.py
│   ├── models/
│   │   └── schemas.py          # Request and response schemas
│   └── services/
│       ├── agent_service.py        # LangGraph investigation workflow
│       ├── agent_tools.py          # Tools the agent calls
│       ├── prediction_service.py   # ML inference and risk gate
│       ├── model_feature_service.py
│       ├── shipment_service.py
│       ├── weather_service.py
│       ├── inventory_service.py
│       ├── supplier_service.py
│       ├── briefing_service.py     # Retrieval, briefing, and fallback
│       └── azure_openai_service.py
│
├── rag/
│   ├── config.py
│   ├── ingestion.py            # Builds the vector store
│   ├── retrieval.py
│   ├── documents/              # Five procedure documents (PDF)
│   └── vector_store/           # Persisted Chroma store
│
├── data/
│   └── processed/              # Shipment, inventory, and supplier datasets
│
├── models/                     # Trained preprocessor and XGBoost model
├── notebooks/                  # Model development and data preparation
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── .env.example
│   └── src/
│       ├── App.jsx
│       ├── api/                # Backend client and investigation stream
│       └── components/         # Home, Shipments, Investigation, Briefings, Actions
│
├── tests/                      # Backend tests (pytest)
└── docs/                       # Product and planning documents
```

---

# 12. Getting Started

## 12.1 Prerequisites

* Python 3.11 (the project declares `>=3.11,<3.13`; it has been run and tested on 3.11)
* Node.js and npm, for the frontend
* [uv](https://docs.astral.sh/uv/) (recommended) or pip
* Internet access for the weather step (Open-Meteo). Without it the investigation still completes and reports the missing weather evidence.

Azure OpenAI credentials are **not** required to run the application locally.

## 12.2 Clone the repository

```bash
git clone https://github.com/tag-ecosystemai/c1-transformers-project-3.git
cd c1-transformers-project-3
```

## 12.3 Install backend dependencies

With uv:

```bash
uv sync
```

Or with pip:

```bash
python -m venv .venv
```

Activate it — Windows:

```bash
.venv\Scripts\activate
```

macOS / Linux:

```bash
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
```

## 12.4 Configure environment variables

Copy `.env.example` to `.env`.

The defaults are enough to run locally with the fallback briefing. Add the Azure OpenAI values only if you want retrieved documents and model-written briefings; see [section 13](#13-environment-variables).

**Never commit `.env` to GitHub.**

## 12.5 Start the backend

From the repository root:

```bash
uvicorn backend.main:app --reload
```

With uv:

```bash
uv run uvicorn backend.main:app --reload
```

The API is then available at `http://localhost:8000`, with interactive documentation at `http://localhost:8000/docs`.

## 12.6 Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. In development, Vite proxies `/api` requests to the backend at `http://localhost:8000`, so `VITE_API_BASE_URL` can stay empty.

## 12.7 Try it

The dashboard loads two demonstration shipments by default:

* **`SHP-153444`** — MEDIUM risk. Investigating it runs all six evidence steps and produces a briefing.
* **`SHP-153440`** — LOW risk. The risk gate reports that no investigation is required.

Without Azure OpenAI configuration, the briefing for `SHP-153444` is generated from the collected evidence, shows no document citations, and states that supporting documents were unavailable.

---

# 13. Environment Variables

All backend variables are listed in `.env.example`. Every variable has a working default except the Azure OpenAI values.

### Needed for the local fallback

Nothing beyond the defaults. The data paths, model paths, thresholds, and weather URLs in `.env.example` work as they are.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FRONTEND_URL` | `http://localhost:3000, http://localhost:5173` | Origins allowed to call the API (comma-separated) |
| `SHIPMENT_DATA_PATH` | `data/processed/shipment_tool_data.csv` | Shipment dataset |
| `INVENTORY_DATA_PATH` | `data/processed/inventory_tool_data.csv` | Inventory dataset |
| `SUPPLIER_DATA_PATH` | `data/processed/supplier_tool_data.csv` | Supplier dataset |
| `MODEL_PATH`, `PREPROCESSOR_PATH` | `models/…` | Trained model artifacts |
| `RISK_THRESHOLD` | `0.40` | Probability at which a shipment is investigated |
| `HIGH_RISK_THRESHOLD` | `0.70` | Probability at which risk is HIGH |
| `WEATHER_API_BASE_URL`, `WEATHER_GEOCODING_URL` | Open-Meteo URLs | Weather and geocoding services |
| `WEATHER_TIMEOUT_SECONDS` | `10` | Weather request timeout |

### Optional: Azure OpenAI and RAG

Set these to enable document retrieval and model-written briefings. If they are missing, the application uses the fallback described in [section 9](#9-rag-and-briefing-layer).

| Variable | Purpose |
| --- | --- |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI key |
| `AZURE_OPENAI_API_VERSION` | API version (default `2024-02-01`) |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | Deployment used to write the briefing |
| `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` | Deployment used by RAG ingestion and retrieval |
| `VECTOR_STORE_PATH` | Location of the vector store (default `rag/vector_store`) |
| `RAG_COLLECTION_NAME` | Collection name (default `operational_sops`) |
| `RAG_DOCUMENTS_PATH`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_TOP_K` | Ingestion and retrieval settings |

### Frontend

Listed in `frontend/.env.example`.

| Variable | Purpose |
| --- | --- |
| `VITE_API_BASE_URL` | Backend URL. Leave empty for local development. |
| `VITE_DEMO_SHIPMENTS` | Comma-separated shipment references shown on the dashboard |

---

# 14. Running the Tests

## Backend

From the repository root:

```bash
python -m pytest -m "not integration"
```

With uv:

```bash
uv run pytest -m "not integration"
```

These tests run offline: weather, retrieval, and Azure OpenAI are replaced with fixed test data.

Two tests are marked `integration` and call the real retrieval pipeline. They need the Azure OpenAI embedding configuration:

```bash
python -m pytest -m integration
```

## Frontend

```bash
cd frontend
npm test
```

The frontend tests use Node's built-in test runner and do not need the backend.

To check the production build:

```bash
npm run build
```

---

# 15. Important Limitations

The application is a demonstration built on historical and synthetic data. It reports these limits itself, in the `limitations` of every briefing.

* **Inventory is product-level.** The inventory record is matched to a shipment by product name only. It describes the product, not the shipment: it does **not** verify that stock is available for a specific shipment or at its destination. No warehouse is linked to a shipment.
* **Supplier candidates are recommendations, not verified commitments.** Candidates are matched on product category. Supplier availability, capacity for the required quantity, commercial terms, and delivery dates are not verified. Human approval is required before changing suppliers.
* **Briefings may have no citations.** When supporting document retrieval is unavailable, the briefing is still generated from the collected evidence, without document citations, and says so.
* **Inventory and supplier data are synthetic**, as are the procedure documents used for RAG. They are not real company records or policies.
* **Weather is destination-level and historical.** It describes the destination city over an approximate window (order date plus scheduled shipping days), not the full shipment route.
* **Delay probability is not delay duration.** The model estimates the likelihood of a delay, not how many days late a shipment will be.
* **Shipments come from a historical dataset** (DataCo), not live tracking.


---

# 16. Deployment Status

**Live demo:** https://supply-chain-disruption-agent.vercel.app/

The Supply-Chain Disruption Agent is deployed as a live application using Microsoft Azure and Vercel. The deployment was carried out by Fredrick.

The repository includes `startup.sh`, which starts the backend with uvicorn on the port given by `PORT`, and the frontend reads the backend URL from `VITE_API_BASE_URL`.

---

# 17. Development Principles

**Data before AI.** Ensure the underlying data is reliable before adding advanced AI functionality.

**ML predicts — the agent investigates.** The ML model provides the risk prediction. The agent collects the evidence around it.

**RAG grounds knowledge.** Recommendations cite operational procedures only when those procedures were actually retrieved.

**LLM explains.** The LLM turns structured findings into understandable operational communication. It does not replace the ML risk model and must not invent evidence or procedures.

**Human-in-the-loop.** The system provides recommendations and decision support. Final operational decisions remain with human users.

```text
AI
 ↓
Detect
 ↓
Investigate
 ↓
Recommend
 ↓
Human
 ↓
Decide
```

**Modular architecture.** ML, agent, tools, RAG, LLM, API, and frontend are independently testable.

**Reproducibility.** All team members should be able to reproduce the development environment and run the core application.

---

# 18. Future Improvements

Potential future enhancements include:

* Real-time shipment tracking
* Inventory linked to specific shipments and warehouses
* Verified supplier availability and capacity
* Route-level weather and port congestion monitoring
* Real-time news analysis
* Automated alerts and Email/Teams notifications
* What-if simulation
* Continuous model monitoring and drift detection

---

# 🎯 Project Vision

The ultimate goal is to move from:

```text
Reactive Logistics
       ↓
"Shipment has been delayed."
```

to:

```text
Predictive Logistics
       ↓
"Shipment is likely to be delayed."
       ↓
Prescriptive Support
       ↓
"Here is why it is at risk,
what it may affect,
and what alternatives are available."
```

The **Supply-Chain Disruption Agent** is designed to help operations teams identify potential disruptions earlier, understand their causes, and make better-informed decisions.

**Detect → Investigate → Explain → Recommend → Decide**
