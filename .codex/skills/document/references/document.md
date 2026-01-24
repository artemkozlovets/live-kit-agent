---
description: Generate focused documentation for specific codebase features with context and file references
tags: [documentation, explain, codebase, reference, knowledge]
---

# Codebase Documentation Generator

Generate concise, human-readable documentation for specific features, topics, or questions about the ServiceBay codebase. Creates well-researched explanations with file references for easy navigation.

## 🎯 Purpose

This command helps create targeted documentation that:
- **Explains how things work** - Not just what, but why and how
- **Provides context** - By exploring the entire codebase for related code
- **Enables navigation** - With clickable file links to specific lines
- **Stays concise** - Short but informative for human understanding
- **Remains accurate** - Based on actual codebase exploration, not assumptions

## 📋 User Input Required

When invoking this command, the user will provide:
- **Topic/Feature**: What to document (e.g., "voice pipeline", "customer verification")
- **Question**: Specific question to answer (e.g., "how does session state work?")
- **Scope**: Optional - specific files, directories, or components to focus on

## 🔍 Research Process (Required)

Before writing documentation, you MUST:

### 1. Explore the Codebase Thoroughly
- Use Task tool with `subagent_type=Explore` for comprehensive discovery
- Search for related files using Glob patterns
- Grep for relevant keywords, functions, classes
- Read key files to understand implementation details
- Trace dependencies and relationships

### 2. Identify Key Components
- Entry points (routes, webhooks, endpoints)
- Core logic (services, managers, handlers)
- Data layer (repositories, schemas, migrations)
- Integration points (external APIs, WebSocket)
- Configuration (environment variables, constants)

### 3. Understand the Flow
- How do components interact?
- What is the data flow?
- What are the dependencies?
- Where are the critical decision points?
- What are potential failure points?

## ✍️ Documentation Structure

Save all documentation to: `docs/documentations/[topic-name].md`

### Required Sections:

```markdown
# [Feature/Topic Name]

> **Last Updated**: [Date]
> **Status**: [Production/Beta/Deprecated]

## Overview
Brief 2-3 sentence summary of what this feature does and why it exists.

## How It Works
Step-by-step explanation of the process:
1. Entry point and trigger
2. Main processing flow
3. Key decision points
4. Output/result

## Key Components

### [Component Name 1]
- **Purpose**: What it does
- **Location**: [filename.ts:123](path/to/filename.ts#L123)
- **Key Methods**: List important functions
- **Dependencies**: What it relies on

### [Component Name 2]
- **Purpose**: What it does
- **Location**: [filename.ts:456](path/to/filename.ts#L456)
- **Key Methods**: List important functions
- **Dependencies**: What it relies on

## Data Flow

[Brief description or simple diagram of how data moves through the system]

1. Input → [Component A](path/to/file.ts#L123)
2. Processing → [Component B](path/to/file.ts#L456)
3. Storage → [Component C](path/to/file.ts#L789)
4. Output → [Component D](path/to/file.ts#L012)

## Configuration

**Environment Variables**:
- `ENV_VAR_NAME` - What it controls
- `ANOTHER_VAR` - What it controls

**Feature Flags** (if applicable):
- `FEATURE_FLAG_NAME` - When to enable/disable

## Important Notes

- Critical behaviors or gotchas
- Performance considerations
- Security considerations
- Known limitations

## Related Documentation

- [Related Feature 1](../path/to/doc.md)
- [Related Feature 2](../path/to/doc.md)
- External docs (if any)

## File References

Quick links to all mentioned files:
- [Main entry point](path/to/file.ts#L123) - Brief description
- [Service layer](path/to/file.ts#L456) - Brief description
- [Data layer](path/to/file.ts#L789) - Brief description
```

## 📝 Writing Guidelines

### DO:
✅ **Explain the "why"** - Not just what code does, but why it exists
✅ **Use simple language** - Avoid jargon unless necessary
✅ **Provide context** - How it fits in the larger system
✅ **Link to code** - Use `[filename.ts:123](path/to/filename.ts#L123)` format
✅ **Be concise** - Short paragraphs, bullet points, clear sections
✅ **Include examples** - Real-world usage scenarios when helpful
✅ **Note edge cases** - Important behaviors or gotchas

### DON'T:
❌ **Include full code blocks** - Unless absolutely necessary for understanding
❌ **Copy-paste comments** - Synthesize information, don't duplicate
❌ **Make assumptions** - Always explore the actual code
❌ **Be verbose** - Keep it concise and scannable
❌ **Skip research** - Always use Task/Explore for thorough discovery

## 🔗 File Link Format

Always use clickable markdown links with line numbers:

**Format**: `[display-text](relative/path/to/file.ts#L123)`

**Examples**:
- `[VoiceStreamManager:701](packages/api/src/websocket/voice-stream-manager.ts#L701)`
- `[SessionManager](packages/api/src/services/session-manager.ts)`
- `[Tool Registry](packages/api/src/tools/registry.ts#L45-L67)` (for ranges)

**Tips**:
- Use relative paths from repository root
- Include line numbers when referencing specific code
- Use descriptive text (not just "click here")
- Format: `#L123` for single line, `#L123-L145` for range

## 🎯 Documentation Examples

### Example 1: Feature Documentation
**User Request**: "Document the voice pipeline"

**Your Process**:
1. Use Task tool to explore `packages/api/src/websocket/`
2. Read VoiceStreamManager, session manager, tool executor
3. Trace the flow from Twilio webhook to OpenAI API
4. Identify all key components and their relationships
5. Create `docs/documentations/voice-pipeline.md`
6. Summarize what was documented

### Example 2: Specific Question
**User Request**: "How does customer verification work?"

**Your Process**:
1. Search for customer-related files (services, repositories, tools)
2. Read customer.service.ts, customer-check-tool.ts
3. Understand the verification logic and flag system
4. Trace the flow from phone check to database lookup
5. Create `docs/documentations/customer-verification.md`
6. Summarize the findings

### Example 3: Technical Concept
**User Request**: "Explain the singleton pattern usage"

**Your Process**:
1. Grep for "getInstance" or "private static instance"
2. Find all singletons (repositories, services, registry)
3. Explain why singletons are used (connection pooling, etc.)
4. Document the pattern with examples
5. Create `docs/documentations/singleton-pattern.md`
6. Summarize the pattern usage across the codebase

## 📊 Completion Summary

After creating documentation, provide the user with:

```markdown
## Documentation Complete ✅

**Created**: `docs/documentations/[topic-name].md`

**What's Included**:
- Overview and purpose
- [X] key components documented
- Data flow explanation
- [Y] file references with line numbers
- Configuration details
- Important notes and gotchas

**Key Files Documented**:
- [File 1](path) - Brief description
- [File 2](path) - Brief description
- [File 3](path) - Brief description

**Related Features**:
- Feature A - Linked in doc
- Feature B - Linked in doc

**Total Files Explored**: [X]
**Total Lines Referenced**: [Y]
```

## 🚀 Quick Start

**For Users**:
1. Invoke: `/document`
2. Specify what to document: "Document the [feature/topic]"
3. Wait for exploration and documentation
4. Review the generated markdown in `docs/documentations/`

**For the Agent**:
1. Receive user's topic/feature/question
2. Create TodoWrite task list
3. Use Task tool (Explore) for comprehensive discovery
4. Read key files and trace dependencies
5. Create well-structured documentation
6. Save to `docs/documentations/[topic-name].md`
7. Provide completion summary to user

## ⚙️ Advanced Features

### Code Block Usage (Minimal)
Only include code blocks when:
- Showing configuration examples
- Demonstrating API usage
- Explaining complex logic that needs visual reference

Keep code snippets to **5-10 lines maximum**.

### Diagrams (Optional)
Use simple text-based flow when helpful:
```
User Call → Twilio → WebSocket → VoiceStreamManager → OpenAI API
                                        ↓
                                  Tool Executor
                                        ↓
                                   Database
```

### Cross-References
Link to other documentation when features are related:
- Other docs in `docs/documentations/`
- Official docs in `docs/architecture/`
- Planning docs in `docs/plans/`

## 💡 Pro Tips

1. **Start Broad, Then Narrow**: Explore the entire feature area before focusing on details
2. **Follow the Flow**: Trace the actual execution path through the code
3. **Note Patterns**: ServiceBay uses specific patterns (singletons, repositories, tools)
4. **Check Recent Changes**: Look at git history for context on why things exist
5. **Test Understanding**: If you can't explain it simply, explore more
6. **Link Generously**: More links = easier navigation for readers
7. **Update Existing**: If documentation already exists, update instead of recreate

## 🔒 Quality Checklist

Before completing, verify:
- [ ] Thorough codebase exploration performed
- [ ] All key components identified and explained
- [ ] File links are accurate with correct line numbers
- [ ] Flow is clear and logical
- [ ] No assumptions - everything based on actual code
- [ ] Concise but complete
- [ ] Saved to `docs/documentations/` folder
- [ ] Summary provided to user

---

**Ready to generate accurate, concise documentation for any part of the ServiceBay codebase.**

