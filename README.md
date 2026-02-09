# Documentation: Agentic Price Tracker

## 1. Project Overview

This application is an **AI-powered Price Monitoring Agent** that tracks and compares products across **Amazon** and **Flipkart**. Unlike traditional scrapers, it uses a **Large Language Model (LLM)** to perform entity resolution and data extraction from unstructured web content.

### Key Features:

* **Intelligent Entity Matching:** Uses LLM-based fuzzy matching to identify if a query (e.g., "iPhone 17 Pro") matches an existing database entry, preventing duplicate records.
* **Multi-Tiered Data Retrieval:** Implements a "Cache-First" strategy to minimize scraping latency and LLM API costs.
* **LLM-Powered Extraction:** Leverages **Ollama (Gemma 3:12b)** or **OpenAI** to extract precise pricing from messy HTML search results.
* **Persistent Storage:** Utilizes **PostgreSQL** with `UPSERT` logic for efficient data management.

---

## 2. System Architecture

The system follows a modular "Agentic Workflow":

1. **Request Layer:** User inputs a product name via the **Gradio UI**.
2. **Reasoning Layer (The Matcher):** The agent pulls existing product names from the DB. An LLM determines if the input is a new product or an update to an existing one.
3. **Search & Scrape Layer:** If data is stale (> 24 hours) or missing, the agent generates search URLs for Amazon and Flipkart and retrieves the HTML.
4. **Extraction Layer (The Parser):** The LLM parses the raw text to find the most relevant price, returning a structured JSON object.
5. **Persistence Layer:** Data is saved to PostgreSQL, updating timestamps for future "freshness" checks.

---

## 3. Database Schema

We utilized a **Normalized Matrix approach** to handle cross-site comparisons in a single row.

---

## 4. Code Documentation (`app.py`)

### `get_best_match(user_query)`

* **Purpose:** Handles the "Model Differentiation" problem (e.g., S24 vs S25).
* **Logic:** Passes the query and a list of DB keys to the LLM. It forces the agent to decide if it should create a new record or update an old one.

### `scrape_site(query, site)`

* **Purpose:** Fetches raw HTML and cleans it.
* **Process:** Removes non-content tags (`<script>`, `<nav>`) to fit the LLM's context window and passes the "clean" text to the extraction function.

### `call_llm(html_text, query)`

* **Purpose:** Converts unstructured text to JSON.
* **Constraint:** Uses `temperature=0` and `json_object` response format to eliminate hallucinations and ensure deterministic output.

---
