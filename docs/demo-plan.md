# 2-3 minute camera-on YouTube demo plan

Target duration: about 2 minutes 30 seconds. Record with camera on and the app visible beside the presenter. Do not upload until the owner reviews the video, verifies license/credential hygiene, and approves publication.

| Time | Show and say |
|---|---|
| 0:00-0:20 | On camera: introduce the Lenny Growth Assistant take-home, the product-builder audience, and the goal of grounded advice with traceable sources. |
| 0:20-0:45 | Show the architecture briefly: existing transcript archive location, FastAPI, ChromaDB, Ollama local model, PostgreSQL, and configurable provider/agent settings. Do not show `.env` values. |
| 0:45-1:20 | Ask a representative product/growth question. Explain retrieval in one sentence, then open at least one returned source reference and show persisted conversation history. |
| 1:20-1:40 | Ask an out-of-scope question and demonstrate explicit insufficient evidence without citations. |
| 1:40-2:10 | Generate a Ship 30 for 30 essay; show its actual word count and sources in the Artifact Viewer. If time permits, show the isolated HTML preview and mention sandbox/CSP. |
| 2:10-2:30 | Close on verified results, one honest limitation (live service/configuration or approximate essay length), and the next step. End recording without showing secrets, transcript dumps, or private account details. |

Before recording, run the local manual test plan, ensure Ollama and DB are healthy, use a clean demo browser account, verify the selected model, and prepare one relevant and one irrelevant question. The demo video is a deliverable for the owner to record; this plan does not publish anything.
