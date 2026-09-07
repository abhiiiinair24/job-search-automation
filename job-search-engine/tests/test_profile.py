from jobsearch.profile import CandidateProfile, default_profile


def test_default_profile_uses_stated_years_of_experience():
    profile = default_profile(years_of_experience=4.0)
    assert profile.years_of_experience == 4.0


def test_default_profile_years_of_experience_is_overridable():
    profile = default_profile(years_of_experience=6.5)
    assert profile.years_of_experience == 6.5


def test_default_profile_includes_stated_core_skills():
    profile = default_profile()
    # A sample of skills explicitly provided in the candidate's background.
    for skill in ["java", "python", "spring boot", "kafka", "aws", "kubernetes"]:
        assert skill in profile.skills


def test_default_profile_includes_stated_genai_skills():
    profile = default_profile()
    for skill in ["pytorch", "langchain", "langgraph", "rag", "mcp"]:
        assert skill in profile.skills


def test_default_profile_includes_stated_data_engineering_skills():
    profile = default_profile()
    for skill in ["pyspark", "hadoop", "bigquery", "etl"]:
        assert skill in profile.skills


def test_default_profile_does_not_invent_skills():
    profile = default_profile()
    # Technologies never mentioned in the candidate's stated background.
    for not_a_skill in ["rust", "elixir", "haskell", "cobol"]:
        assert not_a_skill not in profile.skills


def test_default_profile_domain_experience_matches_stated_background():
    profile = default_profile()
    assert "financial payments systems" in profile.domain_experience
    assert "backend and distributed systems" in profile.domain_experience


def test_default_profile_has_no_invented_projects():
    # No named projects were provided, so this should stay empty rather
    # than being filled in with guesses.
    profile = default_profile()
    assert profile.projects == []


def test_default_profile_prioritizes_buffalo():
    profile = default_profile()
    assert "buffalo" in [loc.lower() for loc in profile.preferred_locations]


def test_candidate_profile_is_a_plain_dataclass_usable_standalone():
    profile = CandidateProfile(
        years_of_experience=1.0,
        skills={"rust": 3.0},
        target_roles={"backend engineer": 2.0},
        domain_experience=["gaming"],
        projects=["a side project"],
    )
    assert profile.skills == {"rust": 3.0}
    assert profile.projects == ["a side project"]
