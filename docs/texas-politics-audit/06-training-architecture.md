# F. Training Architecture — What to Train, What Not to Train, and Where the Labels Are

## 1. The prime directive

**Retrieval beats training for anything that changes or must be cited.** Bill status,
votes, rule text, officeholders, money, registrations — training these into weights
manufactures confident staleness. The model's job is Texas *competence* (procedure,
document genres, reasoning patterns, vocabulary); the corpus's job is Texas *facts*.

Consequently: no continued pretraining on the corpus as a default position. The one
defensible carve-out is a small continued-pretraining/mid-training mix of *timeless*
material — chamber rules, drafting-manual conventions, procedural treatises, historical
session summaries — and only if evals show the base model actually lacks Texas procedure.
Measure first (benchmark categories 1 and 4); train only against a demonstrated gap.

## 2. Where training genuinely pays

### 2.1 Extraction & normalization models (the pipeline's workhorses)
Small, cheap, task-specific models (fine-tuned encoder or small LLM) for:
- journal entry segmentation + action typing
- vote-roll parsing (names → person IDs, Y/N/PNV)
- witness-list row extraction (name / org / position / testified-vs-registered)
- Register preamble field extraction (authority cites, dates, TAC cites)
- bill-text SECTION → statute-cite extraction
- entity resolution (name-variant matching for donors/clients/witnesses) — trained on
  TEC filer crosswalks + hand-adjudicated pairs

These have abundant free labels (below), objective accuracy metrics, and they run
millions of times — exactly where fine-tuning belongs.

### 2.2 Classifiers with naturally labeled data

| Classifier | Free label source | Label pair |
|---|---|---|
| Issue/topic classifier | TLO subject index assignments; HRO topic headings | bill text → subject codes |
| Stance/argument classifier | HRO "Supporters say" / "Opponents say" sections | argument text → pro/con (thousands of professionally written, balanced pairs per session) |
| Support/oppose classifier | Witness-list position field | testimony text (where transcribed) / org+bill context → for/against/on |
| Jurisdiction classifier | Historical referral decisions | bill caption+text → committee |
| Legislative-action classifier | TLO action codes ↔ journal prose describing the same event | journal sentence → action type |
| Rule-action classifier | Register document types | notice text → proposed/adopted/withdrawn/emergency/review |
| Fiscal-impact direction/magnitude | Fiscal-note tables | bill text → cost class (sanity-check use only) |
| Recommendation-outcome mapper | Sunset "Final Results" + interim-report → bill lineage where explicitly stated | recommendation text → enacted/mgmt-action/died; rec ↔ bill pairing |
| Platform-alignment | Planks + RPT priorities vs. bills with known platform positions | bill → aligned/adverse/silent per party |
| Regulatory-outcome | Proposal → adoption pairs in the Register | proposed text → adopted-with-changes/unchanged/withdrawn |

### 2.3 Retriever / reranker training
The corpora generate query–positive–hard-negative triples almost for free:
- HRO analysis ↔ its bill (positive); same-subject different-session bill (hard negative —
  *exactly* the confusion we must beat)
- Register adoption ↔ its proposal; other rules in the same chapter as hard negatives
- Journal action ↔ its TLO action row; same bill different day as hard negative
- AG opinion ↔ statute interpreted; adjacent sections as hard negatives
- Bill-number collision sets (HB 3 across sessions) as *canonical* hard negatives

A domain-tuned reranker that reliably prefers same-session, correct-version evidence is
worth more than any generative fine-tune.

### 2.4 Instruction tuning (targeted, small, curated)
High-quality reasoning exemplars, generated from documents + verified by experts:
- "Read this HRO analysis and brief a client in 5 bullets" (HRO's own DIGEST discipline
  is the template)
- "Given these bill actions and today's date, state what must happen next and by when"
  (deadline reasoning)
- "Compare introduced vs. engrossed and state what changed and who benefits"
- "Given this Register notice, extract deadline, authority, and what a commenter should
  argue" 
- Citation discipline itself: answers that cite journal page / Register cite / version.

Hundreds to low thousands of examples, expert-reviewed — not bulk conversion of the
corpus into synthetic Q&A slop.

### 2.5 ASR/diarization adaptation (if hearing transcription proceeds)
Fine-tune/bias ASR vocabulary on Texas proper nouns (member names, agency acronyms,
"calendars committee", bill-number formats) using committee video + aligned witness lists
and captions where available; speaker-ID models bootstrapped from chair scripts
("The chair recognizes…").

## 3. Explicit non-goals

- **No generative fine-tuning of current facts** (statuses, rosters, totals) — retrieval.
- **No training on paywalled/licensed news text** beyond what licenses permit; metadata
  and links suffice for the narrative layer.
- **No stance model trained to *impute* a legislator's private position** — only to
  classify *stated* positions in cited text. The product line is documented positions,
  not mind-reading.
- **Court-opinion reasoning:** generic legal reasoning is already strong in frontier
  models; do not spend on it. Texas-specific value is the *linkage* layer (which cases
  touch which statutes/rules), which is extraction, not generation.

## 4. Evaluation gates

Every trained component ships only with: a held-out session (train on ≤87R, test on 88R+
style splits — never random row splits, which leak session context); the adversarial sets
from `07-benchmark.md`; and a regression gate on citation validity. For classifiers,
report per-class F1 against the natural labels *and* against a small expert-adjudicated
gold slice (natural labels are noisy: witness positions get miscoded, HRO sections drift
in format across decades).

## 5. Data governance notes

- Natural-label extraction must respect document licensing (state works are public
  record; news and some third-party datasets are not).
- Keep a provenance manifest per training set (which documents, which versions) so any
  extraction bug can be traced and retrained.
- PII: TEC data contains addresses/employers of private individuals; training sets that
  include donor rows should strip street-level PII — the models need patterns, not
  addresses.
