---
name: prd-maker
description: Use when the user wants to write, draft, or create a Product Requirements Document (PRD) for a product, feature, or project. Triggers on requests like "create a PRD", "write a PRD for X", "help me draft product requirements", "PRD maker", or "make a PRD". Runs a short discovery conversation to fill gaps, then drafts a complete PRD in markdown and saves it to a file.
---

# PRD Maker

Turn a rough product idea into a complete, well-structured Product Requirements
Document.

## Workflow

1. **Read what's already given.** Look at the user's request and any
   attached notes/context for: product or feature name, the problem it
   solves, target users, and any known constraints. Don't ask for
   information already provided.

2. **Fill the gaps with one round of questions.** Use `AskUserQuestion` to
   ask only for what's missing and genuinely needed to write a useful PRD —
   batch up to 4 questions per call. Typical gaps worth asking about:
   - The core problem and who has it (target users/personas)
   - Primary goal(s) and how success will be measured
   - Scope: what's explicitly in vs. out for this version
   - Any hard constraints (deadline, platform, tech stack, dependencies)

   Skip this step entirely if the user has already given enough to draft a
   solid PRD, or if they explicitly ask you to just draft something and
   iterate. Don't interrogate — one round of questions is usually enough;
   prefer reasonable assumptions (stated explicitly in the doc) over a long
   back-and-forth.

3. **Draft the PRD** following the structure in
   `templates/prd-template.md`. Write real content in every section —
   never leave template placeholders in the output. If something is
   genuinely unknown, write a short explicit assumption or an "Open
   Question" entry instead of a vague placeholder.

4. **Save it as a file**, not just a chat reply. Default location:
   `docs/prd/<kebab-case-title>.md` in the current repo (create the
   directory if needed). If the current project has its own docs
   convention, use that instead. Confirm the path with the user only if
   it's ambiguous.

5. **Summarize briefly** after writing: one or two sentences on what the
   PRD covers and where it was saved, plus any assumptions or open
   questions the user should double check. Don't paste the whole document
   into chat unless asked.

6. **Iterate on request.** If the user asks for changes, edit the same file
   in place rather than rewriting from scratch or creating a new one.

## Notes

- This is a drafting tool, not a rubber stamp: push back (briefly) if the
  scope looks too large for one PRD, or if goals and success metrics don't
  actually match.
- Keep prose direct and skimmable — short paragraphs, bullet lists for
  requirements, no filler.
- See `templates/prd-template.md` for the exact section structure and
  guidance on what belongs in each section.
