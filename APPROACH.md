# How this was built

Before any of the files, before any code, this was just me thinking through what it should be — how it should work, and what I was going to build. That thinking became the structure everything else followed.

I built it with an AI coding agent (Claude Code). But there's a real difference between directing an agent and just prompting one until things compile and it looks good. I wanted to own my code, not be lost in it: to stay in control of the decisions and the flow rather than hand them to a model.

What helped keep me on track was a set of working files I maintained locally, alongside the code, the whole way through. They don't ship in the repo — some of it's personal, and publishing my notes was never the point — but they're worth describing, because they're what made this deliberate instead of random:

- A **brief** where that thinking became a written contract — the architecture, the API, the data model, the phased plan — so work ran against something fixed instead of a stream of one-off asks.
- A **plan** I tracked development against and kept building on. It started as that full structure of the initial plan, but the real value showed when something new came up mid-build — a feature I hadn't thought of, a better approach — and I could weave it into the existing plan instead of veering off into chaos. It stayed one living document, and that's what kept me on track.
- A **decisions log** — every real architectural choice written down with its reasoning and the alternatives I'd weighed. That's what stopped me from quietly relitigating a settled call two phases later, or contradicting an earlier one without noticing.
- A **build log and timeline** in plain language, no jargon — what happened and why at each step — so I could step away for days and pick back up knowing exactly where I was and what I had done.
- A **standing set of instructions for the agent**: how I wanted it to work, the conventions to follow, and the scope it wasn't allowed to creep into.

One of the important parts that I actually care about, and why intentionally building in this way was key, was that nothing was dependent on the model. The structure was doing most of the work, not the agent — I could've dropped to a weaker model or gone up to a stronger one on any given day and still gotten consistent results because the next step and the reasoning behind everything already built were written down, not living in one model's context or one good session.

I never lost track of what was in the codebase because I stopped at the points that mattered, to actually understand what was being built, not just accept it. The files are where that understanding got written down.

So — not prompt-and-accept. It was a system I built around the agent, so the decisions stayed mine and the result is something I can still explain and change, end to end.
