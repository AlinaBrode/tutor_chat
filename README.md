# Tutor Chat

A simple tutor-style chat application that lets a student converse with a Gemini-based AI tutor through a web interface.

## Features
- Jinja-configurable system prompt with placeholders for task text, task image, solution image, and dialogue history.
- Turn-by-turn logging of conversations (JSON per dialog + JSONL log).
- Optional upload of task and solution images at dialog start.
- Configuration panel to update the Gemini model name and tutor prompt; the Gemini API key is read from the `GEMINI_API` environment variable.
- Separate panel to request automatic grading of a student's work using a configurable estimation template.
- Automatically fetches the list of available Gemini models on startup and exposes them in the settings dropdown.
- Resizable layout lets you shrink the chat area to expand the settings or estimation panel when it is open.
- Conversation export panel lets you browse saved dialogs, preview them, and download the full transcript as plain text.

## Getting Started
1. Create and activate a Python 3.10+ virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the backend:
   ```bash
   python -m backend.app
   ```
4. Open http://localhost:5000 in your browser.
5. Export your Google Gemini API key before starting the server, for example:
   ```bash
   export GEMINI_API="your-secret-key"
   ```
6. Adjust the prompt in the settings panel if needed.
7. Start a new dialog, optionally upload task/solution images, and begin the conversation.

## Configuration
Configuration is stored in `config.json`. The application exposes `/api/config` to fetch or update the prompt and model via the UI. Gemini credentials are never persisted; provide them through the `GEMINI_API` environment variable instead. A dedicated `estimation_template` key controls the grading prompt used by the "Оценить работу" panel.

## Student Work Estimation
- Open the "Оценить работу" panel and optionally provide task text/images and the student's work.
- Press "Оценить" to send the filled template to the LLM; results show the extracted score (`1-5`) and full feedback.
- Uploaded images are stored alongside other runtime uploads, and each estimation is logged in `data/conversations.log` with the rendered prompt and response.

## Conversation Export
- Open the "Экспорт диалогов" panel to load archived conversations.
- Pick a dialog from the dropdown (entries show start time and first user message) to view the prompt and turn-by-turn transcript.
- Use "Скачать диалог" to download the rendered transcript as UTF-8 plain text.

## Data Storage
- Conversations are saved under `data/conversations/` as JSON files.
- A rolling JSONL log of events is kept at `data/conversations.log` (ignored by Git).
- Uploaded images are stored in `data/uploads/` per dialog.

Both directories contain a `.gitkeep` file so the structure exists without committing runtime data.

## Frontend Build
The frontend is a simple static bundle (`frontend/` with HTML/CSS/JS) served directly by Flask; no build step is required.
