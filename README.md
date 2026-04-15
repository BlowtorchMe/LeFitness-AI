## Overview

This repository contains the FastAPI backend for the LE Fitness AI chatbot and booking system.
The companion frontend (`LeFitness-AI-Frontend/`) is a React + Vite + TypeScript app in the sibling directory.

## Tech Stack

- **Backend**: FastAPI (Python 3.10+)
- **Database**: PostgreSQL (Neon recommended); pgvector extension for FAQ embeddings
- **AI**: OpenAI (chat completions + embeddings via Haystack)
- **Integrations**: Meta Graph API (Facebook/Instagram DMs), Google Calendar (service account + push notifications)
- **Deployment**: Vercel (serverless) or any server running uvicorn

---

## 1. Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend)
- A [Neon](https://neon.tech) PostgreSQL database (free tier works)
- An OpenAI API key
- (Optional) A Google Cloud project with Calendar API enabled
- (Optional) A Meta Developer App for Facebook/Instagram

---

## 2. Environment Variables

Copy the example and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Neon (or any PostgreSQL) connection string |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `ADMIN_PASSWORD` | Yes | Password for the admin panel |
| `ADMIN_SESSION_SECRET` | Yes | Random secret for admin session cookies |
| `GOOGLE_SERVICE_ACCOUNT` | For calendar | Service account JSON (file path or inline JSON string) |
| `GOOGLE_CALENDAR_WEBHOOK_URL` | For calendar | Public URL where Google will POST notifications, e.g. `https://your-domain.com/webhooks/calendar` |
| `META_ACCESS_TOKEN` | For Meta | Facebook Page access token |
| `META_VERIFY_TOKEN` | For Meta | Webhook verify token (any string you choose) |
| `META_APP_ID` | For Meta | Meta App ID |
| `META_APP_SECRET` | For Meta | Meta App Secret |
| `META_PAGE_ID` | For Meta | Facebook Page ID |
| `USE_MOCK_APIS` | No | Set `true` to skip real Meta/Google calls during local dev |
| `TEST_MODE` | No | Set `true` to enable additional test shortcuts |

There are no per-gym calendar env vars. Calendar IDs and booking URLs are stored in the database via the admin panel.

---

## 3. Database Setup

### 3.1 Create a Neon database

1. Sign up at [neon.tech](https://neon.tech).
2. Create a new project and database.
3. Copy the connection string (SQLAlchemy format) and set it as `DATABASE_URL`.

### 3.2 Initialize tables

This command is safe to run repeatedly — it creates missing tables without dropping existing data:

```bash
python -c "from app.database.database import ensure_schema; ensure_schema()"
```

> **Warning:** `init_db()` drops and recreates all tables. Never run it on a database with real data.

---

## 4. Running Locally

### Backend

```bash
cd LeFitness-AI

# Create and activate a virtual environment (first time)
python -m venv .venv
.\.venv\Scripts\activate   # Windows PowerShell
source .venv/bin/activate  # Linux/Mac

pip install -r requirements.txt

uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

API docs: http://127.0.0.1:8000/docs

### Frontend

```bash
cd LeFitness-AI-Frontend
npm install
npm run dev
```

Chat UI: http://127.0.0.1:5173

The frontend expects the backend at `http://127.0.0.1:8000` by default. To point it at a different backend (e.g. a tunnel URL), set `VITE_API_URL` in `LeFitness-AI-Frontend/.env`.

---

## 5. Admin Panel

Visit http://127.0.0.1:5173/admin/login. Log in with `ADMIN_PASSWORD`.

### 5.1 Managing Gyms

Go to **Admin → Gyms**. Each gym has:

| Field | Description |
|---|---|
| Name | Display name |
| Slug | URL-safe identifier, e.g. `taby` |
| Location | Address shown in chat |
| Phone | Phone number shown in chat |
| Booking URL | Appointment schedule link shown to users (see Section 6.3) |
| Calendar ID | Google Calendar ID for push notifications (see Section 6.2) |
| Active | Only active gyms receive calendar notifications and appear in chat |

After adding or editing a gym, the backend automatically re-registers Google Calendar watchers in the background.

### 5.2 Managing FAQs

Go to **Admin → FAQs**. You can add FAQs one at a time or bulk-import from a JSON file.

**Bulk import format:**

```json
[
  {
    "question": "What are your opening hours?",
    "answer": "We are open 06:00–22:00 on weekdays and 08:00–20:00 on weekends.",
    "category": "hours"
  }
]
```

Use the **Import JSON** button on the FAQ list page, then click **Reindex** to embed the new FAQs into pgvector so they are searchable by the chatbot.

Alternatively, from the terminal:

```bash
python -m app.faq_indexer
```

---

## 6. Google Calendar Setup

This section explains how to set up Google Calendar so that when a user books an appointment, the chatbot automatically receives a notification and sends the user a confirmation message.

### 6.1 Create a Google Cloud project and enable the Calendar API

1. Go to [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g. `le-fitness`).
3. Go to **APIs & Services → Library**, search for **Google Calendar API**, and enable it.

### 6.2 Create a service account

1. Go to **APIs & Services → Credentials → Create Credentials → Service account**.
2. Give it a name (e.g. `le-fitness-bot`) and click through to finish.
3. Open the service account, go to the **Keys** tab, click **Add Key → Create new key → JSON**.
4. Download the JSON file. Keep it safe — it grants access to your calendars.

**For local development:**
Set `GOOGLE_SERVICE_ACCOUNT` to the file path, e.g.:
```env
GOOGLE_SERVICE_ACCOUNT=/path/to/service-account.json
```

**For Vercel (or any cloud deployment):**
Open the JSON file, copy the entire contents, and paste it as a single-line JSON string:
```env
GOOGLE_SERVICE_ACCOUNT={"type":"service_account","project_id":"...","private_key":"-----BEGIN RSA PRIVATE KEY-----\n..."}
```

Note the service account's email address — it looks like `le-fitness-bot@your-project.iam.gserviceaccount.com`. You will need it in the next step.

### 6.3 Identify the correct Calendar ID

> **Important — Google free accounts:** Google Appointment Schedules on free (non-Workspace) accounts always link to the **primary calendar** of the account that created them. The calendar ID for the primary calendar is simply the **Gmail address** of that account, e.g. `yourname@gmail.com`.
>
> If you use a group/shared calendar ID (`something@group.calendar.google.com`) but the appointment schedule is owned by a Gmail account, the bookings will appear on the Gmail account's primary calendar — not the group calendar — and the bot will not see them.
>
> **Rule:** Use the Gmail address as the Calendar ID in the admin panel for any gym whose appointment schedule was created by a Gmail account.

To confirm which calendar the bookings appear on:
1. Make a test booking using your appointment schedule link.
2. Open Google Calendar and check which calendar the new event appears on.
3. Use the settings of that specific calendar to find its Calendar ID.

For group/shared calendars:
- In Google Calendar, open the calendar's settings.
- Under **Integrate calendar**, copy the **Calendar ID** (e.g. `something@group.calendar.google.com`).

### 6.4 Share the calendar with the service account

The service account must have access to the calendar where bookings appear.

1. In Google Calendar, open the settings of the correct calendar (see 6.3).
2. Under **Share with specific people or groups**, click **Add people**.
3. Enter the service account email (from step 6.2).
4. Set permission to **Make changes to events**.
5. Save.

### 6.5 Create an Appointment Schedule (booking link)

1. In Google Calendar, click **Create → Appointment schedule** (or click a time slot and choose **Appointment schedule**).
2. Configure the schedule: duration, available days and hours, title, etc.
3. Save, then open the schedule and copy the **Booking page link**.
4. In the admin panel, paste this URL into the **Booking URL** field for the corresponding gym. This is the link the chatbot will send to users.

### 6.6 Configure the webhook URL

The backend must be reachable from the internet for Google to send push notifications.

1. Deploy the backend, or use a tunnel for local testing (e.g. [ngrok](https://ngrok.com): `ngrok http 8000`).
2. Set in `.env`:
   ```env
   GOOGLE_CALENDAR_WEBHOOK_URL=https://your-domain.com/webhooks/calendar
   ```
3. Restart the backend. On startup, it will register a watch for every active gym that has a Calendar ID set.

### 6.7 Add gyms in the admin panel

For each gym:
1. Go to **Admin → Gyms → Add Gym**.
2. Fill in the name, slug, location, phone, booking URL (from 6.5), and Calendar ID (from 6.3).
3. Make sure **Active** is checked.
4. Save.

The backend will immediately register a Google Calendar watch for the new gym.

### How it works end-to-end

1. A user chats with the bot and receives the appointment schedule link.
2. The user books an appointment at that link.
3. Google Calendar creates an event and sends a push notification to `/webhooks/calendar`.
4. The backend saves the booking to the database, matches it to the lead by email (if available), and updates the lead's status.
5. Within a few seconds, the chatbot sends the user a confirmation message without requiring any additional input from them.

---

## 7. Meta (Facebook / Instagram) Setup

### 7.1 Create a Meta App

1. Go to [Meta for Developers](https://developers.facebook.com/) and create a new app (type: **Business**).
2. Add the **Messenger** product to the app.
3. Note the **App ID** (`META_APP_ID`) and **App Secret** (`META_APP_SECRET`) from app settings.

### 7.2 Connect a Facebook Page

1. In Messenger settings, connect your Facebook Page.
2. Generate a **Page Access Token** → `META_ACCESS_TOKEN`.
3. Note the **Page ID** → `META_PAGE_ID`.

### 7.3 Register the webhook

1. In Messenger → Webhooks, set:
   - Callback URL: `https://your-domain.com/webhooks/meta`
   - Verify Token: any string you choose → set the same value as `META_VERIFY_TOKEN`
2. Verify the webhook. Subscribe to: `messages`, `messaging_postbacks`, `messaging_referrals`, `message_deliveries`, `message_reads`.

### 7.4 Instagram (optional)

1. In the Meta App, add the **Instagram** product.
2. Connect the Instagram Business account linked to your Facebook Page.
3. Enable "Allow access to messages" on the Instagram account.
4. Add the `instagram_messages` webhook subscription.

Instagram DMs arrive at the same `/webhooks/meta` endpoint.

---

## 8. Deployment to Vercel

1. Push the `LeFitness-AI` directory to a GitHub repository.
2. Import the project in [Vercel](https://vercel.com/).
3. In Vercel project settings, add all required environment variables (see Section 2).
4. Set:
   - **Framework Preset**: Other
   - **Root Directory**: `LeFitness-AI` (if the repo contains only the backend)
5. Deploy. Vercel uses `app.main:app` as the serverless entry point automatically.

> Do not configure uvicorn manually on Vercel. It is only needed for local development.

For the frontend (`LeFitness-AI-Frontend`), deploy it as a separate Vercel project and set `VITE_API_URL` to the backend's Vercel URL.

---

## 9. FAQ Indexing

FAQs are stored in the database and embedded into pgvector for semantic search. The chatbot queries embeddings first before falling back to the LLM.

After adding or editing FAQs via the admin panel, click **Reindex** on the FAQ list page, or run:

```bash
python -m app.faq_indexer
```

On a fresh database, the vector store is empty until this runs. The chat will work via LLM fallback but will not use FAQ retrieval.

---

## 10. API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Health check |
| `POST` | `/api/chat/` | Web chat endpoint |
| `GET` | `/api/leads` | List leads (admin) |
| `GET` | `/api/bookings` | List bookings (admin) |
| `GET` | `/api/faq` | List FAQs |
| `POST` | `/api/faq` | Create FAQ |
| `PUT` | `/api/faq/{id}` | Update FAQ |
| `DELETE` | `/api/faq/{id}` | Delete FAQ |
| `POST` | `/api/faq/import` | Bulk import FAQs from JSON array |
| `POST` | `/api/faq/reindex` | Reindex FAQs into pgvector |
| `GET` | `/api/gyms` | List gyms |
| `POST` | `/api/gyms` | Create gym |
| `PUT` | `/api/gyms/{id}` | Update gym |
| `DELETE` | `/api/gyms/{id}` | Deactivate gym |
| `GET` | `/webhooks/meta` | Meta webhook verification |
| `POST` | `/webhooks/meta` | Meta webhook handler |
| `POST` | `/webhooks/calendar` | Google Calendar push notification handler |

**Web chat request:**

```json
{ "session_id": "optional-uuid", "message": "optional user text" }
```

**Web chat response:**

```json
{ "session_id": "uuid", "messages": ["Bot reply..."] }
```

Omit `message` on the first request to receive the welcome message and initial profile question. Reuse the same `session_id` for the full conversation.
