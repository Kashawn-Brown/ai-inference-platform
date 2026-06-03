# How this was built

I built this with an AI coding agent. I'm saying that up front because it's the first thing people want to know — and because *how* you do it is the whole story. There's a real difference between directing an agent and just prompting one until something compiles, and I'd rather be straight about which this was.

What kept me on the directing side was a set of working files I maintained locally, alongside the code, the entire way through. They don't ship in the repo — some of it's personal, and publishing my notes was never the point — but they're worth describing, because they're what made this deliberate instead of random:

- A **brief** I wrote before any code — the architecture, the API, the data model, the phased plan, and an explicit list of things I was *not* going to build. Work ran against that contract, not a stream of one-off asks.
- A **plan** I kept iterating on top of as things came up, instead of branching off in a new direction every time something changed. Adding to one tracked plan rather than starting over is what kept me grounded.
- A **decisions log** — every real architectural choice written down with its reasoning and the alternatives I'd weighed. That's what stopped me from quietly relitigating a settled call two phases later, or contradicting an earlier one without noticing.
- A **build log and timeline** in plain language, no jargon — what happened and why at each step — so I could step away for days and pick back up knowing exactly where I was.
- A **standing set of instructions for the agent**: how I wanted it to work, the conventions to follow, and the scope it wasn't allowed to creep into.

None of that depended on the model, and that's the part I actually care about. The structure was doing the work, not the agent — I could have dropped to a weaker model on a given day and still gotten consistent results, because the next step and the reasoning behind everything already built were written down, not living in one model's context or one good session. It's also why I never lost track of what was in the codebase: at the points that mattered I stopped to genuinely understand what was being built instead of nodding it through and prompting onward, and the files are where that understanding got pinned down.

So — not prompt-and-accept. A system I built around the agent, so the decisions stayed mine and the result is something I can still explain and change, end to end.
