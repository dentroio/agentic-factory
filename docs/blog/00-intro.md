# Intro — How we are building the product with agents

**Series:** Building with Agents and Work Orders
**Distribution:** Public (factory docs)

This is the series opener. It is background, not a table of contents. Part 1 is where Work Orders start.

---

Most “we use AI to write software” posts start in the IDE. This series is about the **direction we took instead**: treat coding agents as a factory with jobs, privileges, and a human at every irreversible step — not as a chat window that happens to emit a pull request.

the product is the product that factory is building: serious software for people who run networks and policy, large enough that no one person (and no one model) holds the whole system in their head. You do not need the architecture. You need to know we are not generating a toy app on a Sunday. The interesting story is **how we develop it**.

## The direction

We did not adopt agents because it was fashionable. We adopted them because a bounded change, specified well, is something several models can implement faster than we can type — and an *unbounded* change is how you get a brilliant, wrong pull request.

So the direction is:

1. **Write the bound down.** The unit of work is a Work Order: a spec in git that an agent can pick up cold. It is not a ticket title pasted into a prompt.
2. **One process, several agents.** Claude Code, Cursor, Codex, and a set of specialists (planner, reviewer, fixer, visual review) all follow the same rules. They do not all have the same job. The planner does not ship product code. The reviewer does not merge auth changes. The implementer does not skip a human looking at the running UI.
3. **Verify the way we actually run.** Our code is baked into containers. “The file changed” is not “the product changed.” Rebuild, then look. Remote agents that cannot run the stack do not get to pretend they did.
4. **Humans spend attention on truth, not lint.** Lint, tests, and pattern checks are automated. Clicking the feature and deciding whether it is *true* is not. Merge rights follow risk: a copy change and an authentication change are not the same privilege.
5. **The same instinct inside the product.** the product also ships agents for operators. They propose; a person approves before anything changes a live environment. How we *build* and how the *product* uses AI are cousins. Confusing them is how you ask a chatbot to open a GitHub PR, or an IDE agent to change production.

That is the thesis of the series:

> Agents propose. Humans gate the irreversible step.

If you came here for “prompt, PR, done,” you will be disappointed on purpose. If you are trying to use agents on software that can quietly break, you are the reader.

## Who this is for

- Engineering leads who have watched an agent open a brilliant, wrong pull request
- People building with Claude Code, Cursor, or Codex who need more than a rules file
- Anyone curious how Work Orders differ from tickets pasted into a chat

You do not need our stack. You need to care about **privilege**: which agent may plan, which may implement, which may comment, which may merge.

## What you will not get

This is not a product pitch. Later posts mention a screen or a bug only when it explains a factory choice.

This is not our internal runbook. That file tells agents in this repo what to type. These posts are why that file exists.

This is not a claim that models write the company. Humans still decide what is worth building and whether it is done. The direction is *where* that attention goes.

## The eight parts (development, in order)

**Part 1** — Why Work Orders: the constraint that “files on disk” are not the running product.

**Part 2** — What a spec must contain so an agent can cold-start, and why “out of scope” matters.

**Part 3** — How work is born: humans, a planning agent, failed dependency bumps. Agents may draft. They do not set their own risk.

**Part 4** — The cast: not “an AI,” but implementers, specialists, visual review, and the agents that ship in the product. Privilege is the plot.

**Part 5** — The loop: isolate the work, rebuild, *stop and ask a human*, then the local gate.

**Part 6** — GitHub and CI: what actually blocks merge, who may auto-merge, loop guards on bots that commit back.

**Part 7** — Many agents at once — and the rhyme with agents inside the product.

**Part 8** — What compounds, what still breaks, what to steal if you are not us.

A small story runs through the series: one feature went from broken, to a first fix, to a real redesign — and a leftover idea became the *next* Work Order instead of a surprise diff. That is the direction in miniature: bound the work, ship it, file the rest.

## How to read it

In order, starting here. If you only read two essays after this, read **Part 4** (who is allowed to act) and **Part 8** (what we still do not pretend).

The next post does not recap the product. It starts with an agent that rebuilt a container and would not commit until a human said the running UI was right.

That is the factory.

**Next:** [Part 1 — Why we build with Work Orders](01-why-work-orders.md)
