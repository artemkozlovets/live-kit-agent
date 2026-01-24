---
description: Plan a feature through Socratic Q&A - builds spec progressively from conversation
tags: [planning, spec, socratic]
---

# /spec [feature-name]

**Socratic feature planning**: Ask → Dig deeper with "Why?" → Build spec progressively

---

## How to Use

```
/spec
```

That's it. I'll create a minimal spec and start a conversation to fill it in.

---

## The Flow

```
/spec
         ↓
┌─────────────────────────────────────────────┐
│  1. ASK NAME & CREATE spec                  │
│     docs/specs/[your-name]-spec.md          │
│     (just header, sections added as needed) │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  2. ADAPTIVE Q&A                            │
│     Ask → "Why?" follow-up → Update spec    │
│     Summarize before moving topics          │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  3. CODEBASE RECON                          │
│     Find related code, add Integration      │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  4. SYNTHESIZE REQUIREMENTS                 │
│     Extract from conversation, confirm      │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│  5. FINALIZE                                │
│     Status → 🟡 Ready for Review            │
│     On approval → 🟢 Approved               │
└─────────────────────────────────────────────┘
```

---

## Step 1: Name and Create Spec

**First, ask**: "What would you like to name this spec? (e.g., `user-auth`, `caching`, `postgres-connection`)"

Once user provides a name, create `docs/specs/[user-chosen-name]-spec.md` with ONLY:

```markdown
# Feature Spec: [Name]

> Created: [date]
> Status: 🔴 Discovery

---

<!-- Sections added as we discuss -->
```

Then say: "Created `docs/specs/[name]-spec.md`. Let's figure out what you need.

**Tell me in a sentence or two: what do you want to build?**"

---

## Step 2: Adaptive Q&A

### Core Rules:

1. **Ask 1 question at a time**
2. **Always follow up with "Why?"** - Dig one level deeper before moving on
3. **Update spec after each meaningful answer** - Add sections as they emerge
4. **Summarize before changing topics** - Confirm understanding first

---

### The "Why?" Rule

After ANY answer, ask ONE "why?" follow-up to dig deeper:

```
User: "I want to cache API responses"
Claude: "Why caching? Is it latency, cost, or rate limits?"
User: "Rate limits - hitting 100/min cap"
Claude: "Got it. [Updates spec with that context]"
```

---

### Summarize Before Moving On

Before switching topics, confirm understanding:

```
"Here's what I understand about the problem:
- Users hit rate limits (100/min) during bulk ops
- This blocks workflows mid-task
- Caching could reduce calls by ~60%

Correct? Anything to add?"
```

Then update spec and continue.

---

### Adaptive Questions (NOT fixed order)

Pick the **most useful next question** based on gaps. Use judgment.

| Topic | Example Questions |
|-------|-------------------|
| Problem | What problem? Who has it? What if we don't build it? |
| Solution | Simplest version? How would someone use it? |
| Edge Cases | Invalid input? What if X fails? Worst bug? |
| Success | How will you know it works? |

---

### Build Spec Progressively

**DON'T** create empty `[pending]` placeholders.
**DO** add sections as they emerge from conversation:

```markdown
## Problem
Users hit API rate limits (100/min) during bulk operations.
This blocks workflows and frustrates users.

## Solution
Cache responses for 5 min. Check cache before calling API.
```

---

## Step 3: Codebase Recon

After Q&A:
1. Use Task tool with `subagent_type=Explore`
2. Find related existing code
3. Add **Integration** section to spec

---

## Step 4: Synthesize Requirements

Extract from conversation and add to spec:

```markdown
## Requirements

### Must-Have
- [ ] Cache API responses for 5 minutes
- [ ] Check cache before API calls

### Nice-to-Have
- [ ] Cache invalidation endpoint

### Out of Scope
- Distributed caching (single-node only)
```

Ask: "Here are the requirements I extracted. Anything wrong or missing?"

---

## Step 5: Finalize

When requirements are confirmed:

1. Update status to `🟡 Ready for Review`
2. Ask: "Approve spec?"
3. On approval:
   - Update status to `🟢 Approved`

---

## Summary

```
/spec

"What would you like to name this spec?" → docs/specs/[your-name]-spec.md
        (discovery → approved)
```

**Key behaviors:**
- Name chosen upfront (no renaming at the end)
- Adaptive questions + "Why?" follow-ups
- Summarize before moving on
