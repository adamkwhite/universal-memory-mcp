#!/usr/bin/env python3
"""
Generate test data for performance benchmarking.

Creates realistic conversations with varied sizes and content to match
the README claim of 159 conversations totaling 8.8MB.
"""

import json
import random
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from universal_memory_mcp.conversation_memory import ConversationMemoryServer

# Constants
TECH_TOPICS = [
    "python",
    "javascript",
    "react",
    "nodejs",
    "aws",
    "docker",
    "kubernetes",
    "terraform",
    "api",
    "database",
    "sql",
    "mongodb",
    "redis",
    "git",
    "github",
    "authentication",
    "security",
    "testing",
    "deployment",
    "ci/cd",
    "microservices",
    "machine learning",
    "data science",
    "frontend",
    "backend",
    "devops",
]

CODE_SNIPPETS = [
    """
def process_data(items):
    '''Process a list of items and return results'''
    results = []
    for item in items:
        if validate_item(item):
            results.append(transform_item(item))
    return results
""",
    """
async function fetchUserData(userId) {
    try {
        const response = await fetch(`/api/users/${userId}`);
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('Failed to fetch user:', error);
        throw error;
    }
}
""",
    """
SELECT u.name, u.email, COUNT(o.id) as order_count
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
WHERE u.created_at > '2024-01-01'
GROUP BY u.id, u.name, u.email
HAVING COUNT(o.id) > 5
ORDER BY order_count DESC;
""",
    """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web-app
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web-app
  template:
    metadata:
      labels:
        app: web-app
    spec:
      containers:
      - name: app
        image: myapp:latest
        ports:
        - containerPort: 8080
""",
]

CONVERSATION_TEMPLATES = [
    {
        "type": "code_review",
        "title_template": "Code review: {topic} implementation",
        "content_template": """
I'm reviewing the {topic} implementation and have some questions about the architecture.

Current code:
{code_snippet}

My main concerns are:
1. {concern1}
2. {concern2}
3. {concern3}

What would you recommend for improving this? I'm particularly interested in {specific_interest}.

Also, I've been reading about {related_topic} and wondering if that pattern would apply here.
""",
    },
    {
        "type": "debugging",
        "title_template": "Debugging {topic} issue in production",
        "content_template": """
We're experiencing an issue with our {topic} system in production.

Error message:
```
{error_message}
```

Stack trace shows the problem originates from:
{code_snippet}

I've tried the following approaches:
- {approach1}
- {approach2}
- {approach3}

The issue seems to be related to {related_topic}. Any suggestions for troubleshooting this?
""",
    },
    {
        "type": "architecture",
        "title_template": "Architecture decision: {topic} vs {related_topic}",
        "content_template": """
We need to make a decision about our {topic} architecture.

Current situation:
- {situation1}
- {situation2}
- {situation3}

We're considering two approaches:

Option A: {topic} based solution
{code_snippet}

Option B: {related_topic} based solution
- {benefit1}
- {benefit2}
- {tradeoff1}

What factors should we consider? Our main priorities are {priority1} and {priority2}.
""",
    },
    {
        "type": "learning",
        "title_template": "Learning {topic}: best practices and patterns",
        "content_template": """
I'm trying to understand {topic} better and how it relates to {related_topic}.

From what I understand:
- {understanding1}
- {understanding2}
- {understanding3}

Example I found:
{code_snippet}

Questions:
1. {question1}
2. {question2}
3. {question3}

Can you explain how this connects to {another_topic} and what best practices I should follow?
""",
    },
]

CONCERNS = [
    "performance implications",
    "scalability concerns",
    "security vulnerabilities",
    "maintainability",
    "testing coverage",
    "error handling",
    "memory usage",
    "compatibility issues",
    "dependency management",
    "documentation clarity",
]

ERROR_MESSAGES = [
    "TypeError: Cannot read property 'undefined' of null",
    "ConnectionError: Unable to connect to database",
    "MemoryError: Heap out of memory",
    "AuthenticationError: Invalid credentials",
    "TimeoutError: Request exceeded timeout of 30s",
    "ValidationError: Required field missing",
    "PermissionError: Access denied to resource",
]


class TestDataGenerator:
    """Generate realistic test conversations for benchmarking."""

    def __init__(self, storage_path: str = "~/claude-memory-test"):
        self.storage_path = Path(storage_path).expanduser()
        self.server = ConversationMemoryServer(str(self.storage_path))

    def generate_conversation_content(self, size_category: str) -> Tuple[str, str]:
        """Generate a single conversation with title and content."""
        template = random.choice(CONVERSATION_TEMPLATES)
        topic = random.choice(TECH_TOPICS)
        related_topic = random.choice([t for t in TECH_TOPICS if t != topic])
        another_topic = random.choice(
            [t for t in TECH_TOPICS if t not in [topic, related_topic]]
        )

        # Generate title
        title = template["title_template"].format(
            topic=topic, related_topic=related_topic
        )

        # Generate content
        content = template["content_template"].format(
            topic=topic,
            related_topic=related_topic,
            another_topic=another_topic,
            code_snippet=random.choice(CODE_SNIPPETS),
            concern1=random.choice(CONCERNS),
            concern2=random.choice(CONCERNS),
            concern3=random.choice(CONCERNS),
            specific_interest=random.choice(CONCERNS),
            error_message=random.choice(ERROR_MESSAGES),
            approach1=f"Checking {random.choice(TECH_TOPICS)} configuration",
            approach2=f"Updating {random.choice(TECH_TOPICS)} dependencies",
            approach3=f"Refactoring {random.choice(TECH_TOPICS)} implementation",
            situation1=f"Using {random.choice(TECH_TOPICS)} for {random.choice(['data processing', 'API handling', 'user management'])}",
            situation2=f"Need to scale to {random.choice(['10k', '100k', '1M'])} users",
            situation3=f"Integrating with {random.choice(TECH_TOPICS)} services",
            benefit1=f"Better {random.choice(['performance', 'scalability', 'maintainability'])}",
            benefit2=f"Easier {random.choice(['testing', 'deployment', 'monitoring'])}",
            tradeoff1=f"Increased {random.choice(['complexity', 'cost', 'learning curve'])}",
            priority1=random.choice(
                ["performance", "reliability", "developer experience"]
            ),
            priority2=random.choice(["cost efficiency", "scalability", "security"]),
            understanding1=f"{topic} is used for {random.choice(['data processing', 'service communication', 'state management'])}",
            understanding2=f"It integrates well with {random.choice(TECH_TOPICS)}",
            understanding3=f"Common patterns include {random.choice(['singleton', 'factory', 'observer', 'MVC'])}",
            question1=f"How does {topic} handle {random.choice(['concurrency', 'errors', 'state'])}?",
            question2=f"What's the difference between {topic} and {related_topic}?",
            question3=f"When should I use {topic} vs {another_topic}?",
        )

        # Adjust content size based on category
        if size_category == "small":
            # Target 1-5KB
            while len(content) < 1000:
                content += f"\n\nMore details about {topic}: " + content[:500]
            content = content[:5000]  # Cap at 5KB
        elif size_category == "medium":
            # Target 5-50KB
            while len(content) < 5000:
                content += f"\n\nAdditional context about {topic}:\n{content}"
            content = content[:50000]  # Cap at 50KB
        elif size_category == "large":
            # Target 50-100KB
            while len(content) < 50000:
                extra_content = (
                    f"\n\nDeep dive into {topic} and {related_topic}:\n{content}"
                )
                content += extra_content
            content = content[:100000]  # Cap at 100KB

        return title, content

    async def generate_dataset(
        self, num_conversations: int, start_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Generate a complete dataset of conversations."""
        if start_date is None:
            start_date = datetime.now() - timedelta(days=90)  # 3 months ago

        stats: Dict[str, Any] = {
            "total_conversations": 0,
            "total_size_bytes": 0,
            "size_distribution": {"small": 0, "medium": 0, "large": 0},
            "topics_covered": set(),
            "date_range": {"start": None, "end": None},
        }

        for i in range(num_conversations):
            # Determine size category based on distribution
            # Adjust to get average ~55KB per conversation (8.8MB / 159)
            rand = random.random()
            if rand < 0.15:  # 15% small
                size_category = "small"
            elif rand < 0.45:  # 30% medium
                size_category = "medium"
            else:  # 55% large
                size_category = "large"

            # Generate conversation
            title, content = self.generate_conversation_content(size_category)

            # Generate timestamp (spread across time period)
            days_offset = random.randint(0, 90)
            hours_offset = random.randint(0, 23)
            timestamp = start_date + timedelta(days=days_offset, hours=hours_offset)

            # Add conversation
            result = await self.server.add_conversation(
                content=content, title=title, conversation_date=timestamp.isoformat()
            )

            if result["status"] == "success":
                stats["total_conversations"] += 1
                stats["size_distribution"][size_category] += 1

                # Track file size
                file_path = Path(result["file_path"])
                if file_path.exists():
                    stats["total_size_bytes"] += file_path.stat().st_size

                # Track topics
                stats["topics_covered"].update(result.get("topics", []))

                # Track date range
                if (
                    stats["date_range"]["start"] is None
                    or timestamp < stats["date_range"]["start"]
                ):
                    stats["date_range"]["start"] = timestamp
                if (
                    stats["date_range"]["end"] is None
                    or timestamp > stats["date_range"]["end"]
                ):
                    stats["date_range"]["end"] = timestamp

            if (i + 1) % 10 == 0:
                print(f"Generated {i + 1}/{num_conversations} conversations...")

        # Convert topics set to list for JSON serialization
        stats["topics_covered"] = list(stats["topics_covered"])
        stats["date_range"]["start"] = (
            stats["date_range"]["start"].isoformat()
            if stats["date_range"]["start"]
            else None
        )
        stats["date_range"]["end"] = (
            stats["date_range"]["end"].isoformat()
            if stats["date_range"]["end"]
            else None
        )

        return stats

    def print_stats(self, stats: Dict[str, Any]):
        """Print generation statistics."""
        total_mb = stats["total_size_bytes"] / (1024 * 1024)
        avg_kb = (
            (stats["total_size_bytes"] / stats["total_conversations"]) / 1024
            if stats["total_conversations"] > 0
            else 0
        )

        print("\n=== Generation Statistics ===")
        print(f"Total conversations: {stats['total_conversations']}")
        print(f"Total size: {total_mb:.2f} MB ({stats['total_size_bytes']} bytes)")
        print(f"Average size: {avg_kb:.2f} KB per conversation")
        print("\nSize distribution:")
        print(f"  Small (1-5KB): {stats['size_distribution']['small']}")
        print(f"  Medium (5-50KB): {stats['size_distribution']['medium']}")
        print(f"  Large (50-100KB): {stats['size_distribution']['large']}")
        print(f"\nTopics covered: {len(stats['topics_covered'])}")
        print(
            f"Date range: {stats['date_range']['start']} to {stats['date_range']['end']}"
        )

        # Check against README claims
        print("\n=== README Claim Validation ===")
        print("Claimed: 159 conversations, 8.8MB")
        print(
            f"Generated: {stats['total_conversations']} conversations, {total_mb:.2f}MB"
        )
        if stats["total_conversations"] == 159:
            size_diff = abs(total_mb - 8.8)
            if size_diff < 0.5:  # Within 0.5MB
                print("✅ Matches README claim!")
            else:
                print(f"⚠️  Size difference: {size_diff:.2f}MB")


async def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate test data for performance benchmarking"
    )
    parser.add_argument(
        "--conversations",
        "-n",
        type=int,
        default=159,
        help="Number of conversations to generate (default: 159)",
    )
    parser.add_argument(
        "--storage-path",
        "-p",
        type=str,
        default="~/claude-memory-test",
        help="Storage path for generated data (default: ~/claude-memory-test)",
    )
    parser.add_argument(
        "--clean", action="store_true", help="Clean existing data before generating"
    )

    args = parser.parse_args()

    # Clean if requested
    if args.clean:
        storage_path = Path(args.storage_path).expanduser()
        if storage_path.exists():
            import shutil

            shutil.rmtree(storage_path)
            print(f"Cleaned existing data at {storage_path}")

    # Generate data
    generator = TestDataGenerator(args.storage_path)
    print(f"Generating {args.conversations} conversations...")

    stats = await generator.generate_dataset(args.conversations)
    generator.print_stats(stats)

    # Save stats
    stats_file = Path(args.storage_path).expanduser() / "generation_stats.json"
    with open(stats_file, "w") as f:
        json.dump(stats, f, indent=2)
    print(f"\nStats saved to: {stats_file}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
