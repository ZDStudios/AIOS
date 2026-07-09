---
name: skill-maker
description: Create new AI OS skills from a plain-English description.
---
# Skill Maker
When asked to create a skill: write a new `SKILL.md` with YAML frontmatter (`name`, `description`)
and numbered, imperative instructions the agent should follow. Save it under `skills/<name>/SKILL.md`,
then tell the user to run `aios update` (or restart) to mount it into every agent.
