# Screenshot extraction prompt (multimodal)

Used by `src/reference_posts.py` to extract structured data from a LinkedIn post screenshot.

The runtime sends this as the user content alongside the image. Keep instructions terse — multimodal models follow short, direct instructions better than long ones.

---

You are extracting structured data from a single screenshot of a LinkedIn post.

Return ONLY a JSON object with this schema. Use `null` for any field you cannot read with high confidence.

    {
      "author": "<full name visible at top, or null>",
      "author_role": "<job title from byline, or null>",
      "post_text": "<full text of the post body, preserving line breaks as \\n>",
      "hook": "<the first sentence of the post body>",
      "post_type": "<event_reflection | tutorial | contrarian | story | result | question | announcement | other>",
      "tone": "<reflective | tactical | contrarian | celebratory | analytical | other>",
      "emotional_angle": "<personal_transformation | technical_authority | warning | curiosity | other>",
      "cta_type": "<question | comment_request | link_click | none | other>",
      "visible_likes": <integer or null>,
      "visible_comments": <integer or null>,
      "visible_reposts": <integer or null>,
      "visible_impressions": <integer or null>,
      "estimated_performance": "<high | medium | low | unknown>",
      "uncertain_fields": ["<list any field names you guessed>"]
    }

Rules:
- Never invent. If a metric is not visible, return null and add the field name to `uncertain_fields`.
- `estimated_performance` is your judgment: high = clearly above-average engagement for a LinkedIn post (e.g. 100+ likes or many comments), medium = typical, low = sparse engagement.
- Preserve all line breaks and paragraph structure in `post_text` using `\n`.
- Do not include any commentary outside the JSON.
