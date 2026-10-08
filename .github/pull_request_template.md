## Summary

Describe the concrete problem and resulting behavior or design direction.

## Related work

Link relevant Issues, contract decisions or owning-repository changes.

## Verification

Describe checks and evidence. Distinguish documentation review, source/tests, artifact verification and live acceptance. State when a category does not apply.

## Compatibility and recovery

For runtime changes, describe API/schema impact, plan/authorization changes, backup/restore conditions and interrupted-operation handling. For documentation-only changes, state whether accepted policy changes.

## Checklist

- [ ] Core/wrapper, application-migration and neighboring service ownership remain clear.
- [ ] Management-entry versions are preserved or an explicit policy change is documented.
- [ ] Relevant verification is complete; no planned capability is described as shipped.
- [ ] Documentation and PROGRESS.md reflect the actual completion state.
- [ ] No secrets, private topology, sensitive data or machine-specific runtime evidence were added.
- [ ] New third-party code/assets have compatible documented licenses, or none were added.
