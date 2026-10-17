# Curriculum sequence cardinality guard

The v1 full MaleCNS curriculum declares one sequence per stage, split, and
world seed. Its loader currently compares sets of seeds, so two distinct
directories labelled with one seed can be added while all declared seeds remain
present and still reach model loading. This is a data-selection defect, not evidence of
actual training.

Before loading the large connectome, reject a stage/split unless its sequence
count equals the configured seed count and each configured seed occurs exactly
once. Preserve the smoke profile and the existing order of valid sequences.
Keep the v2 54-job corpus separate: this guard does not establish rollout
identity, source authenticity, or distinct sample bytes. No physical capture or
training is authorized by a passing v1 guard.

Evidence: a regression test must show two distinct directories with the same
seed are refused before the absent-model check; a correctly selected stage must
still reach the absent-model check. Run the focused suite and connected
connectome regression suite.
