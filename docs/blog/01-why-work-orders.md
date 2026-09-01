# Part 1 — Why we build with Work Orders

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

If you have not read the [series intro](00-intro.md), start there. This post is not about what the product does. It is about why we develop it with Work Orders.

---

On a Saturday night an agent rebuilt a Docker container, asked a human to click a tab in a browser, and refused to commit until that human said the running UI was right.

That is not how most people imagine “AI coding.” The popular picture is a chat window, a wall of generated files, and a pull request that someone rubber-stamps because the tests are green. Sometimes that works. It does not work for a product this size.

the product is large enough that nobody holds the whole system in their head, including the models. The delivery constraint is worse than size: **code is baked into Docker images**. Editing a file on disk does nothing until the affected container is rebuilt. An agent that “finishes” by committing untested source has not finished. It has described a change that is still invisible in the only environment that matters.

We needed a way for several coding agents — Claude Code, Cursor, OpenAI Codex, sometimes Codex running inside GitHub Actions — to implement real product work without:

- ripping each other off the same git checkout
- shipping a migration that never runs
- exposing an API route with no RBAC
- merging an auth change because CI was green
- asking “what should I do next?” after every file edit

The answer is not “let the model roam the repo.” The answer is a **Work Order**: a markdown spec that is the agent’s job ticket, plus a **single process file** every agent platform is pointed at, plus **CI that encodes the same invariants** the process file describes.

A Work Order is not a ticket in Jira that someone later pastes into a prompt. It *is* the prompt. It lives in git, is reviewed like code, and is still readable six months later. Open `the redesign WO-service-discovery-redesign.md` today and you can see the problem, the scope, what was deliberately left out, and the follow-on that was filed during review. That file is how the product was actually built — not a Slack thread, not a forgotten chat.

## The unit of intent

Software teams have always needed a unit of work. Tickets, stories, RFCs, “the thing we talked about Tuesday.” Most of those artifacts are written for humans who will hold a meeting and then type. Agents do not attend meetings. They read files.

So the Work Order is written for a reader who:

- has no memory of yesterday’s conversation
- will follow instructions literally
- will expand scope if you leave a tempting extra in the same paragraph as the real job
- will guess if a file path is missing
- can be excellent *inside a box* and chaotic outside it

That is the **cold start test**, and it is the whole design of Part 2. If an agent with zero chat history cannot implement the spec correctly, the spec is not done. Clarifying questions feel cheap in a chat. They are expensive in a factory: they break autonomy, they serialize humans, and they produce a second Work Order to undo the first.

The other design choice is **scope as a first-class section**. A good Work Order names the extras you noticed and refuses them. During the the import UI redesign, live review surfaced a better way to classify internal versus external destinations — the product already has a real `subnets` table from device discovery, more accurate than a blanket private-range check. That idea did not go into the same pull request. It became the next Work Order. The agent stayed autonomous because the box stayed small.

## Two factories, one rhyme

the product has two kinds of AI, and it is worth naming them in the first post so later posts do not smash them together.

**Dimension 1 — Agents that build the product.** Coding agents implement Work Orders, rebuild containers, open pull requests, and merge under rules. Humans still decide priority, risk, and whether the running UI is true.

**Dimension 2 — Agents that run inside the product.** Product agents (in-product chat in the sidebar, scheduled jobs in the AI Harness) look at live network data, draft findings, and queue actions. Operators still approve anything that would change the customer’s network.

They rhyme on purpose. In both cases AI proposes and a human gates the irreversible step. In Dimension 1 that step is merge to `main`. In Dimension 2 it is a mutating action against a live environment. An approval queue in the product is the cousin of the “please click this tab before I commit” checkpoint coding agents are required to hit.

This series is mostly Dimension 1 — how the product is built. Dimension 2 walks on in Part 4 (the roster) and gets a proper tour in Part 7, because the interesting claim is not “we use AI.” It is that **the way we build the product and the way the product uses AI are the same idea at two scales.**

## Why not just “prompt the repo”?

Three reasons, all learned the expensive way.

**1. The model is not the process.** Claude Code, Cursor, and Codex do not share a chat log. They share a repository. If the process lives in one person’s head, or in one IDE’s memory, the next agent starts cold and guesses. `AGENT_PROCESS.md` is the process. `CLAUDE.md`, `AGENTS.md`, and Cursor’s always-on rule file are three front doors into the same building. Part 4 is about every other agent in that building — planners, reviewers, fixers, visual review — because implementers are only the visible layer.

**2. Green tests are not a running product.** the product's frontend has two lives: Vite for hot reload, and an nginx container that bakes the production build. Committing because Vite looked right is how you ship a stale nginx image. The factory treats container rebuild as part of “done,” not as ops afterthought. Part 5 is that loop.

**3. Autonomy without a budget is negligence.** A copy change and an authentication change should not have the same merge rights. Risk tiers (P0 through P3) are the autonomy budget: who verifies, who merges, whether Docker is even involved. Part 2 defines them; Part 6 enforces them on GitHub.

## What this series is not

It is not a claim that agents write the product unsupervised. The load-bearing beam is a human looking at `https://localhost` and saying the feature is true. Remove that beam and you get green CI with a page that still lists discovery-protocol noise as a “service.”

It is not a generic “how we use Cursor” post. The interesting machinery is Work Orders, claim files, worktrees, a PR Gate that re-checks the product-specific scars (`db.commit()`, registered migrations, RBAC), and a swarm of specialist agents that never implement the feature but keep the factory from lying.

It is not Dimension 2’s operator manual. If you want how in-product chat routes a question to the Identity Agent, that is Part 7 and the agent catalog. If you want how a markdown file becomes a running tab in the product, keep reading.

## The story we will keep coming back to

the import UI started as an empty import list (lookback window too tight). Then it was a cramped modal with garbage names (`z.example.test` became “Z”) and discovery-protocol noise dressed up as applications. Then it was a full-width tab with a Protocol column and the noise gone. Then someone asked whether the product's own subnets should classify internal traffic, and that question became a new Work Order instead of a 2,000-line surprise.

Observe. Specify. Isolate. Implement. Bake. Verify. Gate. Merge. File the leftover.

That loop is how the product is being built. The next post is the artifact at the center of it: what a Work Order actually contains, and why a vague one is more dangerous than no ticket at all.

**Next:** [Part 2 — Anatomy of a Work Order](02-anatomy-of-a-work-order.md)
