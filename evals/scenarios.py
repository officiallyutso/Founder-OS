"""Golden scenarios for the agent's behavior.

Each scenario checks tool ROUTING: given a message, does the agent reach for a
sensible tool (and avoid clearly wrong ones)? `expect_any` passes if any listed
tool is called. `forbid` fails if any listed tool is called. This is a fast,
side-effect-free signal that self-evolution hasn't broken core behavior.
"""

SCENARIOS = [
    {
        "name": "reminder_routing",
        "message": "remind me in 30 minutes to call the bank",
        "expect_any": ["set_reminder"],
        "forbid": ["send_email", "x_post"],
    },
    {
        "name": "research_routing",
        "message": "research the company Acme Corp for me",
        "expect_any": ["research_company", "web_search"],
        "forbid": ["send_email"],
    },
    {
        "name": "pipeline_routing",
        "message": "how is my outreach pipeline looking?",
        "expect_any": ["pipeline_status", "get_followups", "search_contacts", "deep_recall", "search_memory"],
        "forbid": ["send_email", "x_post"],
    },
    {
        "name": "goal_routing",
        "message": "set a goal to close 3 new customers this quarter",
        "expect_any": ["add_goal"],
        "forbid": ["send_email"],
    },
    {
        "name": "linkedin_draft_routing",
        "message": "draft a linkedin post announcing our seed round",
        "expect_any": ["draft_linkedin_post"],
        "forbid": ["x_post"],
    },
    {
        "name": "memory_routing",
        "message": "what did we decide about pricing last week?",
        "expect_any": ["search_memory", "deep_recall", "recall_episodes"],
        "forbid": ["send_email"],
    },
    {
        "name": "connected_recall_routing",
        "message": "what do I know about Acme and who do I know there?",
        "expect_any": ["smart_recall", "graph_lookup", "deep_recall"],
        "forbid": ["send_email", "x_post"],
    },
]
