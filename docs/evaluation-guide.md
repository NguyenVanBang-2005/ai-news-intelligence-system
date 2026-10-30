# Labeling guide: topic and summary quality

One page for people who label `local-data/corpus_to_label.csv`. The file is created by
`scripts/export_corpus.py` and is never committed: it lists real articles.

## Before you start

- Make your own copy of the CSV, named after you: `local-data/labels_<name>.csv`.
- Label alone. Do not look at the other labeler's file until both are finished.
- Read each article at its `url`. For the summary, open the article in the web UI.
- Fill only these columns; leave all others unchanged:

| Column | What to write |
|---|---|
| `topic_correct` | `yes`, `no` or `unsure` (lower case) |
| `human_topic` | Your own short topic for the article, 1-4 words (always fill it) |
| `extractive_summary_ok` | `yes` / `no`: is the extractive summary in the UI (sentences taken from the article) usable as is? |
| `summary_score_1_to_5` | A whole number from 1 to 5 (scale below) |
| `notes` | Anything odd: paywall, page not found, not about AI, video only... |

## topic_correct

Look at `model_topic` (keywords such as `investors · stock · enterprise · market`).

- **yes**: the keywords describe the main subject of the article. One of the four words
  may be off, as long as the overall theme fits.
- **no**: the theme does not fit, or it only matches a side remark in the article.
- **Other / Outlier**: answer `yes` if the article really does not belong to any of the
  other topics in the file, `no` if it clearly fits one of them (name it in `notes`).
- **unsure**: you read the article and still cannot decide. Explain why in `notes`.

## summary_score_1_to_5

| Score | Meaning |
|---|---|
| 1 | Wrong or meaningless: states things the article does not say, or is unreadable |
| 2 | Mostly off: about the article, but misses the main point or is mostly boilerplate |
| 3 | Gets the main point, but leaves out important facts |
| 4 | Main point and most key facts; small gaps or awkward wording |
| 5 | All main points, no errors, reads well |

Judge the content, not the style. Leave the cell empty if there is no summary.

## When you are not sure

- Do not guess. Use `unsure` for the topic, leave the score empty, and write the reason in
  `notes`.
- If the page cannot be opened (paywall, 404, login), leave `topic_correct` and the score
  empty and write `cannot open` in `notes`.
- Do not change your answer after seeing the other labeler's file. Disagreements are
  discussed afterwards and recorded separately.

## Two labelers per article

Each article is labeled by two people independently, then the two files are compared:

```
python scripts/score_corpus.py local-data/labels_A.csv local-data/labels_B.csv
```

The script prints, for each file: number of labeled rows, share of `topic_correct = yes`
(`unsure` is left out of the denominator and its count is shown), summary score mean and
1-5 distribution, and the outlier share of the sample. For the pair it prints:

- **Percent agreement** = articles where both gave the same `topic_correct` answer,
  divided by articles both answered.
- **Cohen's kappa** = (observed agreement - chance agreement) / (1 - chance agreement),
  where chance agreement is the sum over answers of (share of A's answers) × (share of
  B's answers). 1 is perfect, 0 is no better than chance. Read roughly: below 0.4 weak,
  0.4-0.6 moderate, 0.6-0.8 good, above 0.8 very good.

If kappa is below 0.4, the rules above are not clear enough: discuss the disagreements,
make the rules more precise, and label a fresh sample before reporting accuracy.
