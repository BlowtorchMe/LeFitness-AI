## Overview

This repository contains the FastAPI backend for the LE Fitness chatbot and booking system.
This README focuses on how to run it, configure it, and connect Meta and Google Calendar.

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: PostgreSQL (Neon as cloud DB); pgvector for FAQ embeddings
- **Deployment**: Vercel (serverless)
- **AI**: OpenAI (chat + FAQ embeddings via Haystack)
- **FAQ**: DB table `faqs` + pgvector RAG (embed query → retrieve top answer)
- **Integrations**:
  - Meta (Facebook/Instagram) Graph API
  - Google Calendar (service account + appointment schedule link)

## 1. Install Dependencies

```bash
pip install -r requirements.txt
```

Use Python 3.10+.

## 2. Environment Configuration

Copy the example file and edit:

```bash
# Windows PowerShell
Copy-Item .env.example .env

# Linux/Mac
cp .env.example .env
```

### 2.1 Core settings

See `.env.example` for the full list of variables.
Set at least:

- `OPENAI_API_KEY`
- `DATABASE_URL` (Neon connection string)
- Basic gym info (`GYM_NAME`, `GYM_EMAIL`, etc.)

For local testing with mock Meta, set:

- `USE_MOCK_APIS=true`
- `TEST_MODE=true`

### 2.2 How to get Meta (Facebook / Instagram) values

Steps to get the values for the Meta-related env vars:

1. **Create a Facebook App**
   - Go to Meta for Developers and create a new app (type “Business” or similar).
   - Add the “Messenger” product to this app.
   - In the app settings, you will see:
     - `App ID` → use for `META_APP_ID`
     - `App Secret` → use for `META_APP_SECRET`

2. **Connect a Facebook Page**
   - In the Messenger settings for your app, connect the Facebook Page you want to use.
   - Generate a **Page Access Token** for that page.
   - Use that token as `META_ACCESS_TOKEN`.
   - The Page ID is shown in the same area; use it for `META_PAGE_ID`.
   - This same page can receive both Facebook Messenger and Instagram Direct messages when configured.

3. **Set the webhook URL and verify token**
   - In Messenger → Webhooks, add a callback URL:
     - Callback URL: `https://your-domain.com/webhooks/meta` (or your local tunnel URL)
     - Verify Token: choose any string you like, and put the same value into `.env` as `META_VERIFY_TOKEN`.
   - Select the subscriptions (messages, messaging_postbacks, messaging_referrals, message_deliveries, message_reads).
   - Save and verify.

4. **Enable Instagram messaging (optional but recommended)**
   - In the same app, add the **Instagram** product.
   - In Instagram settings, connect the **Instagram Business account** that is linked to your Facebook Page.
   - Make sure “Allow access to messages” is turned on for the Instagram account.
   - In Webhooks, also enable the Instagram field (for example `instagram_messages`), so Instagram DMs are sent to the same `/webhooks/meta` endpoint.

5. **Subscribe the Page to the App**
   - Still in Messenger / Instagram settings, subscribe your Page (and Instagram account, if used) to this app so that messages from users are delivered to this webhook.

For console-only testing, you can skip all of this and just put dummy values for Meta fields while keeping `USE_MOCK_APIS=true`.

### 2.3 How to get Google Calendar values

Steps to prepare Google and fill the calendar-related env vars:

1. **Create a Google Cloud project**
   - Go to Google Cloud Console.
   - Create a new project (or choose an existing project for this bot).

2. **Enable Google Calendar API**
   - In the Cloud Console, go to “APIs & Services” → “Library”.
   - Search for “Google Calendar API” and enable it for this project.

3. **Create a service account**
   - Go to “APIs & Services” → “Credentials”.
   - Click “Create Credentials” → “Service account”.
   - Give it a name (e.g. `le-fitness-bot`).
   - After creation, go into the service account details and create a **JSON key**.
   - Download the JSON key file.
   - For local dev, you can point `GOOGLE_SERVICE_ACCOUNT` to the file path.
   - For Vercel, open the JSON file, copy its full contents, and paste it as a single-line JSON string into `GOOGLE_SERVICE_ACCOUNT` env.

4. **Choose or create the Calendar**
   - In Google Calendar (web UI), create or pick the calendar you want to use for bookings.
   - Go to that calendar’s settings:
     - Under “Integrate calendar”, find the **Calendar ID** (it usually looks like `something@group.calendar.google.com`).
     - Put that into `.env` as `GOOGLE_CALENDAR_ID`.

5. **Share the Calendar with the service account**
   - Still in the calendar settings, under “Share with specific people or groups”:
     - Add the service account email (from the JSON key).
     - Give it at least “Make changes to events” permission.

6. **Create an Appointment Schedule**
   - In Google Calendar (web UI), click on a time slot and choose “Appointment schedule” (or “Create” → “Appointment schedule”, depending on UI).
   - Configure your booking rules (duration, available days, times, etc.).
   - Save it.
   - Open the appointment schedule and copy the **booking page link** (the link you would send to customers).
   - Put that URL into `.env` as `GOOGLE_APPOINTMENT_SCHEDULE_LINK`.

7. **Set the webhook URL**
   - Decide the public URL where your backend will be reachable.
   - Set `.env`:
     - `GOOGLE_CALENDAR_WEBHOOK_URL=https://your-domain.com/webhooks/calendar`
   - On startup, the backend uses the service account to register a watch on `GOOGLE_CALENDAR_ID` pointing to that URL.

## 3. Database (Neon)

Use Neon as the PostgreSQL backend:

1. Create a project and database in Neon.
2. In the Neon dashboard, copy the connection string (Python / SQLAlchemy format).
3. Set `DATABASE_URL` in `.env`, for example:

```env
DATABASE_URL=postgresql://USER:PASSWORD@ep-example-123456.neon.tech/neondb
```

### Initialize tables

```bash
python -c "from app.database.database import init_db; init_db()"
```

This creates the required tables (`leads`, `bookings`, `conversations`, `faqs`) and enables the `vector` extension for FAQ embeddings.

## 4. Running Locally

Start the FastAPI app:

```bash
uvicorn app.main:app --reload
```

Health check:
- Open `http://localhost:8000/` in a browser or use `curl`.

API docs:
- `http://localhost:8000/docs`

### 4.5 FAQ (database + RAG)

FAQs live in the `faqs` table and are searched via pgvector. Chat uses FAQ first, then the general AI prompt.

**Seed FAQs:** Import `faq_seed.json` (project root) via the FAQ admin UI or `POST /api/faq/import` with the JSON array; use `?reindex=true` to run the indexer after import.

**Reindex:** Use the "Reindex" button in the FAQ admin UI, or `POST /api/faq/reindex`, or run:

```bash
python -m app.faq_indexer
```

## 5. Testing web chat (no Meta)

You can test the full chat flow using only the web chat page, without any Meta (Facebook/Instagram) setup.

**Required in `.env`:**
- `OPENAI_API_KEY` – for AI responses
- `DATABASE_URL` – for leads and conversations

**Optional:** `GYM_NAME`, `GOOGLE_APPOINTMENT_SCHEDULE_LINK` (for a real booking link in messages). Leave all Meta vars (`META_ACCESS_TOKEN`, etc.) empty.

**Steps:**

1. In `Fitness-Chatbot`, create `.env` with at least `OPENAI_API_KEY` and `DATABASE_URL`. No Meta or Google vars needed for web-only testing.

2. Initialize the database (if not already):
   ```bash
   python -c "from app.database.database import init_db; init_db()"
   ```

3. Start the backend:
   ```bash
   uvicorn app.main:app --reload
   ```

4. In another terminal, start the chat frontend (e.g. from the `Fitness-Chatbot-UI` sibling project):
   ```bash
   cd ../Fitness-Chatbot-UI
   npm install
   npm run dev
   ```

5. Open http://localhost:5173 and click **Start chat**. The flow is: welcome → name, email, phone → booking link. All traffic uses `POST /api/chat`; no Meta APIs or webhooks are involved.

## 6. Meta Webhook Integration (Live)

Once the backend is deployed to a public URL:

1. In `.env` on the server/Vercel, set real Meta credentials and disable mocks:

```env
USE_MOCK_APIS=false
TEST_MODE=false
```

2. In the Meta App dashboard:
   - Set the webhook callback URL to `https://your-domain.com/webhooks/meta`
   - Set the verify token to `META_VERIFY_TOKEN`
   - Verify the webhook
   - Subscribe the page to the app for messaging events

3. Connect the page to the app so that messages from users are delivered to this backend.

The conversation flow matches the web chat:
- Welcome message
- Profile gathering (name, email, phone) using plain text prompts
- Booking recommendation with a plain text appointment schedule URL

## 7. Google Calendar Webhook Behavior

On startup, the backend:
- Authenticates using the Google service account.
- Registers a watch on `GOOGLE_CALENDAR_ID` using `GOOGLE_CALENDAR_WEBHOOK_URL`.
- Schedules automatic renewal of the watch every few days.

When a user books through your `GOOGLE_APPOINTMENT_SCHEDULE_LINK`:
- Google Calendar creates the event.
- A webhook is sent to `/webhooks/calendar`.
- The backend:
  - Saves the booking to the database.
  - Tries to match it to an existing lead by email if possible.
  - Can send a confirmation message in chat when it detects the booking.

No Twilio or SMTP configuration is required; confirmations rely on Google Calendar’s own email notifications and the chat messages.

## 8. Deployment to Vercel

Basic flow:

1. Push the repository to GitHub.
2. Import the project in Vercel.
3. In Vercel project settings, add all required environment variables from `.env` (especially `OPENAI_API_KEY`, `DATABASE_URL`, Meta, and Google settings).
4. Vercel will build and deploy automatically.

Recommended Vercel settings:
- Install Command: `pip install -r requirements.txt`
- Build Command: leave empty (Vercel handles Python serverless functions)
- Output Directory: leave empty

Do not start `uvicorn` yourself on Vercel; `app.main:app` is used as the serverless entrypoint.

## 9. API Endpoints (Backend)

- `GET /` – health check
- `GET /api/leads` – list leads
- `GET /api/bookings` – list bookings
- `POST /api/chat` – web chat (for chat page instead of Messenger/Instagram)
- **FAQ**
  - `GET /api/faq` – list FAQs (paginated; query: `page`, `size`)
  - `GET /api/faq/{id}` – get one FAQ
  - `POST /api/faq` – add one FAQ
  - `PUT /api/faq/{id}` – update FAQ
  - `DELETE /api/faq/{id}` – delete FAQ
  - `POST /api/faq/import` – import FAQs from JSON array (optional `?reindex=true`)
  - `POST /api/faq/reindex` – run FAQ indexer (DB → pgvector)
- `POST /webhooks/meta` – Meta webhook handler
- `GET /webhooks/meta` – Meta webhook verification
- `POST /webhooks/calendar` – Google Calendar webhook handler

### Web chat (`POST /api/chat`)

Body: `{ "session_id": "optional", "message": "optional" }`. First request without `message` returns welcome + first profile question. Response: `{ "session_id": "...", "messages": ["..."] }`. Use the same `session_id` for the rest of the conversation. The companion React app is in the `Fitness-Chatbot-UI` project (sibling directory).

