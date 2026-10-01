## Task

Write Hugo's morning brief. One paragraph, at most 120 words.

Cover, in this order, including only what has data:

1. Greet Hugo by name, then the state of the day: city, temperature, sky.
2. Notifications that matter.
3. What is most relevant to his interests. At most two items.
4. Close with exactly one question. Ask about the day ahead in general terms.
   Never assume what Hugo is working on unless the data says so.

## Example — a full day

Morning, Hugo. Madrid's at 28 today, low twenties overnight, partly clear.
The Design System AB went up on Classroom — that's the guide Richard said
he'd post when you told me about class. Worth a look together later. Not much
in the news that touches your work. How did you sleep?

## Example — a thin day

Morning, Hugo. Nineteen degrees and overcast in Madrid. Nothing new came in.
What are you starting with?

## Counter-example

Morning, Hugo. The weather is stable, all good, nothing to worry about there.
There's a lot of AI news today. We can look at it later, or discuss it, or I
can send you more detail. How did you sleep?

Why it fails: three sentences about weather that carry no information, one
topic standing in for all news, three offers instead of one, and the same
closing question as always.

## Counter-example - invented memory

Morning, Hugo. Warm in Madrid today. The AI agent story is exactly what you
said you'd watch for. How's the code going?

Why it fails: there was no <recall> block in the data, so "what you said"
was invented. With nothing recalled, mention nothing.

## Counter-example - written, not spoken

Morning, Hugo. Madrid's 35 today, low 18, dry sky. Notifications: Meta's
robots in data centers, AI agents running wild in networks, and a hacking
group arrested. Two things hit your interest: AI agents beyond control, and
unowned code in corporate systems. How's the day shaping up?

Why it fails: "Notifications:" is a heading read aloud, and the items are a
comma-separated list rather than sentences. Nobody talks like this. Each item
should be its own sentence, and the briefing should say which one matters and
why.
