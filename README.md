# cirrus-cloudflare-agent

> A full-stack AI agent built entirely on Cloudflare — no traditional hosting, just a domain.

🌐 **Live demo**: [focuseffect.fr](https://focuseffect.fr)

---

## What is this?

**Cirrus** is an AI-powered web agent that runs 100% on Cloudflare's edge infrastructure. No servers. No traditional hosting. No cloud VMs. Just a domain name and Cloudflare.

It demonstrates that you can build a complete, production-grade application — with persistent memory, real-time AI responses, live data feeds, and a dynamic frontend — using only Cloudflare products.

---

## Cloudflare Stack

| Product | Role | Details |
|---|---|---|
| **Cloudflare Pages** | Frontend hosting | Static site deployed at the edge, globally distributed. Custom domain configured directly in Pages — DNS record auto-created. |
| **Cloudflare Workers** | Backend / API | Handles all AI requests, routing, and business logic. Two endpoints: `POST /chat` and `GET /news` |
| **Workers AI** | LLM inference | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` · max_tokens: 2048 |
| **AI Gateway** | Caching + monitoring | Gateway id: `default` · TTL: 3600s · request logging · cost visibility |
| **Workers KV** | Persistent memory | Binding: `CACHE` · stores last 3 conversation turns per user · TTL: 7 days |
| **Cloudflare DNS** | Custom domain routing | CNAME auto-created when adding custom domain in Pages dashboard |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        User Browser                          │
│         localStorage: userId · userName · chatHistory        │
└─────────────────────────┬────────────────────────────────────┘
                          │ HTTPS
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   Cloudflare DNS                             │
│    focuseffect.fr → CNAME → focuseffect-site.pages.dev       │
│    (auto-created by Pages custom domain setup)               │
└─────────────────────────┬────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│                   Cloudflare Pages                           │
│     Edge-served HTML/CSS/JS · 330+ datacenters worldwide     │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌─────────────┐  │
│  │  Agent   │ │ Products │ │ Calculator │ │    Audit    │  │
│  │ (Cirrus) │ │ Catalog  │ │            │ │    News     │  │
│  └──────────┘ └──────────┘ └────────────┘ └─────────────┘  │
└─────────────────────────┬────────────────────────────────────┘
                          │ fetch()
          ┌───────────────┴───────────────┐
          │ POST /chat                    │ GET /news
          ▼                               ▼
┌──────────────────────────────────────────────────────────────┐
│                   Cloudflare Worker                          │
│                                                              │
│  POST /chat                        GET /news                 │
│  ├─ Read KV memory (userId)        ├─ Fetch Cloudflare Blog  │
│  ├─ Build dynamic system prompt    │  RSS feed               │
│  │   · All CF products + pricing   ├─ Fetch Cloudflare       │
│  │   · Live UTC timestamp          │  Changelog RSS feed     │
│  │   · userName + language         └─ Return structured JSON │
│  ├─ Route through AI Gateway           (title, date, desc,   │
│  ├─ Call Workers AI (LLM)               source badge)        │
│  └─ Write updated memory to KV                               │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    AI Gateway                          │  │
│  │   id: "default" · Cache TTL: 3600s                     │  │
│  │   Request logging · Cost monitoring · Error tracking   │  │
│  └───────────────────────┬────────────────────────────────┘  │
│                          │                                   │
│                          ▼                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    Workers AI                          │  │
│  │   @cf/meta/llama-3.3-70b-instruct-fp8-fast             │  │
│  │   max_tokens: 2048                                     │  │
│  │   System prompt includes:                              │  │
│  │   · Full Cloudflare product catalog with pricing       │  │
│  │   · Live UTC timestamp (injected at runtime)           │  │
│  │   · User name + detected language                      │  │
│  │   · Conversation history from KV                       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    Workers KV                          │  │
│  │   Binding: CACHE                                       │  │
│  │   Key: userId · TTL: 7 days                            │  │
│  │   Value: last 3 conversation turns (JSON)              │  │
│  │   → Persistent memory across sessions                  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Zero origin servers. Zero traditional hosting. Everything runs at Cloudflare's edge.**

---

## Features

**Cirrus AI Agent**
- Conversational AI with persistent cross-session memory via Workers KV
- Automatic language detection (EN, FR, ES, PT, ZH, JA)
- User personalization via first name detection and localStorage
- Dynamic system prompt injected at runtime with live UTC timestamp and full Cloudflare product catalog with official pricing
- 5 rotating welcome messages per new conversation

**Product Catalog**
- 19 Cloudflare products with official pricing and direct links
- Sections: AI Platform · Core Products · Plans
- Products include: Workers AI, AI Gateway, AI Search, Vectorize, Cloudflare Agents SDK, CDN, DDoS Protection, WAF, Bot Management, Zero Trust, R2, Workers, Argo, Turnstile, SASE, and more

**Security Audit Tool**
- Enter any URL → Cirrus returns a fully structured analysis
- Security Gaps Detected: WAF, Bot Management, DDoS, Page Shield — with urgency badges
- Performance Improvements: CDN, Argo, Image Optimization, Waiting Room — with estimated % gains
- AI Platform Opportunities: tailored recommendations for the audited site's use case
- Itemized Cost Summary: per-product pricing + estimated savings
- "Ask Cirrus for a deeper analysis" → auto-sends URL and context to the agent

**Cost Calculator**
- Input: visitors/month · site type · storage needs · current setup
- Output: recommended Cloudflare plan + products with official pricing
- AI Opportunities section — contextual suggestions by site type:
  - E-commerce → Workers AI + AI Search
  - SaaS / API → Agents SDK + Durable Objects + Workflows
  - Media → Workers AI FLUX + R2
  - Blog → AI Search Beta
  - All types → AI Gateway (Free) + Vectorize
- "Ask Cirrus to refine my plan" → auto-sends full user profile to the agent

**Live News Feed**
- Cloudflare Blog + Changelog RSS feeds fetched live via Worker GET endpoint
- Returned as structured JSON: title · date · description · source badge
- Auto-rendered as cards in the frontend

**Navigation**
- Smooth section transitions with `history.pushState()` + `popstate` listener
- Browser back button fully functional
- Section hash restored on page reload
- Cirrus widget fixed bottom-right on all sections with contextual call-to-action bubbles

---

## Project Structure

```
/
├── src/
│   ├── index.js           ← Cloudflare Worker — POST /chat · GET /news
│   ├── cloudflare-data.js ← Official Cloudflare pricing data (19 products)
│   └── fetch-news.js      ← RSS feed parser — Blog + Changelog
├── public/
│   └── index.html         ← Frontend (generated by write_site.py)
├── write_site.py          ← Python script that generates the full frontend
└── wrangler.jsonc         ← Cloudflare Workers configuration
```

---

## Deploy it yourself

**Prerequisites**
- A Cloudflare account (free tier works for most features)
- A domain name added to Cloudflare
- Node.js 18+ and Python 3 installed locally

---

**1. Install Wrangler and authenticate**
```bash
npm install -g wrangler
wrangler login
```

**2. Create a Workers KV namespace for conversation memory**
```bash
wrangler kv namespace create CACHE
# Copy the returned id into wrangler.jsonc
```

**3. Configure `wrangler.jsonc`**
```jsonc
{
  "name": "focuseffect-agent",
  "main": "src/index.js",
  "compatibility_date": "2024-01-01",
  "kv_namespaces": [
    { "binding": "CACHE", "id": "YOUR_KV_NAMESPACE_ID" }
  ],
  "ai": { "binding": "AI" }
}
```

**4. Set up AI Gateway**

In your Cloudflare dashboard → AI → AI Gateway → create a gateway with id `default`.
All Workers AI calls are automatically routed through it for caching and monitoring.

**5. Deploy the Worker**
```bash
npx wrangler deploy
# Live at https://YOUR-WORKER.YOUR-SUBDOMAIN.workers.dev
```

**6. Generate and deploy the frontend**
```bash
python3 write_site.py
npx wrangler pages deploy public --project-name YOUR-PROJECT-NAME
# Live at https://YOUR-PROJECT.pages.dev
```

**7. Add your custom domain**

In Cloudflare Pages dashboard → your project → **Custom domains** → **Add custom domain** → enter your domain.
Cloudflare automatically creates the DNS record. No manual CNAME setup needed.

**8. Update the Worker CORS origin**

In `src/index.js`, update the allowed origin to your domain:
```js
'Access-Control-Allow-Origin': 'https://YOUR-DOMAIN.com'
```
Then redeploy:
```bash
npx wrangler deploy
```

---

**Full redeploy in one command**
```bash
npx wrangler deploy && python3 write_site.py && npx wrangler pages deploy public --project-name YOUR-PROJECT-NAME
```

---

## Key Concepts Demonstrated

- **Edge-first architecture**: every component runs across Cloudflare's network of 330+ data centers — no single origin server
- **AI at the edge**: LLM inference without managing GPU infrastructure — Workers AI handles it natively
- **Stateful edge functions**: Workers KV enables persistent memory across sessions without a traditional database
- **Zero-infrastructure deployment**: no EC2, no VPS, no Docker, no Kubernetes — just `wrangler deploy`
- **Full-stack from one provider**: DNS, CDN, compute, AI inference, caching, storage, and monitoring — all Cloudflare

---

## License

MIT
