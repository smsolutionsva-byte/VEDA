# Document decomposition — a document is not an activity

## Principle

A document contains evidence. Evidence must be decomposed into **atomic
observations**. Only eligible observations are resolved against schedule
activities. The whole document must never be treated as one schedule-activity
observation.

## Old dataflow (the bug)

```
FILE -> extract text -> ONE evidence record per page/blank-line block
     -> classify that whole block -> match the whole block to ONE activity
```

A Daily Construction Report whose page had no blank-line breaks (or was a
flattened table) became **one** evidence record holding the entire page. That
record was then classified using whatever words happened to appear anywhere on
the page ("Welder" in a manpower row -> "Welding") and matched to a single
activity with an absurd confidence.

## New dataflow

```
FILE
 └─ TEXT ACQUISITION           veda/pipeline/documents.acquire_text
      native text first; [page N]-only / image-only / too-short  ->
      ExtractionRequired  (file.extract_state = 'extraction_required',
                           NO evidence, NO activity match, review raised)
 └─ DOCUMENT CLASSIFICATION    documents.classify_document
      DAILY_CONSTRUCTION_REPORT / DAILY_PROGRESS_REPORT / SITE_DIARY /
      EXCEL_PROGRESS_REGISTER / ISSUE_REGISTER / RESOURCE_REPORT / UNKNOWN
 └─ SECTION EXTRACTION         documents.segment
      report_metadata | work_progress | manpower | equipment | target |
      issue | weather | signoff   (generic heading vocabulary, no project ids)
 └─ ATOMIC OBSERVATION EXTRACTION   documents.decompose  (one parser per section)
      each WORK_PROGRESS row  -> one ACTIVITY_PROGRESS observation with
        description, location, unit, total_qty, planned_today, achieved_today,
        plan_next_day, cumulative_qty, percent_complete   (blank stays null)
      each MANPOWER / EQUIPMENT row -> one context observation
      each issue row -> one ISSUE observation (reference, raised date,
        work_affected, plan_start)
 └─ OBSERVATION-TYPE ROUTING
      activity_progress / general  -> schedule activity resolver
      issue                        -> issue / risk engine (affected activity
                                      resolved from its own "work affected" text)
      manpower/equipment/weather/report_metadata/signoff/target -> stored as
                                      context, state='context', never matched
 └─ ACTIVITY RESOLUTION  (per observation)   veda/pipeline/linking.link_evidence
      hybrid retrieval + engineering risk policy, PLUS a deterministic
      exact-identity resolver: if exactly one schedule activity states the same
      work (normalised description, disambiguated by location) that IS the
      identity, independent of ranker order.
 └─ CONFIDENCE / CONSTRAINT REASONING
      identity confidence (e.g. 0.97, labelled NOT empirically calibrated) is
      separate from schedule-write authority (always gated).
 └─ VALIDATION / HUMAN REVIEW   per ambiguous observation, never per page
 └─ GOVERNED SCHEDULE CHANGE    proposal -> dry-run -> approval -> verified write
```

## The six entities stay distinct

| concept                | table            |
|------------------------|------------------|
| SourceDocument         | `files`          |
| ExtractedObservation   | `evidence` (+ `observation_type`, `section`, `row_index`, `raw_text`, `raw_values_json`, `observation_key`, `raw_date`, `date_interpretations_json`) |
| ScheduleActivity       | `activities`     |
| EvidenceLink           | `evidence_links` |
| ProposedScheduleChange | `proposals`      |
| HumanDecision          | `reviews`        |

## Observation record (new / changed columns on `evidence`)

| column | meaning |
|---|---|
| `observation_type` | `activity_progress` \| `manpower` \| `equipment` \| `weather` \| `issue` \| `target` \| `report_metadata` \| `signoff` \| `general` |
| `document_type` | classifier output for the source document |
| `section` | which section the observation came from |
| `row_index` | 1-based row/line within the section |
| `raw_text` | verbatim source line(s) for the observation |
| `raw_values_json` | structured values (quantities, manpower counts, issue fields …) |
| `raw_date` / `date_interpretations_json` | ambiguous dates: raw string + every calendar-valid interpretation, ranked, with a reason. `date` holds the preferred ISO value only; the raw is never overwritten. |
| `observation_key` | `sha256(file_sha · page · section · row · normalised_content)` — deterministic identity so re-processing reconciles instead of duplicating |
| `extraction_method` / `extraction_confidence` | provenance of the extraction |

## Dates

`veda/pipeline/dates.interpret(raw, context_dates)` never mutates the raw value.
`10.03.2017` in a report that also contains `21-Sep-17`, `26-Jul-17` and
`4-Oct-17` yields:

```
raw                       "10.03.2017"
normalized                "2017-10-03"
date_format_interpretation "MM.DD.YYYY"
confidence                "high"
ambiguous                 true
interpretations           [2017-10-03 (0.90), 2017-03-10 (0.53)]
reason  "MM.DD.YYYY preferred over DD.MM.YYYY: numeric date with an ambiguous
         day/month order; within 1d of other project dates."
```

## Regression fixture

`tools/make_project_218_fixture.py` writes
`sample_data/Project_218_P6_Style_Activities.csv` and a real text-extractable
`sample_data/Daily_Construction_Report_218_TEXT_EXTRACTABLE.pdf`.
`tools/dcr_pipeline_acceptance_test.py` drives the pipeline offline and checks
all 20 documented pass conditions. Project 218 is **only** a fixture; no
production module references its names or ids.
