# ACCEPTANCE — the ten unforgivables, as tests

The baby EMP (CF Discord Agent.md, 2026-07-15) ends with: *"The ten resentments
are already an acceptance-test checklist: each 'unforgivable' is a test the
agent must pass before it earns trust."* This file is that bridge, made literal.
Run `python3 -m pytest` — these are not aspirations, they are the suite.

| # | Unforgivable (dossier rank) | Enforced by | Proven by |
|---|------------------------------|-------------|-----------|
| 1 | **Silent failure** — breaks or does nothing, says nothing | `LoopRun.__exit__` writes a typed outcome in all paths; a run that reports nothing is recorded as `protocol_violation` with traceback | `test_unforgivable_silence.py::test_run_that_says_nothing_is_a_protocol_violation`, `::test_crash_mid_run_still_writes_outcome_with_traceback`; stress "session death: 200 chaotic runs" |
| 2 | **Overconfidence on thin/stale info** — "it works it works" | Claims require openable evidence (`CompletionClaim` refuses empty evidence); RuleVerifier refutes missing files and unconcluded runs; ModelVerifier treats unparseable praise as INSUFFICIENT, never verified; staleness annotation makes old data look old | `::test_claims_require_evidence`, `::test_rule_verifier_refutes_missing_files`, `::test_model_verifier_unparseable_means_insufficient_never_verified`; `test_unforgivable_time.py::test_annotation_makes_age_visible_in_text` |
| 3 | **Context-loss / misattribution** | Ledger requires an author on every entry; supersession keeps lineage (no gaslit corrections); `as_of()` reconstructs what was known when | `test_unforgivable_memory.py::test_no_anonymous_memory`, `::test_supersession_keeps_lineage_no_gaslighting`, `::test_as_of_reads_what_was_known_then` |
| 4 | **Time-blindness** (the substrate) | Bitemporal stamps everywhere; naive timestamps refused; half-life staleness per volatility; newest-wins; schedules are verifiable state | all of `test_unforgivable_time.py`; stress "time attack" (2,000 skewed events) |
| 5 | **Acting before understanding** (the air-strike) | The Witness's only act is recording opinions + staging drafts; outbound requires a human's approval; investigation (the read) is written before anything is proposed | `test_witness_integration.py::test_outbound_is_staged_never_fired`; `test_unforgivable_coordination.py::test_nothing_fires_unapproved` |
| 6 | **Scope-drift / can't say no** | `[]` is a legitimate model answer → loud `nothing_new`; N is first-class and returnable; T without ≥3 POVs + owner + revisit is refused; unresolved Ts surface as hidden nos | `test_witness_integration.py::test_empty_opinions_is_nothing_new_not_manufactured_usefulness`; `test_unforgivable_identity.py::test_no_is_first_class_and_returnable`, `::test_unresolved_t_surfaces_as_hidden_no`; stress "sycophancy pressure" |
| 7 | **No clear owner / turd-drop** | `Pass` requires a named receiver, a real ask (≥5 words), and context; lifecycle is tracked; overdue passes surface | `test_unforgivable_coordination.py::test_turd_drop_is_a_type_error`, `::test_pass_lifecycle_and_tracking`; stress "pass fuzz" (3,000 transitions) |
| 8 | **Boundary tone/confidentiality error** | Privacy lives in the conversation key: DM→public raises without a human-logged declassification; distinct humans' DMs never cross; every outbound is staged behind a human | `::test_dm_never_flows_to_channel_without_declassification`, `::test_dms_of_different_humans_never_cross`; stress "privacy fuzz" (5,000 flows) |
| 9 | **Fake multi-agent coordination** | Coordination is auditable files (passes with comment threads and transition history), not choreography claims; the receiver's prompt is generated from the pass itself | `::test_receiver_prompt_carries_the_thread`, `::test_pass_lifecycle_and_tracking` |
| 10 | **Unverifiable sub-agent context** | Completion claims bind to loop runs; a claim referencing a run that never concluded is refuted; verdicts and trust compound per maker in the ledger | `test_unforgivable_silence.py::test_rule_verifier_checks_loop_run_reality`, `::test_trust_compounds_in_the_ledger` |

**Watch-list unforgivables** (newer/rarer, from the dossier):

| Watch item | Enforced by | Proven by |
|------------|-------------|-----------|
| Hallucinated embodiment ("let me eyeball the pixels") | embodiment linter; EMPs fail strict validation | `test_unforgivable_identity.py::test_embodiment_language_is_linted` |
| soul.md / continuity theater | `SoulRefusalError` by filename; session epitaphs state the agent died | `::test_soul_files_are_refused_by_name`; `test_unforgivable_memory.py::test_epitaph_the_agent_dies_the_record_survives` |
| Lossy compaction / session death | flush-before-compact enforced; empty flush must be explicit | `test_unforgivable_memory.py::test_flush_before_compact_enforced` |
| Runaway cost | `max_turns` can never be None/0; budget exhaustion is a typed outcome; quiet loops go dormant; heartbeats respect active hours | `test_unforgivable_silence.py::test_unbounded_loops_are_unrepresentable`, `::test_budget_exhaustion_is_a_typed_outcome_not_a_hang`, `::test_nothing_new_is_loud_and_two_make_dormant` |

One honest caveat, stated the way the dossier would want it stated: these tests
prove the *harness* refuses the failure modes. They cannot prove a *model*
seated in it is wise. That gap is exactly why verification is external, staged
actions wait for humans, and trust compounds per-maker instead of being assumed.
