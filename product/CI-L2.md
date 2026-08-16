# L2 CI - Semantic review (post-pilot)

## Purpose

LLM-assisted review of whether narrative claims and confidence language are supported by package evidence.

## Default policy

**Flag, do not hard-block** until a design partner calibrates false-positive rates.

## Example checks

- Conclusion sentences cite outputs or overrides that exist  
- Judgments are not presented as master data facts  
- Material qty changes have reason_code + evidence_refs  
- out_of_scope respected in narrative  

## Dependency

Requires stable L1 packages. Do not sequence L2 before L1 green on the pilot pack type.
