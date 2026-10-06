# Development Rules

These rules apply to all code, tests, tooling, and documentation in this
repository. `PLAN.md` defines the product contract and `IMPLEMENTATION.md`
defines the staged delivery and verification workflow.

## Project workflow

- Update the implementation status in `IMPLEMENTATION.md` within each stage
  branch. The completion evidence and next-stage marker must be part of the same
  stage PR before it is merged, not a separate follow-up bookkeeping PR.
- Never record work performed in this repository in `week-summary` or another
  personal weekly-work log.

## 1. Keep dependencies clean

- Every direct dependency must provide functionality that the project currently
  uses. Before adding one, verify that the standard library, platform, or an
  existing dependency cannot solve the problem clearly with little code.
- Pin every dependency exactly. Python requirements use `==`; npm dependencies
  use exact version strings without `^`, `~`, tags, or ranges. Keep lock and
  constraint files current.
- Review the full dependency tree after each dependency change. Remove unused,
  duplicate, or superseded direct dependencies and run the relevant integrity,
  audit, test, and build checks.
- Do not add a package only to avoid writing a small amount of straightforward,
  well-tested code.

## 2. Prefer conservative, robust implementations

- Choose mature, explicit, well-understood patterns over clever abstractions or
  new technology without a demonstrated need.
- Prefer deterministic behavior, bounded inputs, clear failure modes, and code
  that can be debugged without specialized knowledge.
- Optimize for correctness and maintainability before flexibility or novelty.

## 3. Keep solutions simple

- Use the smallest design that completely satisfies the current requirement.
- Avoid additional layers, wrappers, services, generators, frameworks, and
  tools unless their concrete reduction in effort or risk clearly exceeds the
  complexity they introduce.
- Do not build extension points, compatibility paths, or general-purpose
  infrastructure for hypothetical future requirements.

## 4. Prefer small local implementations to large dependencies

- When only a few small, stable functions are needed from a library, prefer a
  focused local implementation with tests instead of adding the entire library.
- Port code only when its license permits reuse. Preserve required attribution
  and document non-obvious behavior or provenance.
- Do not locally reimplement security-sensitive functionality, cryptography,
  authentication primitives, complex protocol parsers, or other functionality
  where a maintained specialist dependency materially reduces risk.
