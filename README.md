# Siam Command AI — The Orchestration Core Layer

Siam Command AI is the high-performance command center for the Master Architecture, acting as the bridge between Jarvis-VSCode and our cloud-native backend services. It orchestrates three critical pillars:

- **Supabase Layer**: Unified Authentication, Profile persistence, and AI memory storage.
- **Stripe Layer**: Secure subscription lifecycle, monetization enforcement, and automated billing portal.
- **OpenAI Layer**: State-of-the-art AI generation and automation tools powered by GPT-4-class models.

---

## 🚀 Quick Start

### 1. Environment Setup

Copy `.env.example` to `.env.local` and configure your credentials:

```bash
# App Configuration
NEXT_PUBLIC_APP_URL=http://localhost:3000

# Supabase (Auth & Database)
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# Stripe (Monetization)
STRIPE_SECRET_KEY=your_stripe_secret
STRIPE_PRICE_ID=your_price_id
STRIPE_WEBHOOK_SECRET=your_webhook_secret

# AI Engine
OPENAI_API_KEY=your_openai_key
OPENAI_MODEL=gpt-4o-mini
```

### 2. Local Development

```bash
npm install
npm run dev
```

---

## 🛠️ System Architecture

### 📡 Core API Routes

| Endpoint | Purpose |
| :--- | :--- |
| `/api/auth/*` | Full Auth lifecycle (SignUp, Login, Logout, Reset) |
| `/api/users/me` | Real-time Profile & Credit retrieval |
| `/api/dashboard/overview` | Aggregated data (Profile + Subs + Commands + AI History) |
| `/api/stripe/*` | Managed Billing (Checkout, Webhooks, Portal) |
| `/api/ai/generate` | Orchestrated AI prompt execution |

### 🗄️ Database Schema (`/supabase/schema.sql`)

The system follows a strict relational model for data integrity:
- `profiles`: Core user metrics including `ai_credits` and `plan` tiers.
- `subscriptions`: Real-time Stripe status mapping.
- `command_logs`: Auditable history of all system commands.
- `ai_generations`: Detailed tracking of AI usage and credit consumption.

---

## 🔗 Integration with Jarvis-VSCode

Siam Command AI serves as the **API Provider** for the [Jarvis-VSCode](../jarvis-vscode) extension. Ensure that the `NEXT_PUBLIC_APP_URL` is correctly referenced in the Jarvis Client settings to enable seamless cross-platform orchestration.

## 📦 Deployment

Optimized for deployment on **Vercel**. 
1. Push to your GitHub repository.
2. Connect to Vercel.
3. Add the required Environment Variables in the Vercel Dashboard.
4. Scale instantly.
