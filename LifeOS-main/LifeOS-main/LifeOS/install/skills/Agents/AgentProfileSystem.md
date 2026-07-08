# Agent Profile System

**Simple agent context loading for specialized agent types.**

**Status:** ✅ Redesigned (v2.0.0 - Simplified)
**Date:** 2025-12-18

---

## Core Concept

> **Retirement note (2026):** The `Architect`, `Engineer`, and `Designer` agent *types* were retired. Their `*Context.md` reading-lists below still exist and are loaded onto a **`general-purpose`** agent — this loader never dispatched a static `Architect`/`Engineer`/`Designer` `subagent_type` (it always spawns `general-purpose`), so the system is unchanged; only the role labels no longer correspond to standalone agent types.

When spawning a `general-purpose` agent with a specialized role context (architecture, implementation, design, etc.), each agent needs to know:
1. What their role is
2. Which parts of the LifeOS Skills system are relevant to their work
3. What output format to use

**The Solution**: ONE markdown context file per agent type that acts as a "reading list" pointing to relevant Skills.

---

## Design Philosophy

**SIMPLE, NOT ELABORATE**

This system does NOT:
- ❌ Duplicate content from LifeOS (LifeOS auto-loads at session start)
- ❌ Use elaborate YAML structures with memory blocks
- ❌ Create redundant init prompts
- ❌ Use multiple files with different names per agent

This system DOES:
- ✅ Reference existing Skills (doesn't duplicate them)
- ✅ Use ONE markdown context file per agent type
- ✅ Supplement what LifeOS already provides
- ✅ Act as a curated "reading list" for each agent
- ✅ Leverage our existing Skills system

---

## File Structure

```
~/.claude/skills/Agents/
├── ArchitectContext.md     # Architecture specialist context
├── EngineerContext.md       # Implementation specialist context
├── DesignerContext.md       # UX/UI specialist context
├── ArtistContext.md         # Visual content creator context
├── QATesterContext.md       # Quality assurance specialist context
└── Tools/
    └── LoadAgentContext.ts  # Simple loader utility
```

---

## Context File Format

Each `*Context.md` file follows this simple structure:

```markdown
# [AgentType] Agent Context

**Role**: [One-line role description]
**Model**: opus|sonnet|haiku

---

## Required Knowledge (Pre-load from Skills)

### [Category]
- **skills/Path/To/File.md** - Description of what this provides

---

## Task-Specific Knowledge

Load these dynamically based on task keywords:

- **keyword** → skills/Path/To/Relevant.md

---

## Key Principles (from LifeOS)

[Brief list - these are ALREADY LOADED via LifeOS, just reference them]

---

## Output Format

[Optional template for this agent type's outputs]
```

---

## How It Works

### 1. Agent Spawning (Manual)

When you need to spawn an agent, use the Task tool with the agent's context:

```typescript
// Load the context
const loader = new AgentContextLoader();
const { prompt, model } = loader.generateEnrichedPrompt(
  "Architect",
  "Design a new skill system for handling user preferences"
);

// Spawn the agent with enriched prompt
Task({
  subagent_type: "general-purpose",
  description: "Architecture design task",
  prompt: prompt,
  model: model
});
```

### 2. What Gets Loaded

The agent receives:
1. **LifeOS context** (auto-loaded at session start)
   - Constitutional principles
   - Stack preferences
   - Security protocols
   - Etc.

2. **Agent-specific context** (from `*Context.md` file)
   - Role definition
   - References to relevant Skills
   - Task-specific knowledge pointers
   - Output format guidance

3. **Current task** (provided when spawning)
   - The specific work to be done

### 3. Context Composition

The loader simply concatenates:
```
[Agent Context File Content]

---

## Current Task

[Task Description]
```

That's it. Simple. No elaborate profile system. Just a reading list.

---

## Available Role Contexts

Each row is a reading-list `*Context.md` file loaded onto a **`general-purpose`** agent (not a dispatchable subagent type). The `Architect`, `Engineer`, and `Designer` agent types were retired, but their context files remain for use as role briefs.

| Role Context | Context File | Role |
|------------|--------------|------|
| **Architecture** | ArchitectContext.md | Software architecture specialist |
| **Implementation** | EngineerContext.md | Implementation specialist with TDD focus |
| **Design** | DesignerContext.md | UX/UI design specialist |
| **Artist** | ArtistContext.md | Visual content creator for UL |
| **QATester** | QATesterContext.md | Quality assurance validation (Gate 4) |

---

## CLI Usage

```bash
# List available agent types
bun run ~/.claude/skills/Agents/Tools/LoadAgentContext.ts

# View context for specific agent
bun run ~/.claude/skills/Agents/Tools/LoadAgentContext.ts Architect

# Generate enriched prompt for spawning
bun run ~/.claude/skills/Agents/Tools/LoadAgentContext.ts Architect "Design new skill system"
```

---

## Adding New Agent Types

To add a new agent type:

1. Create `[AgentType]Context.md` in `~/.claude/skills/Agents/`
2. Follow the context file format above
3. Reference relevant Skills (don't duplicate content)
4. Specify model preference (opus/sonnet/haiku)
5. Done!

The loader automatically discovers new context files.

---

## Key Differences from Letta Code

**Letta Code's approach:**
- Multiple files per agent with different names
- Complex profile structures
- Memory blocks that duplicate knowledge
- Elaborate init prompts

**Our approach:**
- ONE file per agent type: `[AgentType]Context.md`
- Simple markdown format
- References to existing Skills (not duplication)
- Leverages LifeOS auto-loading
- Acts as a "reading list" not a knowledge dump

---

## Why This Is Better

1. **No Duplication**: LifeOS already loads constitutional principles, stack preferences, etc. No need to repeat them.

2. **Simple**: One markdown file per agent. Easy to understand, easy to maintain.

3. **Leverages Existing System**: Uses our Skills system as the knowledge repository.

4. **Supplements, Doesn't Replace**: Adds to what LifeOS provides, doesn't try to replace it.

5. **Curated Reading Lists**: Each context file points agents to the relevant parts of our extensive Skills system.

6. **Maintainable**: When Skills change, context files just need reference updates, not content rewrites.

---

## Integration with Task Tool

When spawning agents, the main agent can:

```typescript
// Load agent context
const loader = new AgentContextLoader();
const { prompt, model } = loader.generateEnrichedPrompt(
  agentType,
  taskDescription
);

// Spawn with Task tool
await Task({
  subagent_type: "general-purpose",
  description: shortDescription,
  prompt: prompt,
  model: model
});
```

The spawned agent gets:
- All of LifeOS (auto-loaded)
- Agent-specific context (from *Context.md)
- Current task description

---

## Future Enhancements

Potential future improvements (only if needed):

1. **Dynamic Skill Loading**: If task description matches keywords, automatically append relevant Skill content
2. **Project-Specific Context**: Load `.pai/agent-context.md` for project-specific patterns
3. **Task History**: Track which agents worked on which tasks for continuity
4. **Context Caching**: Cache loaded Skills to avoid repeated file reads

But start simple. The current design may be sufficient.

---

## Migration from v1.0.0 (YAML Profiles)

**Old system (v1.0.0):**
- Used elaborate YAML files (`Architect.yaml`, etc.)
- Had memory blocks that duplicated LifeOS content
- Had redundant init prompts
- Used AgentProfileLoader.ts with complex parsing

**New system (v2.0.0):**
- Uses simple markdown files (`ArchitectContext.md`, etc.)
- References Skills, doesn't duplicate
- Uses LoadAgentContext.ts with simple loading
- Much cleaner and more maintainable

**YAML files are now deprecated.** Use the markdown context files instead.

---

## Summary

**Simple agent context system:**
- ONE markdown file per agent type
- References Skills (doesn't duplicate)
- Supplements LifeOS (doesn't replace)
- Acts as curated "reading list"
- Easy to understand and maintain

**When spawning agents, they get:**
- LifeOS context (auto-loaded)
- Agent-specific context (from *Context.md)
- Current task description

That's it. Simple. Effective. No over-engineering.
