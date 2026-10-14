# Lexicon Legal AI: SDR outbound brief

> **ILLUSTRATIVE DATA.** Built from mock signals, not a live collection. Do not use it for real outreach.

**Recommendation:** Pursue · **Tier:** B · **MEDDPICC:** 55/100 (62.5% coverage) · **Primary wedge:** Prompt caching (fit 86)

## Lexicon Legal AI: cut the cost of repeated context with Claude prompt caching

## Snapshot

| | |
|---|---|
| Domain | lexiconlegal.example |
| HQ | San Francisco, CA (in territory) |
| Stage | Series B · $48M raised · last round Mar 2026 |
| Headcount | 85 |
| Vertical | Legal tech |
| Hiring | 4 AI/ML of 18 open roles |
| Cloud | AWS |
| Incumbents | the OpenAI API and LangChain |

## Why now

- Raised a Series B round in Mar 2026 ($48M raised to date).
- Hiring for 4 AI/ML roles out of 18 openings, including 'Senior ML Engineer, Retrieval'.
- Building with the OpenAI API and LangChain today.
- Runs on AWS.

## Wedges

| Wedge | Fit | Confidence | Evidence |
|---|---|---|---|
| Prompt caching | 86 | 100% | E1, E5, E4, E2 |
| Cloud marketplace | 71 | 100% | E2, E3, E1, E4 |
| Extended thinking | 37 | 100% | E2, E1, E5 |

_Leads with prompt caching (fit 86); cloud marketplace is the second angle (fit 71)._

### Prompt caching

Lexicon Legal AI appears to send large, repeated context to an LLM (signals: RAG, long-document or support workloads; existing LLM API spend; inference cost is a stated priority). Prompt caching bills repeated prefixes at a fraction of the input price, so input spend should fall as volume grows.

**Proof points**

- On Claude Sonnet 5.5, cache reads bill at 0.1x the base input price and a 5-minute cache write at 1.25x, so a prefix reused twice already costs less.
- Caching a long shared prefix also cuts time to first token.
- Prefixes from 512 tokens cache on current Claude models.

**Impact (illustrative):** Input-token spend on repeated context. Illustration only: if 70% of input tokens are a shared prefix that hits the cache, those tokens bill at 0.1x, cutting input spend by about 63% (0.7 x 0.9), before cache-write costs. Needs: monthly input tokens, the share of each prompt that repeats, and the cache hit rate.

## MEDDPICC scorecard

| Element | Score | Status | Health | Evidence | Next action |
|---|---|---|---|---|---|
| Metrics | 4 | hypothesized | yellow | E1, E4 | Ask for current inference cost and the target that would justify a change. |
| Economic buyer | - | unknown | grey | - | Identify the CTO or a founder and confirm they own the AI budget. |
| Decision criteria | 5 | hypothesized | yellow | E5, E1 | Ask which criteria a model vendor must pass, and who checks them. |
| Decision process | - | unknown | grey | - | Ask how they chose their current model vendor and how long it took. |
| Paper process | 4 | hypothesized | yellow | E2, E3 | Ask whether they can buy through Amazon Bedrock and what review it needs. |
| Identify pain | 7 | hypothesized | green | E1, E5, E4, E2 | Roughly what share of each prompt is the same across calls (system prompt, retrieved documents, tool definitions)? |
| Champion | - | unknown | grey | - | Find the hiring manager for 'Senior ML Engineer, Retrieval'. |
| Competition | 6 | validated | yellow | E1, E4, E2 | Ask what would make them run a side-by-side on one workload. |

Tier B: 55/100 on 62.5% coverage. Strongest: identify pain and competition. Biggest gaps: economic buyer, decision process and champion. Recommendation: pursue.

## Talk track

Ask how much of each prompt repeats across calls. Explain prompt caching: the repeated prefix is cached, cache reads bill at 0.1x the input price on Claude Sonnet 5.5, and time to first token drops. Offer a side-by-side on one high-volume workflow, measured on their own evals.

## Call opener

Saw Lexicon Legal AI is hiring a Senior ML Engineer, Retrieval. Teams that send the same long context on every call (retrieved documents, system prompts, tool definitions) can cache it with Claude, so repeat reads bill at a fraction of the input price. Is that on your radar this quarter?

## Sequence

### Step 1 · Day 0 · Email

**Subject:** Repeated context at Lexicon Legal AI

Hi [First name],

Saw Lexicon Legal AI is hiring a Senior ML Engineer, Retrieval. Teams that send the same long context on every call (retrieved documents, system prompts, tool definitions) can cache it with Claude, so repeat reads bill at a fraction of the input price.

Roughly what share of each prompt is the same across calls (system prompt, retrieved documents, tool definitions)?

**CTA:** Worth 20 minutes to size it on one workflow?

### Step 2 · Day 2 · LinkedIn

Hi [First name], I work with startups building on LLMs. Teams that send the same long context on every call (retrieved documents, system prompts, tool definitions) can cache it with Claude, so repeat reads bill at a fraction of the input price. Glad to connect.

**CTA:** Connect

### Step 3 · Day 5 · Call

Saw Lexicon Legal AI is hiring a Senior ML Engineer, Retrieval. Teams that send the same long context on every call (retrieved documents, system prompts, tool definitions) can cache it with Claude, so repeat reads bill at a fraction of the input price. Is that on your radar this quarter?

Ask how much of each prompt repeats across calls. Explain prompt caching: the repeated prefix is cached, cache reads bill at 0.1x the input price on Claude Sonnet 5.5, and time to first token drops. Offer a side-by-side on one high-volume workflow, measured on their own evals.

**CTA:** Book a 20-minute technical session.

### Step 4 · Day 9 · Email

**Subject:** Re: Repeated context at Lexicon Legal AI

Hi [First name],

One question usually tells us whether this is worth a look: What is your monthly input-token volume, and which workload drives most of it?

If it isn't a priority this quarter, I'll close the loop.

**CTA:** A yes or no helps either way.

## Personas

- **Cto founder** (CTO, Co-founder, CEO): Lower input-token spend as usage grows, without a rewrite.
- **Ai ml lead** (Head of AI, ML Lead, Staff ML Engineer): Faster, cheaper calls on the workloads their team owns.

## Objections

- **We're standardized on another model provider.** Most teams don't switch wholesale. Run one cost-heavy workflow on Claude and compare cost and quality on your own evals.
- **Our stack is built around LangChain.** LangChain supports Claude, so a trial is mostly a model swap behind the same chains.
- **It's not a priority this quarter.** Understood. Which quarter would it be, and what would need to be true by then?

## Discovery questions

- Roughly what share of each prompt is the same across calls (system prompt, retrieved documents, tool definitions)?
- What is your monthly input-token volume, and which workload drives most of it?
- Which AI features are most cost-sensitive as usage grows?
- Identify the CTO or a founder and confirm they own the AI budget.
- Ask how they chose their current model vendor and how long it took.

## Evidence

- **E1** (Job posting): You'll ship RAG features on the OpenAI API, build evals for clause extraction, and keep per-document inference cost flat as volume grows. ([source](https://lexiconlegal.example/careers/senior-ml-engineer-retrieval))
- **E2** (Job posting): Our stack: Python, LangChain, Postgres/pgvector, AWS (EKS, S3, Lambda). ([source](https://lexiconlegal.example/careers/senior-ml-engineer-retrieval))
- **E3** (Dns): app.lexiconlegal.example is a CNAME for an AWS Elastic Load Balancer (elb.amazonaws.com).
- **E4** (Job posting): Experience operating high-volume OpenAI API workloads required; you'll own caching, rate limits and cost dashboards. ([source](https://lexiconlegal.example/careers/staff-engineer-llm-platform))
- **E5** (Job posting): Long-document reasoning over full agreements; SOC 2 handling of customer data. ([source](https://lexiconlegal.example/careers/applied-scientist-contract-intelligence))

---

_Signals are inferred from public data and may be incomplete or out of date. Verify them before outreach. Data source: mock. Generated 2026-10-01 16:00 UTC by mock LLM._
