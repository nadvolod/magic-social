# Variant judge report — Issue #422

_Drafts: `drafts/2026_05_17_temporal_replay_conference_review`._
_References: 3 top-performing posts from `screenshot_learning.json`._

## Per-variant scores

| Variant | RawIdea | Specificity | RefExceed | Voice | Diagnosis |
|---|---|---|---|---|---|
| variant_1 | 3 | 3 | 4 | 4 | To score higher, it needs more of the actual conference texture from the Raw Idea—specific workshops, speakers, and the unusual event details—so it feels unmistakably tied to this exact trip rather than a generalized Temporal recap. |
| variant_2 | 3 | 3 | 3 | 4 | To improve, it should add the unique conference moments from the Raw Idea and a more personal observation that only someone at this specific event would mention. |
| variant_3 | 3 | 4 | 4 | 4 | To be clearly stronger, it needs at least one or two unmistakable Raw Idea details and a more lived-in conference moment so it feels like a firsthand event post rather than a generalized AI ops checklist. |
| variant_4 | 3 | 3 | 3 | 4 | It would need more specific firsthand observations from the actual conference and a less abstract thesis to feel more like a memorable own-voice post. |
| variant_5 | 3 | 3 | 2 | 4 | To compete better, it needs either a more distinctive personal observation from the conference or a sharper insight that goes beyond the familiar replay/retry framing. |

## Reasons per variant

### variant_1
- **raw_idea_fidelity** (3/5): It keeps the core subject of Replay by Temporal and AI/durable execution, but it drops major Raw Idea specifics like the 2000+ engineers, the Nexus workshop with Mason, Melissa’s AI-focused conference, Netflix/OpenAI presentations, and the secret Tiki room/concert/cotton candy details.
- **specificity** (3/5): It includes concrete anchors like "Replay by Temporal," "giant Ziggy," "retries against the wrong boundary," and "replay-safe," but most of the post stays at a conceptual level rather than naming the actual people, workshops, or conference experiences from the Raw Idea.
- **reference_exceedance** (4/5): Compared with the references, it adds a sharper contrarian thesis—"Most conference takeaways are too vague to survive first contact with production"—and a stronger production-engineering angle around failure modes and replay safety.
- **voice_authenticity** (4/5): It reads like a real LinkedIn post with first-person framing, short punchy lines like "They won't." and a direct question at the end, though some phrasing such as "durable execution is becoming table stakes" feels polished rather than personal.

### variant_2
- **raw_idea_fidelity** (3/5): It preserves the main event and theme with "Replay by Temporal," "Temporal Replay," and "giant Ziggy," but it omits the Raw Idea’s distinctive elements like the 2000+ attendees, Nexus workshop, Mason, Melissa, Netflix, OpenAI, and the secret Tiki room/concert.
- **specificity** (3/5): The post uses concrete scene details such as "a room full of laptops," "rows of engineers," "workflow diagram," and "walking through the venue under the big Replay by Temporal signage," but it still lacks the richer named specifics present in the source.
- **reference_exceedance** (3/5): It is solid and readable, but it mostly rephrases the same durable-execution/replay message already common in the reference cohort rather than offering a clearly fresher angle or new substance.
- **voice_authenticity** (4/5): The first-person setup, simple sentence structure, and reflective line "That scene said a lot" feel natural for LinkedIn, though the post is somewhat polished and generic in its cadence.

### variant_3
- **raw_idea_fidelity** (3/5): It stays on-topic with Replay by Temporal and AI systems, but it strips away nearly all Raw Idea specifics beyond the event name, leaving out the 2000+ engineers, workshops, speakers, and the social/conference details.
- **specificity** (4/5): It is more concrete than many generic posts because it lists four explicit checklist questions—"What gets retried automatically?" and "How do you recover after a worker crash or deploy?"—and mentions "packed sessions" and "giant Ziggy."
- **reference_exceedance** (4/5): The checklist format gives it a more actionable, reusable angle than the references, which makes it plausibly stronger for readers who want a tactical takeaway rather than a recap.
- **voice_authenticity** (4/5): It sounds like a real practitioner post with a personal filter—"I now want four answers immediately"—and a conversational close, though it still leans into polished framework language.

### variant_4
- **raw_idea_fidelity** (3/5): It correctly centers Replay by Temporal and durable execution, but it omits the Raw Idea’s specific conference content such as the Nexus workshop, Melissa, Netflix/OpenAI talks, and the Tiki room/music/cotton candy experience.
- **specificity** (3/5): There are concrete details like "packed rooms," "architecture slides," "recovery, retries, and resumability," and "giant Ziggy hanging over the venue," but the post still reads more like a synthesized industry take than a specific event memory.
- **reference_exceedance** (3/5): The argument about interruption and resuming agents is coherent, but it does not clearly surpass the reference cohort because it stays within the same durable-execution framing without a distinctly new insight or story.
- **voice_authenticity** (4/5): The post has a credible LinkedIn cadence with first-person reflection and a balanced, experienced tone, though lines like "AI infrastructure is converging with workflow reliability" feel a bit abstract and editorialized.

### variant_5
- **raw_idea_fidelity** (3/5): It keeps the Replay by Temporal subject and the durable-execution theme, but it leaves out nearly all of the Raw Idea’s distinctive details, including the 2000+ engineers, workshops, speakers, and the unusual entertainment elements.
- **specificity** (3/5): The post has some concrete anchors—"replay, retries, and resumability," "giant Ziggy," and the failure modes "timeout, duplicate work, or partial completion"—but it is otherwise very compressed and generic.
- **reference_exceedance** (2/5): It is concise, but it does not add enough fresh substance beyond the standard Temporal/durable-execution message to clearly beat the strongest reference posts.
- **voice_authenticity** (4/5): The short, direct phrasing and the closing question feel like a real LinkedIn engagement post, though the brevity also makes it sound more templated than lived-in.

## Verdict

FAIL — v2 model did NOT meet the acceptance bar.
- Only 0 of 5 variants met the (raw_idea_fidelity >= 4 AND reference_exceedance >= 3) bar; need 3.
- Median raw_idea_fidelity = 3.0 (< 3.5)
- Median specificity = 3.0 (< 3.5)
- Median reference_exceedance = 3.0 (< 3.5)
