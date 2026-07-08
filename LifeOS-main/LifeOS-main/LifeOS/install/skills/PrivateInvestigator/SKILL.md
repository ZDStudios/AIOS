---
name: PrivateInvestigator
description: "Ethical people-finding and identity verification using 15 parallel research agents (45 concurrent search threads) across people-search aggregators, social media x-ray searches, public records (voter, property, court portals, professional licenses), reverse lookups (phone, email, image, username enumeration), and tiered Google dorking. Confidence-scored results (HIGH/MEDIUM/LOW/POSSIBLE) requiring 3+ matching identifiers. Workflows: FindPerson, SocialMediaSearch, PublicRecordsSearch, ReverseLookup, VerifyIdentity. Stops immediately if purpose shifts toward harassment or stalking. USE WHEN find person, locate person, reconnect, lost contact, old friend, reverse phone lookup, who owns this email, reverse image search, find by username, verify identity, people search, public-data background check, who is this caller. NOT FOR structured due-diligence or company/entity intelligence investigations (use _OSINT) or general web research synthesis (use Research)."
effort: high
---

## Customization

**Before executing, check for user customizations at:**
`~/.claude/LIFEOS/USER/CUSTOMIZATIONS/SKILLS/PrivateInvestigator/`

If this directory exists, load and apply any PREFERENCES.md, configurations, or resources found there. These override default behavior. If the directory does not exist, proceed with skill defaults.


## 🚨 MANDATORY: Voice Notification (REQUIRED BEFORE ANY ACTION)

**You MUST send this notification BEFORE doing anything else when this skill is invoked.**

1. **Send voice notification**:
   ```bash
   curl -s -X POST http://localhost:31337/notify \
     -H "Content-Type: application/json" \
     -d '{"message": "Running the WORKFLOWNAME workflow in the PrivateInvestigator skill to ACTION"}' \
     > /dev/null 2>&1 &
   ```

2. **Output text notification**:
   ```
   Running the **WorkflowName** workflow in the **PrivateInvestigator** skill to ACTION...
   ```

**This is not optional. Execute this curl command immediately upon skill invocation.**

# PrivateInvestigator - Ethical People Finding

## What It Does

Finds people and verifies identities using public data only. It fans out 15 parallel research agents (5 types, 3 each — 45 concurrent search threads) across people-search aggregators, social media, public records, and reverse lookups, then scores results by confidence (HIGH/MEDIUM/LOW/POSSIBLE) requiring 3+ matching identifiers before it trusts a match.

## The Problem

Finding a real person from a name, a phone number, or an email is scattered across dozens of sources — people-search sites, county records, court portals, social platforms, reverse-lookup services — and no single one gives you the answer. Common names make it worse: search "John Smith" and you get thousands of people, most of them the wrong one. Run the searches one at a time and you either give up before you've covered enough sources or you act on a single weak match and contact the wrong person. This skill runs the sources in parallel and refuses to call a match real until several independent identifiers line up.

## How It Works

**Public data only.** No hacking, pretexting, or authentication bypass — every technique here is legal and ethical. The work runs as a parallel investigation: 15 research agents launch in one message, each running sub-searches, and findings get cross-checked and confidence-scored before anything is reported.

## Workflow Routing

| Workflow | Trigger | File |
|----------|---------|------|
| FindPerson | "find person", "locate", "search for [person]", "reconnect", "lost contact" — full parallel-agent investigation | `Workflows/FindPerson.md` |
| SocialMediaSearch | "social media search" — cross-platform social media investigation | `Workflows/SocialMediaSearch.md` |
| PublicRecordsSearch | "public records" — government and official records search | `Workflows/PublicRecordsSearch.md` |
| ReverseLookup | "reverse lookup" — phone, email, image, username searches | `Workflows/ReverseLookup.md` |
| VerifyIdentity | "verify identity" — confirm correct person match | `Workflows/VerifyIdentity.md` |

**When executing a workflow, output this notification:**
```
Running the **WorkflowName** workflow in the **PrivateInvestigator** skill to ACTION...
```

## When to Activate

### Direct People-Finding
- "find [person]", "locate [person]", "search for [person]"
- "reconnect with [person]", "looking for lost contact"
- "find an old friend", "locate a former coworker"

### Reverse Lookup
- "reverse phone lookup", "who owns this email"
- "reverse image search", "find person by username"

### Investigation
- "background check" (public data only)
- "what can you find about [person]"
- "research [person]"

## Research Strategy

**MANDATORY: Extensive Parallel Research**

Every investigation uses **15 parallel research agents** (5 types × 3 each):

**Agent Types:**
1. **ClaudeResearcher** (3 agents) - People search aggregators, professional records, location intelligence, comprehensive identity, public records, education/alumni
2. **GeminiResearcher** (3 agents) - Alternative identities, multi-perspective synthesis, historical context
3. **GrokResearcher** (3 agents) - Social media deep search, contrarian analysis, real-time intelligence
4. **CodexResearcher** (3 agents) - Username enumeration, Google dorking, technical profiles

**Each agent executes 3 sub-searches** = **45 parallel search threads** per investigation

**Launch Pattern:** All 15 agents launch in a SINGLE message with multiple Task tool calls.

## Core Capabilities

### 1. People Search Aggregators
| Service | Type | Best For |
|---------|------|----------|
| TruePeopleSearch | Free | Best free option, fresh data |
| FastPeopleSearch | Free | Basic lookups, no signup |
| Spokeo | Freemium | Social media aggregation (120+ networks) |
| BeenVerified | Paid | Comprehensive background data |

### 2. Social Media Investigation
- **Facebook:** Google x-ray searches, mutual friends, groups
- **LinkedIn:** Boolean search, alumni networks
- **Instagram/Twitter/TikTok:** Username patterns, cross-platform correlation

### 3. Public Records
- **Voter Registration:** Most states publicly available
- **Property Records:** County assessor/recorder sites
- **Court Records:** PACER (federal), state court portals, CourtListener
- **Business Filings:** Secretary of State websites
- **Professional Licenses:** State licensing boards

### 4. Reverse Lookup
- **Phone:** CallerID, NumLookup, carrier lookup
- **Email:** Epieos, Holehe, Hunter.io
- **Image:** PimEyes, TinEye, Google/Yandex Images
- **Username:** Sherlock, WhatsMyName, Namechk

### 5. Google Dorking
```
site:linkedin.com "John Smith" "Software Engineer"
site:facebook.com "lives in" "Austin" "marketing"
filetype:pdf resume "Jane Doe" "San Francisco"
```

## Investigation Methodology

### Information Hierarchy

**Tier 1: Foundation Data**
- Full name (and variations/maiden names)
- Approximate age or date of birth
- Last known location
- Context (school, workplace, relationship)

**Tier 2: Primary Research**
- People search aggregators
- Social media presence scan
- Google dorking

**Tier 3: Deep Investigation**
- Public records searches
- Reverse lookups on discovered info
- Cross-platform correlation
- Associate/family network mapping

**Tier 4: Verification**
- Multi-source confirmation
- Timeline consistency check
- Photo verification
- Confidence scoring

## Confidence Scoring

| Level | Criteria | Action |
|-------|----------|--------|
| **HIGH** | 3+ unique identifiers match across independent sources | Safe to contact |
| **MEDIUM** | 2 identifiers match, timeline consistent | Verify before contact |
| **LOW** | Single source or name-only match | Needs more investigation |
| **POSSIBLE** | Partial match, requires verification | Do not act without more data |

## Dealing with Common Names

1. **Add Specificity** - Include location, age, employer, school
2. **Cross-Reference** - Match DOB + address patterns across sources
3. **Family Connections** - Verify through known relatives
4. **Timeline Analysis** - Does the life history make sense?
5. **Multiple Identifiers** - Require 3+ matching data points

## Legal & Ethical Boundaries

### GREEN ZONE (Allowed)
✅ Search public records (property, court, voter, business)
✅ Access publicly posted social media content
✅ Use people search aggregator sites
✅ Perform reverse lookups on public data
✅ Google dorking with public search operators

### RED ZONE (Never Cross)
❌ Access data behind login walls without authorization
❌ Bypass authentication or security measures
❌ Use pretexting or impersonation
❌ Access private databases (credit, financial, medical)
❌ Stalk, harass, or intimidate subjects
❌ Access PI-only databases without license

## When to STOP

- If the purpose shifts to harassment or stalking
- If the subject has clearly opted out of contact
- If investigation requires illegal methods
- If you suspect the requestor has malicious intent

## Examples

**Example 1: Finding an Old College Friend**
```
User: "Help me find my college roommate from 2005, John Smith from Austin"
→ Routes to FindPerson.md
→ Launches 15 parallel research agents
→ Cross-references people search + LinkedIn alumni + property records
→ Verifies identity through timeline analysis
→ Reports findings with HIGH confidence
```

**Example 2: Reverse Phone Lookup**
```
User: "Who called from 512-555-1234?"
→ Routes to ReverseLookup.md
→ Runs phone through CallerID, NumLookup
→ Cross-references with people search aggregators
→ Reports owner name, location, carrier
```

**Example 3: Social Media Investigation**
```
User: "Find Jane Doe's social media, she's a marketing professional in Denver"
→ Routes to SocialMediaSearch.md
→ LinkedIn Boolean search + Google x-ray
→ Username enumeration if handle discovered
→ Reports all accounts with MEDIUM/HIGH confidence
```

---

**Related Documentation:**
- Complete workflow details in `Workflows/` directory
- Integration with Research skill for parallel agent orchestration

## Gotchas

- **Ethical framework is mandatory.** Legitimate purposes only — reconnection, due diligence, safety. No stalking or harassment.
- **15 parallel agents can hit rate limits on public records APIs.** Stagger launches if services throttle.
- **Verify findings across multiple sources.** Single-source results are unreliable.

## Execution Log

After completing any workflow, append a single JSONL entry:

```bash
echo '{"ts":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'","skill":"PrivateInvestigator","workflow":"WORKFLOW_USED","input":"8_WORD_SUMMARY","status":"ok|error","duration_s":SECONDS}' >> ~/.claude/LIFEOS/MEMORY/SKILLS/execution.jsonl
```

Replace `WORKFLOW_USED` with the workflow executed, `8_WORD_SUMMARY` with a brief input description, and `SECONDS` with approximate wall-clock time. Log `status: "error"` if the workflow failed.
