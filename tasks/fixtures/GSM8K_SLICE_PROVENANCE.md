# GSM8K-style slice fixtures — provenance

**Not** a dump of the [GSM8K](https://github.com/openai/grade-school-math) dataset.

These five word problems are **original** grade-school arithmetic items written for
llm-autobench. They follow the GSM8K *style* (short multi-step word problem,
numeric final answer, chain-of-thought then labelled final line) so we can exercise
the existing mechanical `exact` scorer without downloading or redistributing the
GSM8K corpus.

| Task id | Answer | Notes |
|---|---|---|
| `gsm8k_s01` | 14 | bakery fractions |
| `gsm8k_s02` | 18 | money remaining |
| `gsm8k_s03` | 24 | bus seats |
| `gsm8k_s04` | 60 | weekly mileage |
| `gsm8k_s05` | 44 | path area around rectangle |

Licensing: original prompts committed here under this repo's MIT license.
GSM8K itself is MIT-licensed; we deliberately avoid shipping its items so there
is no dataset-download step and no confusion about which corpus was graded.
