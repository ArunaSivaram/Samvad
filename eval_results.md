# Gita Study Assistant -- eval results

Run of `python eval.py` against the fixed test set. Each question is sent through `answer(q, k=3)`.

| # | Question | Expected verses | Retrieved? | Invalid citations | Answer (first 120 chars) |
|---|---|---|---|---|---|
| 1 | doing your duty without attachment to results | 2.47, 3.19 | ✓ 3.19 | — | ## Doing Your Duty Without Attachment to Results  The Bhagavad Gita provides clear guidance on this principle:  ### Perf… |
| 2 | the soul is never born and never dies | 2.20, 2.19, 2.21 | ✓ 2.20 | — | ## The Soul Is Never Born and Never Dies  The Bhagavad Gita directly affirms this truth. Krishna states that the soul (t… |
| 3 | how to sit for meditation | 6.11, 6.12, 6.13 | ✗ (got 2.61, 3.40, 12.6) | — | ## How to Sit for Meditation  The Bhagavad Gita, in the verses provided, does not give detailed physical instructions ab… |
| 4 | staying calm in pleasure and pain | 2.14, 2.38, 2.15 | ✗ (got 18.36, 18.38, 6.17) | — | ## Staying Calm in Pleasure and Pain  The verses provided give some relevant guidance, though they focus more on the *na… |
| 5 | surrendering everything to God | 18.66 | ✗ (got 3.30, 5.29, 5.28) | — | ## Surrendering Everything to God  Based on the provided verses, the Bhagavad Gita offers clear guidance on surrendering… |
| 6 | who speaks the first verse of the Gita | 1.1 | ✗ (got 10.20, 11.39, 11.38) | — | Based on the verses provided, I cannot answer this question. The retrieved verses come from chapters 10 and 11, and none… |
| 7 | I'm anxious about my exam results | 2.47, 2.48 | ✗ (got 2.40, 18.73, 10.36) | — | I don't see verses in the Gita that directly address this question. The closest matches had low similarity scores, which… |
| 8 | compare the path of action and the path of devotion | — | 12.5, 12.19, 13.28 (n/a) | — | # Comparing the Path of Action and the Path of Devotion  The verses you've provided offer only a limited basis for a dir… |
| 9 | what's the stock market outlook? | — | 17.16, 13.6, 16.13 (n/a) | — | I don't see verses in the Gita that directly address this question. The closest matches had low similarity scores, which… |
| 10 | what does chapter 19 verse 5 say? | — | 5.26, 10.1, 12.19 (n/a) | — | The Bhagavad Gita contains only 18 chapters. There is no Chapter 19, and therefore no Chapter 19, Verse 5 exists within… |

## Summary

- **Retrieval hit rate (Q1–Q7):** 2/7 = 29%
- **Answers with invalid citations:** 0 of 10

## Judge by eye -- Q9 (polite decline) and Q10 (no chapter 19)

**Q9 (polite decline expected)** — _what's the stock market outlook?_

> I don't see verses in the Gita that directly address this question. The closest matches had low similarity scores, which usually means the question is phrased very differently from the text or it covers material the Gita does not discuss. Try rephrasing, or ask about a specific chapter or verse.

**Q10 (no chapter 19 expected)** — _what does chapter 19 verse 5 say?_

> The Bhagavad Gita contains only 18 chapters. There is no Chapter 19, and therefore no Chapter 19, Verse 5 exists within the text. The provided verses do not contain any such reference either.
> 
> If you are interested in a specific topic or a verse from one of the 18 actual chapters, I would be happy to help you find it.
