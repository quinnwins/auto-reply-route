# Auto-Reply Route Map: Autonomous Engineering Canonical Route

- **Sessions Analyzed**: 50
- **Canonical Steps**: 8
- **Transitions Modeled**: 98

## State Transition Graph

```mermaid
flowchart TD
    Step1["1. [VERIFY_QA] You are a senior [PATH] engineer and code auditor on the REALZ team. Review all [NUM] bugs in 'Tier [NUM]: Critical Flaws & Regressions'. For each bug: [NUM]. Inspect the live code at current HEAD and working tree using view_file or grep_search. [NUM]. Adversarially verify whether the flaw is present in the codebase right now. [NUM]. Check surrounding code, design tokens (Gallery Dawn vs Editorial Noir), contrast ratios, and layout shifts. [NUM]. Verify if any tests currently assert these exact classes or strings. [NUM]. Provide a rigorous verdict for each: - Status: [CONFIRMED BUG - TRIAGED FOR FIX] vs [FALSE POSITIVE / ALREADY FIXED] - Exact file path and current line numbers - Live code snippet - Expert critique (why an expert rejects it, Apple HIG / Zero Layout Shift / Contrast / Zero Plumbing adherence) - Precise recommended fix Here are the [NUM] bugs to investigate: [NUM]. Visual Craft: Dark-Glass Price Inputs on Porcelain Sheet File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: Min and Max price inputs still have hardcoded Editorial Noir dark-glass classes: `className='... [PATH] [PATH] text-white placeholder:[PATH] focus-visible:border-[#c9a15d][PATH]'` Check if this produces low contrast on Gallery Dawn Porcelain sheet (#FFFCF7). [NUM]. Visual Craft: Layout Shift on Filter Chip Selection File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: Toggles font weight on click: `selected ? 'border-primary bg-primary text-primary-foreground shadow-xs font-semibold' : '... font-medium'` Check if toggling between font-medium and font-semibold causes layout shift / twitch. [NUM]. Mobile Ergonomics: [NUM]:[NUM] Contrast on Filter Stepper Buttons in Sunlight File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: Stepper icons (Minus, Plus) are hardcoded to colors.editorialIvory (#FFF9F1) on colors.editorialSurfaceElevated (#E7D7C8). Check contrast ratio and color tokens. [NUM]. Mobile Ergonomics: Severe Sub-44pt Hitbox on Landscape Home Feed Rail (32pt) File & Lines: [PATH](tabs)[PATH:tsx]:[PORT], [NUM], [NUM] Reported Flaw: LANDSCAPE_HOME_FEED_MENU_BUTTON_SIZE = [NUM] with hitSlop={isLandscapeHomeFeed ? { top: [NUM], bottom: [NUM], left: [NUM], right: [NUM] } : undefined}. Check touch target dimensions and Apple HIG compliance. [NUM]. Mobile Ergonomics: Hardcoded Hex #1b1712 on Mobile Comment Composer Send Button File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: sendButtonDisabled has backgroundColor: '#1b1712', and sendButton has backgroundColor: '#C9A15D'. Check current styles in [PATH:tsx] and colors tokens. [NUM]. Mobile Ergonomics: Safari Landscape Notch Collision on Web Dock File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: isLandscapePhone ? ' bottom-[NUM] left-[NUM] top-[NUM] w-[NUM] ...' Check if left-[NUM] ignores env(safe-area-inset-left). [NUM]. Editorial Tone: Egregious Backend Plumbing in Comments Empty State File & Lines: [PATH:tsx]:[PORT] Reported Flaw: body='The discussion request failed, so this is not an empty thread. Try again to reconnect.' Check if this violates the Zero Plumbing Law. Be thorough, cite exact line numbers, and produce a structured, expert report."]
    Step1 -->|Primary (3%)| Step2
    Step1_B2["[VERIFY_QA] Use a subagent to review this"]
    Step1 -.->|qa_defensive (2%)| Step1_B2
    Step1_B3["[ARCH_DESIGN] proceed with plan"]
    Step1 -.->|alternative (1%)| Step1_B3
    Step1_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step1 -.->|fallback (0%)| Step1_B4
    Step2["2. [SCAFFOLD_BUILD] add anything that needs my own QA to Qa needed folder"]
    Step2 -->|Primary (27%)| Step3
    Step2_B2["[SCAFFOLD_BUILD] contact unmasking is that what we wnt yes or no? or do we wnat to maintain stuff in our own ecosystem, jsut answer. Like allow calling from app itself like uber when you can call uber wihtout a personal phone number being exchanged"]
    Step2 -.->|qa_defensive (26%)| Step2_B2
    Step2_B3["[SCAFFOLD_BUILD] is that in my QA needed file or a sperate one"]
    Step2 -.->|alternative (26%)| Step2_B3
    Step2_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step2 -.->|fallback (0%)| Step2_B4
    Step3["3. [SCAFFOLD_BUILD] contact unmasking is that what we wnt yes or no? or do we wnat to maintain stuff in our own ecosystem, jsut answer. Like allow calling from app itself like uber when you can call uber wihtout a personal phone number being exchanged"]
    Step3 -->|Primary (3%)| Step4
    Step3_B2["[VERIFY_QA] Use a subagent to review this"]
    Step3 -.->|qa_defensive (2%)| Step3_B2
    Step3_B3["[ARCH_DESIGN] proceed with plan"]
    Step3 -.->|alternative (1%)| Step3_B3
    Step3_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step3 -.->|fallback (0%)| Step3_B4
    Step4["4. [VERIFY_QA] Use a subagent to review this"]
    Step4 -->|Primary (27%)| Step5
    Step4_B2["[VERIFY_QA] check agin with a subagent team"]
    Step4 -.->|qa_defensive (26%)| Step4_B2
    Step4_B3["[SCAFFOLD_BUILD] do this"]
    Step4 -.->|alternative (26%)| Step4_B3
    Step4_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step4 -.->|fallback (0%)| Step4_B4
    Step5["5. [VERIFY_QA] check agin with a subagent team"]
    Step5 -->|Primary (94%)| Step6
    Step5_B2["[VERIFY_QA] You are the Modals, Sheets & Overlays Auditor for REALZ Web. Audit all dialogs, sheets, bottom drawers, and overlays in `[PATH]`: [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` (desktop side-panel drawer and modal modes) [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH]` (StagingProductDrawer, ShoppablePhotoOverlay) For each [PATH]: - Check backdrop overlay styling (blur, opacity, tint). - Check dialog container surface (`bg-card`, borders, shadows). - Check form inputs, textareas, segmented controls, stepper buttons, and action CTAs. - Identify any remaining dark relics (`bg-black`, `bg-[#0b0907]`, `bg-[#12100d]`, `#c9a15d`, `[PATH]`). - Provide exact line numbers and concrete refactoring code for every issue found."]
    Step5 -.->|qa_defensive (0%)| Step5_B2
    Step5_B3["[DEBUG_REPAIR] yes fix"]
    Step5 -.->|alternative (0%)| Step5_B3
    Step5_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step5 -.->|fallback (0%)| Step5_B4
    Step6["6. [SCAFFOLD_BUILD] make it perfect after done review with a design subagent team again its normal to go through progresssiosn to make things perfect"]
    Step6 -->|Primary (94%)| Step7
    Step6_B2["[VERIFY_QA] have grok [NUM] extra high review your work"]
    Step6 -.->|qa_defensive (0%)| Step6_B2
    Step6_B3["[ARCH_DESIGN] proceed with plan"]
    Step6 -.->|alternative (0%)| Step6_B3
    Step6_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step6 -.->|fallback (0%)| Step6_B4
    Step7["7. [SCAFFOLD_BUILD] is it perfect like [PATH] as best you can do, dont add any slop to try to oversugar it"]
    Step7 -->|Primary (94%)| Step8
    Step7_B2["[VERIFY_QA] Use a subagent to review this"]
    Step7 -.->|qa_defensive (0%)| Step7_B2
    Step7_B3["[ARCH_DESIGN] proceed with plan"]
    Step7 -.->|alternative (0%)| Step7_B3
    Step7_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step7 -.->|fallback (0%)| Step7_B4
    Step8["8. [SCAFFOLD_BUILD] how about now give me the lowdown"]
    Step8_B2["[VERIFY_QA] have grok [NUM] extra high review your work"]
    Step8 -.->|qa_defensive (0%)| Step8_B2
    Step8_B3["[ARCH_DESIGN] proceed with plan"]
    Step8 -.->|alternative (0%)| Step8_B3
    Step8_B4["[RELEASE_OPS] I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code"]
    Step8 -.->|fallback (0%)| Step8_B4
```

## Canonical Route Sequence & Branching Map

### Step 1: You are a senior [PATH] engineer and code auditor on the REALZ team. Review all [NUM] bugs in "Tier [NUM]: Critical Flaws & Regressions". For each bug: [NUM]. Inspect the live code at current HEAD and working tree using view_file or grep_search. [NUM]. Adversarially verify whether the flaw is present in the codebase right now. [NUM]. Check surrounding code, design tokens (Gallery Dawn vs Editorial Noir), contrast ratios, and layout shifts. [NUM]. Verify if any tests currently assert these exact classes or strings. [NUM]. Provide a rigorous verdict for each: - Status: [CONFIRMED BUG - TRIAGED FOR FIX] vs [FALSE POSITIVE / ALREADY FIXED] - Exact file path and current line numbers - Live code snippet - Expert critique (why an expert rejects it, Apple HIG / Zero Layout Shift / Contrast / Zero Plumbing adherence) - Precise recommended fix Here are the [NUM] bugs to investigate: [NUM]. Visual Craft: Dark-Glass Price Inputs on Porcelain Sheet File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: Min and Max price inputs still have hardcoded Editorial Noir dark-glass classes: `className="... [PATH] [PATH] text-white placeholder:[PATH] focus-visible:border-[#c9a15d][PATH]"` Check if this produces low contrast on Gallery Dawn Porcelain sheet (#FFFCF7). [NUM]. Visual Craft: Layout Shift on Filter Chip Selection File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: Toggles font weight on click: `selected ? "border-primary bg-primary text-primary-foreground shadow-xs font-semibold" : "... font-medium"` Check if toggling between font-medium and font-semibold causes layout shift / twitch. [NUM]. Mobile Ergonomics: [NUM]:[NUM] Contrast on Filter Stepper Buttons in Sunlight File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: Stepper icons (Minus, Plus) are hardcoded to colors.editorialIvory (#FFF9F1) on colors.editorialSurfaceElevated (#E7D7C8). Check contrast ratio and color tokens. [NUM]. Mobile Ergonomics: Severe Sub-44pt Hitbox on Landscape Home Feed Rail (32pt) File & Lines: [PATH](tabs)[PATH:tsx]:[PORT], [NUM], [NUM] Reported Flaw: LANDSCAPE_HOME_FEED_MENU_BUTTON_SIZE = [NUM] with hitSlop={isLandscapeHomeFeed ? { top: [NUM], bottom: [NUM], left: [NUM], right: [NUM] } : undefined}. Check touch target dimensions and Apple HIG compliance. [NUM]. Mobile Ergonomics: Hardcoded Hex #1b1712 on Mobile Comment Composer Send Button File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: sendButtonDisabled has backgroundColor: "#1b1712", and sendButton has backgroundColor: "#C9A15D". Check current styles in [PATH:tsx] and colors tokens. [NUM]. Mobile Ergonomics: Safari Landscape Notch Collision on Web Dock File & Lines: [PATH:tsx]:[PORT]-[NUM] Reported Flaw: isLandscapePhone ? " bottom-[NUM] left-[NUM] top-[NUM] w-[NUM] ..." Check if left-[NUM] ignores env(safe-area-inset-left). [NUM]. Editorial Tone: Egregious Backend Plumbing in Comments Empty State File & Lines: [PATH:tsx]:[PORT] Reported Flaw: body="The discussion request failed, so this is not an empty thread. Try again to reconnect." Check if this violates the Zero Plumbing Law. Be thorough, cite exact line numbers, and produce a structured, expert report.
- **Stratum**: `VERIFY_QA`
- **Canonical Representative Prompt**: "You are a senior UI/UX engineer and code auditor on the REALZ team.
Review all 7 bugs in "Tier 1: Critical Flaws & Regressions". For each bug:
1. Inspect the live code at current HEAD and working tree using view_file or grep_search.
2. Adversarially verify whether the flaw is present in the codebase right now.
3. Check surrounding code, design tokens (Gallery Dawn vs Editorial Noir), contrast ratios, and layout shifts.
4. Verify if any tests currently assert these exact classes or strings.
5. Provide a rigorous verdict for each:
   - Status: [CONFIRMED BUG - TRIAGED FOR FIX] vs [FALSE POSITIVE / ALREADY FIXED]
   - Exact file path and current line numbers
   - Live code snippet
   - Expert critique (why an expert rejects it, Apple HIG / Zero Layout Shift / Contrast / Zero Plumbing adherence)
   - Precise recommended fix

Here are the 7 bugs to investigate:
1. Visual Craft: Dark-Glass Price Inputs on Porcelain Sheet
   File & Lines: client/src/components/TuneFeedSheet.tsx:761-778
   Reported Flaw: Min and Max price inputs still have hardcoded Editorial Noir dark-glass classes:
   `className="... border-white/15 bg-white/5 text-white placeholder:text-white/80 focus-visible:border-[#c9a15d]/60"`
   Check if this produces low contrast on Gallery Dawn Porcelain sheet (#FFFCF7).

2. Visual Craft: Layout Shift on Filter Chip Selection
   File & Lines: client/src/components/TuneFeedSheet.tsx:161-165
   Reported Flaw: Toggles font weight on click:
   `selected ? "border-primary bg-primary text-primary-foreground shadow-xs font-semibold" : "... font-medium"`
   Check if toggling between font-medium and font-semibold causes layout shift / twitch.

3. Mobile Ergonomics: 1.33:1 Contrast on Filter Stepper Buttons in Sunlight
   File & Lines: realz-mobile/src/components/filter-controls.tsx:210-224
   Reported Flaw: Stepper icons (Minus, Plus) are hardcoded to colors.editorialIvory (#FFF9F1) on colors.editorialSurfaceElevated (#E7D7C8).
   Check contrast ratio and color tokens.

4. Mobile Ergonomics: Severe Sub-44pt Hitbox on Landscape Home Feed Rail (32pt)
   File & Lines: realz-mobile/src/app/(tabs)/_layout.tsx:46, 452, 868
   Reported Flaw: LANDSCAPE_HOME_FEED_MENU_BUTTON_SIZE = 32 with hitSlop={isLandscapeHomeFeed ? { top: 0, bottom: 0, left: 6, right: 6 } : undefined}.
   Check touch target dimensions and Apple HIG compliance.

5. Mobile Ergonomics: Hardcoded Hex #1b1712 on Mobile Comment Composer Send Button
   File & Lines: realz-mobile/src/components/CommentsModal/CommentComposer.tsx:206-244
   Reported Flaw: sendButtonDisabled has backgroundColor: "#1b1712", and sendButton has backgroundColor: "#C9A15D".
   Check current styles in CommentComposer.tsx and colors tokens.

6. Mobile Ergonomics: Safari Landscape Notch Collision on Web Dock
   File & Lines: client/src/components/DesktopNavigation.tsx:160-163
   Reported Flaw: isLandscapePhone ? "!bottom-2 !left-2 !top-2 !w-16 ..."
   Check if !left-2 ignores env(safe-area-inset-left).

7. Editorial Tone: Egregious Backend Plumbing in Comments Empty State
   File & Lines: client/src/components/CommentsModal.tsx:1802
   Reported Flaw: body="The discussion request failed, so this is not an empty thread. Try again to reconnect."
   Check if this violates the Zero Plumbing Law.

Be thorough, cite exact line numbers, and produce a structured, expert report."
- **Observation Frequency**: 1 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | add anything that needs my own QA to Qa needed folder | 3.4% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | Use a subagent to review this | 2.0% |
| 3 | 🔀 Alternative | `ARCH_DESIGN` | proceed with plan | 1.4% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.7% |

### Step 2: add anything that needs my own QA to Qa needed folder
- **Stratum**: `SCAFFOLD_BUILD`
- **Canonical Representative Prompt**: "add anything that needs my own QA to Qa needed folder"
- **Observation Frequency**: 5 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | add anything that needs my own QA to Qa needed folder | 27.3% |
| 2 | 🛡️ QA / Defensive | `SCAFFOLD_BUILD` | contact unmasking is that what we wnt yes or no? or do we wnat to maintain stuff in our own ecosystem, jsut answer. Like allow calling from app itself like uber when you can call uber wihtout a personal phone number being exchanged | 26.8% |
| 3 | 🔀 Alternative | `SCAFFOLD_BUILD` | is that in my QA needed file or a sperate one | 26.8% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.1% |

### Step 3: contact unmasking is that what we wnt yes or no? or do we wnat to maintain stuff in our own ecosystem, jsut answer. Like allow calling from app itself like uber when you can call uber wihtout a personal phone number being exchanged
- **Stratum**: `SCAFFOLD_BUILD`
- **Canonical Representative Prompt**: "contact unmasking is that what we wnt yes or no? or do we wnat to maintain stuff in our own ecosystem, jsut answer. Like allow calling from app itself like uber when you can call uber wihtout a personal phone number being exchanged"
- **Observation Frequency**: 1 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | add anything that needs my own QA to Qa needed folder | 3.4% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | Use a subagent to review this | 2.0% |
| 3 | 🔀 Alternative | `ARCH_DESIGN` | proceed with plan | 1.4% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.7% |

### Step 4: Use a subagent to review this
- **Stratum**: `VERIFY_QA`
- **Canonical Representative Prompt**: "Use a subagent  to review this"
- **Observation Frequency**: 3 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | add anything that needs my own QA to Qa needed folder | 27.3% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | check agin with a subagent team | 26.8% |
| 3 | 🔀 Alternative | `SCAFFOLD_BUILD` | do this | 26.8% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.1% |

### Step 5: check agin with a subagent team
- **Stratum**: `VERIFY_QA`
- **Canonical Representative Prompt**: "check agin with a subagent team"
- **Observation Frequency**: 1 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | make it perfect after done review with a design subagent team again its normal to go through progresssiosn to make things perfect | 94.0% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | You are the Modals, Sheets & Overlays Auditor for REALZ Web. Audit all dialogs, sheets, bottom drawers, and overlays in `[PATH]`: [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` (desktop side-panel drawer and modal modes) [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH:tsx]` [NUM]. `[PATH]` (StagingProductDrawer, ShoppablePhotoOverlay) For each [PATH]: - Check backdrop overlay styling (blur, opacity, tint). - Check dialog container surface (`bg-card`, borders, shadows). - Check form inputs, textareas, segmented controls, stepper buttons, and action CTAs. - Identify any remaining dark relics (`bg-black`, `bg-[#0b0907]`, `bg-[#12100d]`, `#c9a15d`, `[PATH]`). - Provide exact line numbers and concrete refactoring code for every issue found. | 0.0% |
| 3 | 🔀 Alternative | `DEBUG_REPAIR` | yes fix | 0.0% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.0% |

### Step 6: make it perfect after done review with a design subagent team again its normal to go through progresssiosn to make things perfect
- **Stratum**: `SCAFFOLD_BUILD`
- **Canonical Representative Prompt**: "make it perfect after done review with a design subagent team again its normal to go through progresssiosn to make things perfect"
- **Observation Frequency**: 1 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | is it perfect like [PATH] as best you can do, dont add any slop to try to oversugar it | 94.0% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | have grok [NUM] extra high review your work | 0.1% |
| 3 | 🔀 Alternative | `ARCH_DESIGN` | proceed with plan | 0.1% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.0% |

### Step 7: is it perfect like [PATH] as best you can do, dont add any slop to try to oversugar it
- **Stratum**: `SCAFFOLD_BUILD`
- **Canonical Representative Prompt**: "is it perfect like 10/10 as best you can do, dont add any slop to try to oversugar it"
- **Observation Frequency**: 1 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | how about now give me the lowdown | 94.0% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | Use a subagent to review this | 0.1% |
| 3 | 🔀 Alternative | `ARCH_DESIGN` | proceed with plan | 0.1% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.0% |

### Step 8: how about now give me the lowdown
- **Stratum**: `SCAFFOLD_BUILD`
- **Canonical Representative Prompt**: "how about now give me the lowdown"
- **Observation Frequency**: 1 occurrences

| Rank | Functional Role | Stratum | Recommended Auto-Reply Prompt | Probability |
|:---:|:---|:---|:---|:---:|
| 1 | 🟢 Primary Forward | `SCAFFOLD_BUILD` | add anything that needs my own QA to Qa needed folder | 94.2% |
| 2 | 🛡️ QA / Defensive | `VERIFY_QA` | have grok [NUM] extra high review your work | 0.1% |
| 3 | 🔀 Alternative | `ARCH_DESIGN` | proceed with plan | 0.1% |
| 4 | 🚪 Fallback / Exit | `RELEASE_OPS` | I want you to deploy a [NUM] subagent team to look over this and ONLY plan no code | 0.0% |
