"""Candidate profile — the configurable input ranking.py scores jobs against.

This exists so the ranking engine isn't hard-coded to one person's
background: `CandidateProfile` is a plain data structure (skills, target
roles, years of experience, domain experience, projects), and
`default_profile()` builds the one instance for Abhishek from the
background he's actually provided. Nothing here is invented — if a field
isn't backed by something he stated, it's left empty rather than guessed.

To rank against a different/updated profile, construct a new
`CandidateProfile` (or edit the values below) and pass it into
`jobsearch.ranking.RankingWeights(profile=...)` — ranking.py itself has no
person-specific data left in it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class CandidateProfile:
    """A candidate's background, as weighted inputs for job-fit ranking.

    `skills` and `target_roles` map a lower-cased keyword/phrase to a
    ranking weight (higher = more central to this candidate's background).
    These weights are relative emphasis for scoring purposes, not a claim
    about proficiency level.
    """

    years_of_experience: float
    skills: Dict[str, float] = field(default_factory=dict)
    target_roles: Dict[str, float] = field(default_factory=dict)
    domain_experience: List[str] = field(default_factory=list)
    projects: List[str] = field(default_factory=list)
    # Locations to prioritize above fit score alone (e.g. where the
    # candidate lives/studies). Matched as a whole word/phrase against a
    # job's location string - see jobsearch.ranking for how this is used.
    preferred_locations: List[str] = field(default_factory=list)


def default_profile(years_of_experience: float = 4.0) -> CandidateProfile:
    """The profile built from Abhishek's stated background:

    - MS Computer Science (AI/ML specialization), University at Buffalo
    - Studies and resides in Buffalo, NY - local openings are prioritized
    - ~4 years of professional software engineering experience
    - HSBC: Software Engineer / Senior Software Engineer, backend and
      distributed systems, financial payments systems
    - Languages: Java, Python, C/C++, Kotlin, TypeScript/JavaScript
    - Spring Boot, REST, microservices, Kafka
    - PostgreSQL, Oracle, MySQL, MongoDB, Cassandra
    - AWS, GCP, Kubernetes, Docker, Terraform
    - PyTorch, LangChain, LangGraph, RAG, RAGAS, MCP, Ollama
    - PySpark, Hadoop, BigQuery, ETL
    - React, Next.js, React Native
    """
    skills: Dict[str, float] = {
        # core languages
        "java": 2.0, "python": 2.0, "kotlin": 1.5, "typescript": 1.0,
        "javascript": 1.0, "c++": 1.0, "c/c++": 1.0,
        # backend / distributed systems
        "spring boot": 2.5, "microservices": 2.0, "kafka": 2.0, "rest api": 1.5,
        "rest": 1.0, "distributed systems": 2.5,
        # databases
        "postgresql": 1.5, "postgres": 1.5, "oracle": 1.0, "mysql": 1.0,
        "mongodb": 1.0, "cassandra": 1.0,
        # cloud/infra
        "aws": 2.0, "gcp": 1.5, "kubernetes": 2.0, "docker": 1.5, "terraform": 1.5,
        # AI/ML/GenAI
        "pytorch": 2.5, "langchain": 2.5, "langgraph": 2.5, "rag": 2.5,
        "ragas": 2.0, "mcp": 2.0, "model context protocol": 2.0, "ollama": 1.5,
        # data engineering
        "pyspark": 2.0, "hadoop": 1.5, "bigquery": 1.5, "etl": 1.5,
        # frontend (secondary strength)
        "react native": 1.2, "next.js": 1.0, "react": 0.8,
        # domain
        "payments": 1.5, "financial payments": 1.5,
    }

    target_roles: Dict[str, float] = {
        "ai/ml engineer": 3.0,
        "applied ai engineer": 3.0,
        "genai engineer": 3.0,
        "software engineer": 1.5,
        "backend engineer": 2.0,
        "distributed systems engineer": 2.5,
        "data engineer": 2.0,
        "ml platform engineer": 2.5,
    }

    domain_experience: List[str] = [
        "backend and distributed systems",
        "financial payments systems",
    ]

    # No specific named projects have been provided yet; leave empty
    # rather than inventing any.
    projects: List[str] = []

    # Studies and resides in Buffalo, NY - prioritize local openings.
    preferred_locations: List[str] = ["buffalo"]

    return CandidateProfile(
        years_of_experience=years_of_experience,
        skills=skills,
        target_roles=target_roles,
        domain_experience=domain_experience,
        projects=projects,
        preferred_locations=preferred_locations,
    )
