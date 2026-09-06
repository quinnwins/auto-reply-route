from __future__ import annotations

import pytest

from auto_reply_route.classifier import (
    HumanIntentClassifier,
    IntentClassification,
    PromptIntentTier,
)


class TestAdversarialPrefixOverrides:
    """Probing explicit prefix overrides against question and advisory patterns."""

    def test_bracket_prefix_overrides_strategic_question(self):
        """'[4] what feature are we missing here' must yield CODE_BUILD with 4 steps."""
        prompt = '[4] what feature are we missing here'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.CODE_BUILD
        assert res.suggested_steps == 4
        assert res.explicit_prefix_override is True
        assert res.bypass_route_generation is False
        assert res.confidence == 0.99
        assert res.extracted_subject == 'what feature are we missing here'
        assert '4-step route via prefix' in res.reason

    def test_bracket_prefix_overrides_why_question(self):
        """'[12] why is this slow' must yield CODE_BUILD with 12 steps."""
        prompt = '[12] why is this slow'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.CODE_BUILD
        assert res.suggested_steps == 12
        assert res.explicit_prefix_override is True
        assert res.bypass_route_generation is False
        assert res.confidence == 0.99
        assert res.extracted_subject == 'why is this slow'
        assert '12-step route via prefix' in res.reason

    def test_prefix_variations_behavior(self):
        """Comparing bracket, colon, steps prefix vs bare number."""
        # Bracket: explicit override
        r_bracket = HumanIntentClassifier.classify('[4] what feature are we missing here')
        assert r_bracket.tier == PromptIntentTier.CODE_BUILD
        assert r_bracket.explicit_prefix_override is True
        assert r_bracket.suggested_steps == 4

        # Colon: explicit override
        r_colon = HumanIntentClassifier.classify('4: what feature are we missing here')
        assert r_colon.tier == PromptIntentTier.CODE_BUILD
        assert r_colon.explicit_prefix_override is True
        assert r_colon.suggested_steps == 4

        # 'steps:': explicit override
        r_steps = HumanIntentClassifier.classify('4 steps: what feature are we missing here')
        assert r_steps.tier == PromptIntentTier.CODE_BUILD
        assert r_steps.explicit_prefix_override is True
        assert r_steps.suggested_steps == 4

        # Bare number without colon/bracket/steps: does NOT trigger explicit override, falls to DIRECT_ANSWER
        r_bare = HumanIntentClassifier.classify('4 what feature are we missing here')
        assert r_bare.tier == PromptIntentTier.DIRECT_ANSWER
        assert r_bare.explicit_prefix_override is False
        assert r_bare.suggested_steps == 0


class TestHybridQuestionAndCommand:
    """Probing compound inputs containing both explanatory questions and build actions."""

    def test_hybrid_question_plus_command_prioritizes_code_build(self):
        """'What is WebAuthn and can you implement it in auth/login.py'"""
        prompt = 'What is WebAuthn and can you implement it in auth/login.py'
        res = HumanIntentClassifier.classify(prompt)

        # Action verb 'implement' prevents classification as pure question
        assert res.tier == PromptIntentTier.CODE_BUILD
        assert res.suggested_steps == 1
        assert res.bypass_route_generation is False
        assert res.explicit_prefix_override is False
        assert 'concrete engineering feature' in res.reason

    def test_pure_question_counterpart_routes_to_direct_answer(self):
        """Without the action verb, 'What is WebAuthn' routes to DIRECT_ANSWER."""
        prompt = 'What is WebAuthn?'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.DIRECT_ANSWER
        assert res.suggested_steps == 0
        assert res.bypass_route_generation is True
        assert 'informational or conceptual inquiry' in res.reason


class TestRhetoricalQuestions:
    """Probing rhetorical and conversational question forms."""

    def test_rhetorical_can_we_add_button_yields_code_build(self):
        """'can we add a logout button' contains 'add', triggering CODE_BUILD."""
        prompt = 'can we add a logout button'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.CODE_BUILD
        assert res.suggested_steps == 1
        assert res.bypass_route_generation is False

    def test_rhetorical_can_we_launch_today_yields_direct_answer(self):
        """'can we launch today' has no code action verb, triggering DIRECT_ANSWER."""
        prompt = 'can we launch today'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.DIRECT_ANSWER
        assert res.suggested_steps == 0
        assert res.bypass_route_generation is True

    def test_action_verb_asymmetry_deploy_vs_launch(self):
        """'deploy' is in CODE_ACTION_VERBS, but 'launch' is not."""
        res_launch = HumanIntentClassifier.classify('can we launch today')
        res_deploy = HumanIntentClassifier.classify('can we deploy today')

        assert res_launch.tier == PromptIntentTier.DIRECT_ANSWER
        assert res_deploy.tier == PromptIntentTier.CODE_BUILD

    def test_inflection_sensitivity_add_vs_adding(self):
        """'add' matches CODE_ACTION_VERBS, but gerund 'adding' does not."""
        res_add = HumanIntentClassifier.classify('is it hard to add a logout button?')
        res_adding = HumanIntentClassifier.classify('can we discuss adding a logout button?')

        # 'add' triggers code action -> fails question check -> CODE_BUILD
        assert res_add.tier == PromptIntentTier.CODE_BUILD
        # 'adding' does not match add -> question check succeeds -> DIRECT_ANSWER
        assert res_adding.tier == PromptIntentTier.DIRECT_ANSWER


class TestShortQueries:
    """Probing single-word and telegraphic inputs."""

    def test_pricing_with_question_mark_yields_direct_answer(self):
        """'pricing?' ends in '?' without code verbs -> DIRECT_ANSWER."""
        res = HumanIntentClassifier.classify('pricing?')
        assert res.tier == PromptIntentTier.DIRECT_ANSWER
        assert res.suggested_steps == 0
        assert res.bypass_route_generation is True

    def test_bare_pricing_yields_direct_answer(self):
        """'pricing' without '?' correctly yields DIRECT_ANSWER."""
        res = HumanIntentClassifier.classify('pricing')
        assert res.tier == PromptIntentTier.DIRECT_ANSWER
        assert res.suggested_steps == 0
        assert res.bypass_route_generation is True

    def test_roadmap_query_both_variants_yield_direct_answer(self):
        """'roadmap?' and 'roadmap' both match STRATEGIC_ADVISORY_PATTERNS."""
        res_q = HumanIntentClassifier.classify('roadmap?')
        res_bare = HumanIntentClassifier.classify('roadmap')

        assert res_q.tier == PromptIntentTier.DIRECT_ANSWER
        assert res_q.suggested_steps == 0
        assert res_bare.tier == PromptIntentTier.DIRECT_ANSWER
        assert res_bare.suggested_steps == 0

    def test_help_and_status_yield_direct_answer(self):
        """Meta-commands 'help' and 'status' without '?' correctly yield DIRECT_ANSWER."""
        res_help = HumanIntentClassifier.classify('help')
        res_status = HumanIntentClassifier.classify('status')

        assert res_help.tier == PromptIntentTier.DIRECT_ANSWER
        assert res_help.suggested_steps == 0
        assert res_status.tier == PromptIntentTier.DIRECT_ANSWER
        assert res_status.suggested_steps == 0

    def test_help_and_status_with_question_mark_yield_direct_answer(self):
        """'help?' and 'status?' match endswith('?') -> DIRECT_ANSWER."""
        res_help_q = HumanIntentClassifier.classify('help?')
        res_status_q = HumanIntentClassifier.classify('status?')

        assert res_help_q.tier == PromptIntentTier.DIRECT_ANSWER
        assert res_status_q.tier == PromptIntentTier.DIRECT_ANSWER


class TestSarcasticPromptsAndMorphology:
    """Probing sarcastic design critique and grammatical inflections."""

    def test_sarcastic_prompt_without_question_mark_yields_ux_craft_audit(self):
        """'could this button possibly be any uglier' correctly routes to UX_CRAFT_AUDIT."""
        prompt = 'could this button possibly be any uglier'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.UX_CRAFT_AUDIT
        assert res.suggested_steps == 3
        assert res.bypass_route_generation is False

    def test_sarcastic_prompt_with_question_mark_yields_ux_craft_audit(self):
        """'could this button possibly be any uglier?' correctly routes to UX_CRAFT_AUDIT."""
        prompt = 'could this button possibly be any uglier?'
        res = HumanIntentClassifier.classify(prompt)

        assert res.tier == PromptIntentTier.UX_CRAFT_AUDIT
        assert res.suggested_steps == 3
        assert res.bypass_route_generation is False

    def test_ugly_vs_uglier_vs_ugliest_consistency(self):
        """'ugly', 'uglier', and 'ugliest' all consistently match UX_CRAFT_AUDIT."""
        res_ugly = HumanIntentClassifier.classify('this button is ugly')
        res_uglier = HumanIntentClassifier.classify('this button is uglier')
        res_ugliest = HumanIntentClassifier.classify('this button is the ugliest')

        assert res_ugly.tier == PromptIntentTier.UX_CRAFT_AUDIT
        assert res_ugly.suggested_steps == 3

        assert res_uglier.tier == PromptIntentTier.UX_CRAFT_AUDIT
        assert res_uglier.suggested_steps == 3

        assert res_ugliest.tier == PromptIntentTier.UX_CRAFT_AUDIT
        assert res_ugliest.suggested_steps == 3
